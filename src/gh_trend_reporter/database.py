"""SQLite データベース管理レイヤー.

トレンドデータの永続化・キャッシュ・週次分析結果の保存を担当する。
3 つのテーブル（``trending_repos``, ``repo_details``, ``weekly_analyses``）を管理し、
週ラベル（ISO 8601 形式: ``"2025-W03"``）ベースのクエリを提供する。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from gh_trend_reporter.models import RepoDetail, TrendingRepo, WeeklyAnalysis

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trending_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    language TEXT,
    stars INTEGER,
    stars_since INTEGER,
    forks INTEGER,
    since TEXT NOT NULL,
    collected_at DATE NOT NULL,
    UNIQUE(owner, name, since, collected_at)
);

CREATE TABLE IF NOT EXISTS repo_details (
    full_name TEXT PRIMARY KEY,
    topics TEXT,
    readme_excerpt TEXT,
    license TEXT,
    open_issues INTEGER,
    open_prs INTEGER,
    last_pushed TEXT,
    created_at TEXT,
    homepage TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_analyses (
    week_label TEXT PRIMARY KEY,
    analysis_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
"""


class Database:
    """SQLite データベースの接続管理と CRUD 操作を提供する.

    Args:
        db_path: データベースファイルのパス。``":memory:"`` でインメモリ DB を使用。
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """アクティブな DB 接続を返す.

        Raises:
            RuntimeError: ``init()`` が未呼び出しの場合。
        """
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._conn

    def init(self) -> None:
        """DB 接続を開きスキーマを初期化する."""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        """DB 接続を閉じる。既に閉じている場合は何もしない。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- trending_repos ---

    def insert_trending_repo(self, repo: TrendingRepo) -> None:
        """単一の TrendingRepo を挿入する.

        UNIQUE 制約により同一 (owner, name, since, collected_at) の重複はスキップされる。

        Args:
            repo: 挿入する Trending リポジトリデータ。
        """
        self.conn.execute(
            """
            INSERT OR IGNORE INTO trending_repos
                (owner, name, description, language, stars, stars_since, forks, since, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo.owner,
                repo.name,
                repo.description,
                repo.language,
                repo.stars,
                repo.stars_since,
                repo.forks,
                repo.since,
                repo.collected_at.isoformat(),
            ),
        )
        self.conn.commit()

    def insert_trending_repos(self, repos: list[TrendingRepo]) -> int:
        """複数の TrendingRepo を一括挿入する.

        Args:
            repos: 挿入する Trending リポジトリデータのリスト。

        Returns:
            実際に挿入された行数（重複スキップ分を除く）。
        """
        count = 0
        for repo in repos:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO trending_repos
                    (owner, name, description, language, stars,
                     stars_since, forks, since, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo.owner,
                    repo.name,
                    repo.description,
                    repo.language,
                    repo.stars,
                    repo.stars_since,
                    repo.forks,
                    repo.since,
                    repo.collected_at.isoformat(),
                ),
            )
            count += cursor.rowcount
        self.conn.commit()
        return count

    def get_repos_by_date(self, target_date: date, since: str | None = None) -> list[TrendingRepo]:
        """指定日に収集されたリポジトリを取得する.

        Args:
            target_date: 収集日。
            since: ``"daily"`` / ``"weekly"`` でフィルタ。None で全件。

        Returns:
            条件に一致する TrendingRepo のリスト。
        """
        query = "SELECT * FROM trending_repos WHERE collected_at = ?"
        params: list[str] = [target_date.isoformat()]
        if since:
            query += " AND since = ?"
            params.append(since)
        rows = self.conn.execute(query, params).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_repos_by_week(self, week_label: str) -> list[TrendingRepo]:
        """ISO 週ラベルに該当する月曜〜日曜のリポジトリを取得する.

        Args:
            week_label: ISO 週ラベル（例: ``"2025-W03"``）。

        Returns:
            該当週に収集された TrendingRepo のリスト。
        """
        start, end = _week_label_to_date_range(week_label)
        rows = self.conn.execute(
            "SELECT * FROM trending_repos WHERE collected_at BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_previous_week_repos(self, current_week: str, weeks_ago: int = 1) -> list[TrendingRepo]:
        """指定週から N 週前のリポジトリ一覧を取得する.

        Args:
            current_week: 基準となる週ラベル。
            weeks_ago: 何週間前のデータを取得するか（デフォルト: 1）。

        Returns:
            前週に収集された TrendingRepo のリスト。
        """
        start, _ = _week_label_to_date_range(current_week)
        prev_start = start - timedelta(weeks=weeks_ago)
        prev_end = prev_start + timedelta(days=6)
        rows = self.conn.execute(
            "SELECT * FROM trending_repos WHERE collected_at BETWEEN ? AND ?",
            (prev_start.isoformat(), prev_end.isoformat()),
        ).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_new_entries(self, current_week: str) -> list[str]:
        """今週新たに Trending 入りしたリポジトリを特定する.

        Args:
            current_week: 対象の週ラベル。

        Returns:
            前週には存在せず今週初登場の ``"owner/name"`` リスト（ソート済み）。
        """
        current_repos = self.get_repos_by_week(current_week)
        prev_repos = self.get_previous_week_repos(current_week)

        current_names = {f"{r.owner}/{r.name}" for r in current_repos}
        prev_names = {f"{r.owner}/{r.name}" for r in prev_repos}

        return sorted(current_names - prev_names)

    # --- repo_details ---

    def insert_repo_detail(self, detail: RepoDetail) -> None:
        """RepoDetail を挿入または更新する（UPSERT）.

        Args:
            detail: 保存するリポジトリ詳細データ。
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO repo_details
                (full_name, topics, readme_excerpt, license, open_issues,
                 open_prs, last_pushed, created_at, homepage, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                detail.full_name,
                json.dumps(detail.topics),
                detail.readme_excerpt,
                detail.license,
                detail.open_issues,
                detail.open_prs,
                detail.last_pushed.isoformat(),
                detail.created_at.isoformat(),
                detail.homepage,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def get_repo_detail(self, full_name: str, cache_ttl: int = 86400) -> RepoDetail | None:
        """キャッシュ有効期限内の RepoDetail を取得する.

        Args:
            full_name: ``"owner/name"`` 形式のリポジトリ識別子。
            cache_ttl: キャッシュ有効期限（秒）。超過していれば None を返す。

        Returns:
            キャッシュヒット時は RepoDetail、ミスまたは期限切れ時は None。
        """
        row = self.conn.execute(
            "SELECT * FROM repo_details WHERE full_name = ?",
            (full_name,),
        ).fetchone()

        if row is None:
            return None

        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if (datetime.now() - fetched_at).total_seconds() > cache_ttl:
            return None

        owner, name = row["full_name"].split("/", 1)
        return RepoDetail(
            owner=owner,
            name=name,
            full_name=row["full_name"],
            topics=json.loads(row["topics"]) if row["topics"] else [],
            readme_excerpt=row["readme_excerpt"] or "",
            license=row["license"],
            open_issues=row["open_issues"] or 0,
            open_prs=row["open_prs"] or 0,
            last_pushed=datetime.fromisoformat(row["last_pushed"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            homepage=row["homepage"],
        )

    # --- weekly_analyses ---

    def save_weekly_analysis(self, analysis: WeeklyAnalysis) -> None:
        """WeeklyAnalysis を JSON として DB に保存する（UPSERT）.

        Args:
            analysis: 保存する週次分析結果。
        """
        self.conn.execute(
            """
            INSERT OR REPLACE INTO weekly_analyses
                (week_label, analysis_json, generated_at)
            VALUES (?, ?, ?)
            """,
            (
                analysis.week_label,
                analysis.model_dump_json(),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def get_weekly_analysis(self, week_label: str) -> WeeklyAnalysis | None:
        """保存済みの WeeklyAnalysis を読み込む.

        Args:
            week_label: ISO 週ラベル。

        Returns:
            保存済みデータがあれば WeeklyAnalysis、なければ None。
        """
        row = self.conn.execute(
            "SELECT analysis_json FROM weekly_analyses WHERE week_label = ?",
            (week_label,),
        ).fetchone()

        if row is None:
            return None
        return WeeklyAnalysis.model_validate_json(row["analysis_json"])


def _row_to_trending_repo(row: sqlite3.Row) -> TrendingRepo:
    """sqlite3.Row を TrendingRepo モデルに変換する.

    Args:
        row: DB から取得した行データ。

    Returns:
        変換された TrendingRepo インスタンス。
    """
    return TrendingRepo(
        owner=row["owner"],
        name=row["name"],
        description=row["description"],
        language=row["language"],
        stars=row["stars"],
        stars_since=row["stars_since"],
        forks=row["forks"],
        since=row["since"],
        collected_at=date.fromisoformat(row["collected_at"]),
    )


def _week_label_to_date_range(week_label: str) -> tuple[date, date]:
    """ISO 週ラベルを月曜〜日曜の日付範囲に変換する.

    Args:
        week_label: ISO 週ラベル（例: ``"2025-W03"``）。

    Returns:
        (月曜日, 日曜日) のタプル。
    """
    monday = datetime.strptime(week_label + "-1", "%G-W%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday, sunday
