"""Integration tests — collect → DB → analyze → report の全体フロー"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from gh_trend_reporter.config import Config
from gh_trend_reporter.database import Database
from gh_trend_reporter.models import (
    CategoryGroup,
    CategoryRepo,
    TrendingRepo,
    WeeklyAnalysis,
)
from gh_trend_reporter.reporter import ReportGenerator
from gh_trend_reporter.scraper import TrendingScraper
from tests.conftest import (
    MOCK_AGENT_FUNCTION_CALLS,
    MOCK_ANALYSIS_OUTPUT,
    make_mock_genai_response,
)


def _make_trending_repo(**kwargs: Any) -> TrendingRepo:
    defaults: dict[str, Any] = {
        "owner": "test-owner",
        "name": "test-repo",
        "description": "A test repository",
        "language": "Python",
        "stars": 1000,
        "stars_since": 100,
        "forks": 50,
        "since": "daily",
        "collected_at": date(2025, 1, 15),
    }
    defaults.update(kwargs)
    return TrendingRepo(**defaults)


class TestFullPipeline:
    def test_collect_to_db(self, db: Database, daily_html: str) -> None:
        """scrape → DB 保存 → 読み出しの全体フロー"""
        collected_at = date(2025, 1, 15)
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=collected_at
        )

        count = db.insert_trending_repos(repos)
        assert count > 0

        stored = db.get_repos_by_date(collected_at, since="daily")
        assert len(stored) == len(repos)
        assert stored[0].owner != ""
        assert stored[0].name != ""

    def test_collect_analyze_report(self, db: Database, tmp_path: Path) -> None:
        """collect → analyze → report の全体フロー（モック使用）"""
        # Step 1: DB にデータ投入
        collected_at = date(2025, 1, 15)
        repos = [
            _make_trending_repo(
                owner="google",
                name="gemma",
                language="Python",
                stars=50000,
                stars_since=1234,
                collected_at=collected_at,
            ),
            _make_trending_repo(
                owner="vercel",
                name="next.js",
                language="TypeScript",
                stars=120000,
                stars_since=567,
                collected_at=collected_at,
            ),
        ]
        db.insert_trending_repos(repos)

        # Step 2: 分析結果を直接作成（エージェントをスキップ）
        analysis = WeeklyAnalysis(
            week_label="2025-W03",
            period_start=date(2025, 1, 13),
            period_end=date(2025, 1, 19),
            total_repos_collected=2,
            top_languages=[
                {"language": "Python", "count": 1, "percentage": 50.0},
                {"language": "TypeScript", "count": 1, "percentage": 50.0},
            ],
            categories=[
                CategoryGroup(
                    category="AI/機械学習",
                    repos=[CategoryRepo(name="google/gemma", description="軽量オープンLLM")],
                    summary_ja="LLM 関連",
                ),
            ],
            highlights=["テストハイライト"],
            new_entries=[],
            rising_repos=[],
            week_over_week="",
        )
        db.save_weekly_analysis(analysis)

        # Step 3: レポート生成
        generator = ReportGenerator(reports_dir=tmp_path)
        report = ReportGenerator.build_report(analysis)
        path = generator.save(report)

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "2025-W03" in content
        assert "google/gemma" in content

    def test_two_weeks_comparison(self, db: Database) -> None:
        """2週分のデータで週間比較が正しく動作"""
        # Week 1 data
        week1_date = date(2025, 1, 8)
        week1_repos = [
            _make_trending_repo(
                owner="old-org",
                name="old-repo",
                collected_at=week1_date,
            ),
            _make_trending_repo(
                owner="common-org",
                name="common-repo",
                collected_at=week1_date,
            ),
        ]
        db.insert_trending_repos(week1_repos)

        # Week 2 data
        week2_date = date(2025, 1, 15)
        week2_repos = [
            _make_trending_repo(
                owner="common-org",
                name="common-repo",
                collected_at=week2_date,
            ),
            _make_trending_repo(
                owner="new-org",
                name="new-repo",
                collected_at=week2_date,
            ),
        ]
        db.insert_trending_repos(week2_repos)

        # new_entries should be repos in week 2 but not in week 1
        new_entries = db.get_new_entries("2025-W03")
        assert "new-org/new-repo" in new_entries
        assert "common-org/common-repo" not in new_entries

    async def test_agent_full_loop(self, db: Database) -> None:
        """エージェントが Plan → Act → Observe → Reflect を完遂"""
        from gh_trend_reporter.agent import AnalysisAgent

        # DB にテストデータを投入
        collected_at = date(2025, 1, 15)
        repos = [
            _make_trending_repo(
                owner="google",
                name="gemma",
                language="Python",
                stars=50000,
                stars_since=1234,
                collected_at=collected_at,
            ),
        ]
        db.insert_trending_repos(repos)

        config = Config(agent_max_turns=10, gemini_api_key="test-key")

        # Function call シーケンスに対応するモックレスポンスを構築
        mock_responses = []
        for fc in MOCK_AGENT_FUNCTION_CALLS:
            mock_responses.append(make_mock_genai_response(function_calls=[fc]))
        # 最終ターン: テキストレスポンス（分析結果 JSON）
        mock_responses.append(make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)))

        mock_client = MagicMock()
        mock_generate = AsyncMock(side_effect=mock_responses)
        mock_client.aio.models.generate_content = mock_generate

        agent = AnalysisAgent(
            config=config,
            db=db,
            client=mock_client,
        )
        result = await agent.run_agent("2025-W03")

        assert result.week_label == "2025-W03"
        assert len(result.categories) > 0
        assert len(result.highlights) > 0
        assert len(agent.function_call_log) == len(MOCK_AGENT_FUNCTION_CALLS)
