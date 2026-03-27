"""tests for cli.py"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from gh_trend_reporter.cli import main
from gh_trend_reporter.models import (
    CategoryGroup,
    TrendingRepo,
    WeeklyAnalysis,
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
        "collected_at": date.today(),
    }
    defaults.update(kwargs)
    return TrendingRepo(**defaults)


def _make_analysis(week_label: str = "2025-W03") -> WeeklyAnalysis:
    return WeeklyAnalysis(
        week_label=week_label,
        period_start=date(2025, 1, 13),
        period_end=date(2025, 1, 19),
        total_repos_collected=3,
        top_languages=[{"language": "Python", "count": 1, "percentage": 100.0}],
        categories=[
            CategoryGroup(
                category="AI/機械学習",
                repos=["google/gemma"],
                summary_ja="LLM 関連",
            )
        ],
        highlights=["テストハイライト"],
        new_entries=[],
        rising_repos=[],
        week_over_week="",
    )


class TestCLI:

    def test_collect_command(self) -> None:
        """collect コマンドが動作する"""
        runner = CliRunner()
        mock_repos = [_make_trending_repo()]

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
            patch("gh_trend_reporter.scraper.TrendingScraper") as mock_scraper_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:", collect_interval=0.0
            )
            mock_db = MagicMock()
            mock_db.insert_trending_repos.return_value = 1
            mock_db_cls.return_value = mock_db

            mock_scraper = AsyncMock()
            mock_scraper.scrape = AsyncMock(return_value=mock_repos)
            mock_scraper.close = AsyncMock()
            mock_scraper_cls.return_value = mock_scraper

            result = runner.invoke(main, ["collect"])

        assert result.exit_code == 0
        assert "Done!" in result.output

    def test_analyze_command(self) -> None:
        """analyze コマンドが動作する"""
        runner = CliRunner()
        analysis = _make_analysis()

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
            patch("gh_trend_reporter.agent.AnalysisAgent") as mock_agent_cls,
            patch("gh_trend_reporter.github_api.GitHubAPI") as mock_gh_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:",
                github_token=None,
                github_cache_ttl=86400,
                agent_max_turns=10,
                gemini_api_key="test",
            )
            mock_db = MagicMock()
            mock_db.get_repos_by_week.return_value = [_make_trending_repo()]
            mock_db_cls.return_value = mock_db

            mock_agent = AsyncMock()
            mock_agent.run_agent = AsyncMock(return_value=analysis)
            mock_agent_cls.return_value = mock_agent

            mock_gh = AsyncMock()
            mock_gh.close = AsyncMock()
            mock_gh_cls.return_value = mock_gh

            result = runner.invoke(main, ["analyze", "--week", "2025-W03"])

        assert result.exit_code == 0
        assert "Analysis complete" in result.output

    def test_report_command(self, tmp_path: Any) -> None:
        """report コマンドが動作する"""
        runner = CliRunner()
        analysis = _make_analysis()

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:", reports_dir=tmp_path
            )
            mock_db = MagicMock()
            mock_db.get_weekly_analysis.return_value = analysis
            mock_db_cls.return_value = mock_db

            result = runner.invoke(main, ["report", "--week", "2025-W03"])

        assert result.exit_code == 0
        assert "Report saved" in result.output

    def test_run_command(self, tmp_path: Any) -> None:
        """run コマンド（一括実行）が動作する"""
        runner = CliRunner()
        analysis = _make_analysis()
        mock_repos = [_make_trending_repo()]

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
            patch("gh_trend_reporter.scraper.TrendingScraper") as mock_scraper_cls,
            patch("gh_trend_reporter.agent.AnalysisAgent") as mock_agent_cls,
            patch("gh_trend_reporter.github_api.GitHubAPI") as mock_gh_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:",
                collect_interval=0.0,
                reports_dir=tmp_path,
                github_token=None,
                github_cache_ttl=86400,
                agent_max_turns=10,
                gemini_api_key="test",
            )
            mock_db = MagicMock()
            mock_db.insert_trending_repos.return_value = 1
            mock_db.get_repos_by_week.return_value = mock_repos
            mock_db.get_weekly_analysis.return_value = analysis
            mock_db_cls.return_value = mock_db

            mock_scraper = AsyncMock()
            mock_scraper.scrape = AsyncMock(return_value=mock_repos)
            mock_scraper.close = AsyncMock()
            mock_scraper_cls.return_value = mock_scraper

            mock_agent = AsyncMock()
            mock_agent.run_agent = AsyncMock(return_value=analysis)
            mock_agent_cls.return_value = mock_agent

            mock_gh = AsyncMock()
            mock_gh.close = AsyncMock()
            mock_gh_cls.return_value = mock_gh

            result = runner.invoke(main, ["run"])

        assert result.exit_code == 0

    def test_status_command(self) -> None:
        """status コマンドで DB 統計を表示"""
        runner = CliRunner()

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(db_path=":memory:")
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = (5,)
            mock_db = MagicMock()
            mock_db.conn = mock_conn
            mock_db_cls.return_value = mock_db

            result = runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "gh-trend-reporter status" in result.output

    def test_collect_with_language_filter(self) -> None:
        """--language オプションが正しく渡される"""
        runner = CliRunner()
        mock_repos = [_make_trending_repo(language="Python")]

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
            patch("gh_trend_reporter.scraper.TrendingScraper") as mock_scraper_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:", collect_interval=0.0
            )
            mock_db = MagicMock()
            mock_db.insert_trending_repos.return_value = 1
            mock_db_cls.return_value = mock_db

            mock_scraper = AsyncMock()
            mock_scraper.scrape = AsyncMock(return_value=mock_repos)
            mock_scraper.close = AsyncMock()
            mock_scraper_cls.return_value = mock_scraper

            result = runner.invoke(main, ["collect", "--language", "python"])

        assert result.exit_code == 0
        mock_scraper.scrape.assert_any_call(since="daily", language="python")

    def test_analyze_specific_week(self) -> None:
        """--week オプションで特定週を指定"""
        runner = CliRunner()
        analysis = _make_analysis(week_label="2025-W05")

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
            patch("gh_trend_reporter.agent.AnalysisAgent") as mock_agent_cls,
            patch("gh_trend_reporter.github_api.GitHubAPI") as mock_gh_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(
                db_path=":memory:",
                github_token=None,
                github_cache_ttl=86400,
                agent_max_turns=10,
                gemini_api_key="test",
            )
            mock_db = MagicMock()
            mock_db.get_repos_by_week.return_value = [_make_trending_repo()]
            mock_db_cls.return_value = mock_db

            mock_agent = AsyncMock()
            mock_agent.run_agent = AsyncMock(return_value=analysis)
            mock_agent_cls.return_value = mock_agent

            mock_gh = AsyncMock()
            mock_gh.close = AsyncMock()
            mock_gh_cls.return_value = mock_gh

            result = runner.invoke(main, ["analyze", "--week", "2025-W05"])

        assert result.exit_code == 0
        mock_agent.run_agent.assert_called_once_with("2025-W05")

    def test_no_data_error(self) -> None:
        """データなしで analyze → エラーメッセージ"""
        runner = CliRunner()

        with (
            patch("gh_trend_reporter.cli.Config") as mock_config_cls,
            patch("gh_trend_reporter.cli.Database") as mock_db_cls,
        ):
            mock_config_cls.load.return_value = MagicMock(db_path=":memory:")
            mock_db = MagicMock()
            mock_db.get_repos_by_week.return_value = []
            mock_db_cls.return_value = mock_db

            result = runner.invoke(main, ["analyze", "--week", "2025-W99"])

        assert result.exit_code != 0
        assert "データがありません" in result.output
