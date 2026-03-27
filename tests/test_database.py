"""database.py のテスト"""

from __future__ import annotations

from datetime import date, datetime

from gh_trend_reporter.database import Database
from gh_trend_reporter.models import (
    CategoryGroup,
    RepoDetail,
    TrendingRepo,
    WeeklyAnalysis,
)


def _make_trending_repo(
    owner: str = "google",
    name: str = "gemma",
    since: str = "daily",
    collected_at: date = date(2025, 1, 15),
    **kwargs: object,
) -> TrendingRepo:
    defaults: dict[str, object] = {
        "description": "Open weights LLM",
        "language": "Python",
        "stars": 50000,
        "stars_since": 1234,
        "forks": 3000,
    }
    defaults.update(kwargs)
    return TrendingRepo(
        owner=owner,
        name=name,
        since=since,
        collected_at=collected_at,
        **defaults,
    )


class TestDatabase:
    """Database のテスト"""

    def test_create_tables(self, db: Database) -> None:
        """テーブルが正しく作成される"""
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "trending_repos" in table_names
        assert "repo_details" in table_names
        assert "weekly_analyses" in table_names

    def test_insert_trending_repo(self, db: Database) -> None:
        """TrendingRepo を挿入できる"""
        repo = _make_trending_repo()
        db.insert_trending_repo(repo)

        rows = db.conn.execute("SELECT * FROM trending_repos").fetchall()
        assert len(rows) == 1
        assert rows[0]["owner"] == "google"
        assert rows[0]["name"] == "gemma"

    def test_upsert_trending_repo(self, db: Database) -> None:
        """同じ (owner, name, since, date) の重複はスキップ"""
        repo = _make_trending_repo()
        db.insert_trending_repo(repo)
        db.insert_trending_repo(repo)

        rows = db.conn.execute("SELECT * FROM trending_repos").fetchall()
        assert len(rows) == 1

    def test_get_repos_by_date(self, db: Database) -> None:
        """日付指定でリポジトリを取得"""
        db.insert_trending_repo(_make_trending_repo(collected_at=date(2025, 1, 15)))
        db.insert_trending_repo(
            _make_trending_repo(owner="vercel", name="next.js", collected_at=date(2025, 1, 15))
        )
        db.insert_trending_repo(
            _make_trending_repo(owner="other", name="repo", collected_at=date(2025, 1, 16))
        )

        repos = db.get_repos_by_date(date(2025, 1, 15))
        assert len(repos) == 2

    def test_get_repos_by_week(self, db: Database) -> None:
        """週指定（week_label）でリポジトリを取得"""
        # 2025-W03: 2025-01-13 (Mon) ~ 2025-01-19 (Sun)
        db.insert_trending_repo(_make_trending_repo(collected_at=date(2025, 1, 13)))
        db.insert_trending_repo(
            _make_trending_repo(owner="vercel", name="next.js", collected_at=date(2025, 1, 19))
        )
        # 前週のデータ
        db.insert_trending_repo(
            _make_trending_repo(owner="other", name="repo", collected_at=date(2025, 1, 12))
        )

        repos = db.get_repos_by_week("2025-W03")
        assert len(repos) == 2

    def test_insert_repo_detail(self, db: Database) -> None:
        """RepoDetail を挿入できる"""
        detail = RepoDetail(
            owner="google",
            name="gemma",
            full_name="google/gemma",
            topics=["llm", "ai"],
            readme_excerpt="# Gemma",
            license="Apache-2.0",
            open_issues=42,
            open_prs=10,
            last_pushed=datetime(2025, 1, 18, 12, 0),
            created_at=datetime(2024, 6, 1),
            homepage="https://ai.google.dev/gemma",
        )
        db.insert_repo_detail(detail)

        row = db.conn.execute(
            "SELECT * FROM repo_details WHERE full_name = 'google/gemma'"
        ).fetchone()
        assert row is not None
        assert row["full_name"] == "google/gemma"

    def test_get_repo_detail_cache(self, db: Database) -> None:
        """キャッシュ有効期限内のデータを返す"""
        detail = RepoDetail(
            owner="google",
            name="gemma",
            full_name="google/gemma",
            topics=["llm"],
            readme_excerpt="# Gemma",
            license="Apache-2.0",
            open_issues=42,
            open_prs=10,
            last_pushed=datetime(2025, 1, 18, 12, 0),
            created_at=datetime(2024, 6, 1),
            homepage=None,
        )
        db.insert_repo_detail(detail)

        cached = db.get_repo_detail("google/gemma", cache_ttl=86400)
        assert cached is not None
        assert cached.topics == ["llm"]

    def test_get_previous_week_repos(self, db: Database) -> None:
        """前週のリポジトリ一覧を取得"""
        # 今週: 2025-W03 (01-13 ~ 01-19)
        db.insert_trending_repo(_make_trending_repo(collected_at=date(2025, 1, 15)))
        # 前週: 2025-W02 (01-06 ~ 01-12)
        db.insert_trending_repo(
            _make_trending_repo(owner="old", name="repo", collected_at=date(2025, 1, 8))
        )

        prev_repos = db.get_previous_week_repos("2025-W03", weeks_ago=1)
        assert len(prev_repos) == 1
        assert prev_repos[0].owner == "old"

    def test_save_weekly_analysis(self, db: Database) -> None:
        """WeeklyAnalysis を保存・読み込みできる"""
        analysis = WeeklyAnalysis(
            week_label="2025-W03",
            period_start=date(2025, 1, 13),
            period_end=date(2025, 1, 19),
            total_repos_collected=50,
            top_languages=[{"language": "Python", "count": 12, "percentage": 24.0}],
            categories=[
                CategoryGroup(
                    category="AI/ML",
                    repos=["google/gemma"],
                    summary_ja="LLM 関連が活発",
                )
            ],
            highlights=["AI エージェント急増"],
            new_entries=["new/repo"],
            rising_repos=[{"name": "google/gemma", "stars_since": 1234}],
            week_over_week="先週比で AI 増加",
        )
        db.save_weekly_analysis(analysis)

        loaded = db.get_weekly_analysis("2025-W03")
        assert loaded is not None
        assert loaded.week_label == "2025-W03"
        assert loaded.total_repos_collected == 50
        assert len(loaded.categories) == 1

    def test_get_new_entries(self, db: Database) -> None:
        """今週登場して前週にはなかったリポジトリを取得"""
        # 前週: 2025-W02 (01-06 ~ 01-12)
        db.insert_trending_repo(
            _make_trending_repo(owner="old", name="repo", collected_at=date(2025, 1, 8))
        )
        # 今週: 2025-W03 (01-13 ~ 01-19) - old/repo + new/repo
        db.insert_trending_repo(
            _make_trending_repo(owner="old", name="repo", collected_at=date(2025, 1, 15))
        )
        db.insert_trending_repo(
            _make_trending_repo(owner="new", name="repo", collected_at=date(2025, 1, 15))
        )

        new_entries = db.get_new_entries("2025-W03")
        assert "new/repo" in new_entries
        assert "old/repo" not in new_entries

    def test_empty_database(self, db: Database) -> None:
        """空 DB でクエリしてもエラーにならない"""
        repos = db.get_repos_by_date(date(2025, 1, 15))
        assert repos == []

        repos = db.get_repos_by_week("2025-W03")
        assert repos == []

        analysis = db.get_weekly_analysis("2025-W03")
        assert analysis is None

        new_entries = db.get_new_entries("2025-W03")
        assert new_entries == []
