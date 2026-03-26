"""SQLite データ管理"""

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
    """SQLite データベース管理"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._conn

    def init(self) -> None:
        """DB 接続を開きテーブルを作成する"""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- trending_repos ---

    def insert_trending_repo(self, repo: TrendingRepo) -> None:
        """TrendingRepo を挿入する（重複はスキップ）"""
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
        """複数の TrendingRepo を一括挿入する"""
        count = 0
        for repo in repos:
            cursor = self.conn.execute(
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
            count += cursor.rowcount
        self.conn.commit()
        return count

    def get_repos_by_date(
        self, target_date: date, since: str | None = None
    ) -> list[TrendingRepo]:
        """日付指定でリポジトリを取得する"""
        query = "SELECT * FROM trending_repos WHERE collected_at = ?"
        params: list[str] = [target_date.isoformat()]
        if since:
            query += " AND since = ?"
            params.append(since)
        rows = self.conn.execute(query, params).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_repos_by_week(self, week_label: str) -> list[TrendingRepo]:
        """週指定（例: 2025-W03）でリポジトリを取得する"""
        start, end = _week_label_to_date_range(week_label)
        rows = self.conn.execute(
            "SELECT * FROM trending_repos WHERE collected_at BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_previous_week_repos(
        self, current_week: str, weeks_ago: int = 1
    ) -> list[TrendingRepo]:
        """前週のリポジトリ一覧を取得する"""
        start, _ = _week_label_to_date_range(current_week)
        prev_start = start - timedelta(weeks=weeks_ago)
        prev_end = prev_start + timedelta(days=6)
        rows = self.conn.execute(
            "SELECT * FROM trending_repos WHERE collected_at BETWEEN ? AND ?",
            (prev_start.isoformat(), prev_end.isoformat()),
        ).fetchall()
        return [_row_to_trending_repo(row) for row in rows]

    def get_new_entries(self, current_week: str) -> list[str]:
        """今週登場して前週にはなかったリポジトリの full_name リストを取得する"""
        current_repos = self.get_repos_by_week(current_week)
        prev_repos = self.get_previous_week_repos(current_week)

        current_names = {f"{r.owner}/{r.name}" for r in current_repos}
        prev_names = {f"{r.owner}/{r.name}" for r in prev_repos}

        return sorted(current_names - prev_names)

    # --- repo_details ---

    def insert_repo_detail(self, detail: RepoDetail) -> None:
        """RepoDetail を挿入/更新する"""
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

    def get_repo_detail(
        self, full_name: str, cache_ttl: int = 86400
    ) -> RepoDetail | None:
        """キャッシュ有効期限内の RepoDetail を取得する"""
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
        """WeeklyAnalysis を保存する"""
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
        """WeeklyAnalysis を読み込む"""
        row = self.conn.execute(
            "SELECT analysis_json FROM weekly_analyses WHERE week_label = ?",
            (week_label,),
        ).fetchone()

        if row is None:
            return None
        return WeeklyAnalysis.model_validate_json(row["analysis_json"])


def _row_to_trending_repo(row: sqlite3.Row) -> TrendingRepo:
    """sqlite3.Row を TrendingRepo に変換する"""
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
    """週ラベル（例: 2025-W03）を月曜〜日曜の日付範囲に変換する"""
    monday = datetime.strptime(week_label + "-1", "%G-W%V-%u").date()
    sunday = monday + timedelta(days=6)
    return monday, sunday
