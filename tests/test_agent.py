"""エージェントのテスト"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from gh_trend_reporter.agent import (
    AgentError,
    AgentMaxTurnsError,
    AnalysisAgent,
    _classify_single_repo,
    _extract_json,
)
from gh_trend_reporter.config import Config
from gh_trend_reporter.database import Database
from gh_trend_reporter.models import TrendingRepo, WeeklyAnalysis
from tests.conftest import (
    MOCK_AGENT_FUNCTION_CALLS,
    MOCK_ANALYSIS_OUTPUT,
    make_mock_genai_response,
)


def _insert_sample_repos(db: Database, repos: list[TrendingRepo]) -> None:
    """サンプルデータを DB に投入する"""
    for repo in repos:
        db.insert_trending_repo(repo)


def _make_agent(
    config: Config,
    db: Database,
    mock_responses: list[MagicMock],
) -> AnalysisAgent:
    """モック済みのエージェントを生成する"""
    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_models = MagicMock()

    mock_generate = AsyncMock(side_effect=mock_responses)
    mock_models.generate_content = mock_generate
    mock_aio.models = mock_models
    mock_client.aio = mock_aio

    return AnalysisAgent(
        config=config,
        db=db,
        client=mock_client,
        rate_limiter=MagicMock(acquire=AsyncMock()),
    )


class TestAnalysisAgent:
    """エージェントの正常系テスト"""

    async def test_agent_calls_get_trending_first(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントの最初の呼び出しが get_trending_repos である"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[
                    {"name": "get_trending_repos", "args": {"since": "daily", "limit": 25}}
                ]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        await agent.run_agent(week_label)

        assert len(agent.function_call_log) >= 1
        assert agent.function_call_log[0]["name"] == "get_trending_repos"

    async def test_agent_fetches_repo_details(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントが注目リポジトリの詳細を取得する"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[
                    {"name": "get_repo_detail", "args": {"owner": "google", "repo": "gemma"}}
                ]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        await agent.run_agent(week_label)

        detail_calls = [fc for fc in agent.function_call_log if fc["name"] == "get_repo_detail"]
        assert len(detail_calls) >= 1

    async def test_agent_compares_with_previous_week(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントが前週データを取得して比較する"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[{"name": "get_previous_week_trending", "args": {"weeks_ago": 1}}]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        await agent.run_agent(week_label)

        prev_week_calls = [
            fc for fc in agent.function_call_log if fc["name"] == "get_previous_week_trending"
        ]
        assert len(prev_week_calls) >= 1

    async def test_agent_classifies_repos(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントがカテゴリ分類を実行する"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[
                    {
                        "name": "classify_repos",
                        "args": {
                            "repos": [
                                {
                                    "name": "google/gemma",
                                    "description": "Open weights LLM",
                                    "language": "Python",
                                    "topics": ["llm", "ai"],
                                }
                            ]
                        },
                    }
                ]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        await agent.run_agent(week_label)

        classify_calls = [fc for fc in agent.function_call_log if fc["name"] == "classify_repos"]
        assert len(classify_calls) >= 1

    async def test_agent_returns_valid_analysis(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントの最終出力が WeeklyAnalysis 構造を持つ"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[{"name": "get_trending_repos", "args": {"since": "daily"}}]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        result = await agent.run_agent(week_label)

        assert isinstance(result, WeeklyAnalysis)
        assert len(result.categories) > 0
        assert len(result.highlights) > 0
        assert len(result.new_entries) > 0
        assert result.week_label == week_label

    async def test_agent_loop_terminates(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントが最大ターン以内に完了する"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[{"name": "get_trending_repos", "args": {"since": "daily"}}]
            ),
            make_mock_genai_response(
                function_calls=[{"name": "get_trending_repos", "args": {"since": "weekly"}}]
            ),
            make_mock_genai_response(
                function_calls=[
                    {"name": "get_repo_detail", "args": {"owner": "google", "repo": "gemma"}}
                ]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        result = await agent.run_agent(week_label)

        assert isinstance(result, WeeklyAnalysis)
        assert len(agent.function_call_log) <= agent_config.agent_max_turns

    async def test_agent_function_execution(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """各ツール関数が正しいパラメータで実行される"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(
                function_calls=[
                    {"name": "get_trending_repos", "args": {"since": "daily", "limit": 25}}
                ]
            ),
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        await agent.run_agent(week_label)

        fc = agent.function_call_log[0]
        assert fc["name"] == "get_trending_repos"
        assert fc["args"]["since"] == "daily"

    async def test_agent_full_loop_sequence(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """エージェントが Plan→Act→Observe→Reflect の完全シーケンスを実行する"""
        _insert_sample_repos(db, sample_trending_repos)

        # MOCK_AGENT_FUNCTION_CALLS の各ターンを function_call レスポンスに変換し、
        # 最終ターンはテキスト（分析結果 JSON）で応答する
        responses = [
            make_mock_genai_response(function_calls=[fc]) for fc in MOCK_AGENT_FUNCTION_CALLS
        ] + [
            make_mock_genai_response(text=json.dumps(MOCK_ANALYSIS_OUTPUT)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        result = await agent.run_agent(week_label)

        # 全5ターンの function call が実行されたことを検証
        assert len(agent.function_call_log) == len(MOCK_AGENT_FUNCTION_CALLS)

        # 呼び出し順序を検証
        expected_names = [fc["name"] for fc in MOCK_AGENT_FUNCTION_CALLS]
        actual_names = [fc["name"] for fc in agent.function_call_log]
        assert actual_names == expected_names

        # 最終結果が有効な WeeklyAnalysis であることを検証
        assert isinstance(result, WeeklyAnalysis)
        assert result.week_label == week_label
        assert len(result.categories) > 0
        assert len(result.highlights) > 0


class TestAnalysisAgentErrors:
    """エージェントの異常系テスト"""

    async def test_agent_max_turns_exceeded(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """最大ターン超過 → AgentMaxTurnsError"""
        _insert_sample_repos(db, sample_trending_repos)
        agent_config.agent_max_turns = 3

        # 常に function call を返し続ける
        responses = [
            make_mock_genai_response(
                function_calls=[{"name": "get_trending_repos", "args": {"since": "daily"}}]
            )
            for _ in range(5)
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        with pytest.raises(AgentMaxTurnsError, match="最大ターン数"):
            await agent.run_agent(week_label)

    async def test_agent_invalid_function_name(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """存在しないツール名 → AgentError"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(function_calls=[{"name": "nonexistent_function", "args": {}}]),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        with pytest.raises(AgentError, match="Unknown function"):
            await agent.run_agent(week_label)

    async def test_agent_invalid_json_output(
        self,
        agent_config: Config,
        db: Database,
        sample_trending_repos: list[TrendingRepo],
    ) -> None:
        """不正な JSON 出力 → AgentError"""
        _insert_sample_repos(db, sample_trending_repos)

        responses = [
            make_mock_genai_response(text="This is not valid JSON at all"),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        with pytest.raises(AgentError, match="Invalid JSON"):
            await agent.run_agent(week_label)

    async def test_agent_partial_data(
        self,
        agent_config: Config,
        db: Database,
    ) -> None:
        """collect 不十分（データ少）→ 部分分析を実行"""
        # DB にデータ1件だけ投入
        from tests.conftest import _make_trending_repo

        db.insert_trending_repo(
            _make_trending_repo(
                owner="solo",
                name="repo",
                description="Only one repo",
                language="Go",
                stars=100,
                stars_since=10,
            )
        )

        partial_output = {
            "top_languages": [{"language": "Go", "count": 1, "percentage": 100.0}],
            "categories": [
                {
                    "category": "言語/ツール",
                    "repos": ["solo/repo"],
                    "summary_ja": "Go 関連リポジトリ",
                }
            ],
            "highlights": ["データが少ないため部分分析"],
            "new_entries": [],
            "rising_repos": [],
            "week_over_week": "前週データなし",
        }

        responses = [
            make_mock_genai_response(
                function_calls=[{"name": "get_trending_repos", "args": {"since": "daily"}}]
            ),
            make_mock_genai_response(text=json.dumps(partial_output)),
        ]

        agent = _make_agent(agent_config, db, responses)
        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

        result = await agent.run_agent(week_label)

        assert isinstance(result, WeeklyAnalysis)
        assert result.total_repos_collected == 1


class TestExtractJson:
    """JSON 抽出のテスト"""

    def test_extract_json_from_code_block(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        assert json.loads(_extract_json(text)) == {"key": "value"}

    def test_extract_json_from_plain_code_block(self) -> None:
        text = '```\n{"key": "value"}\n```'
        assert json.loads(_extract_json(text)) == {"key": "value"}

    def test_extract_json_from_raw_text(self) -> None:
        text = 'Some preamble {"key": "value"} some postamble'
        assert json.loads(_extract_json(text)) == {"key": "value"}

    def test_extract_json_pure(self) -> None:
        text = '{"key": "value"}'
        assert json.loads(_extract_json(text)) == {"key": "value"}


class TestClassifySingleRepo:
    """リポジトリ分類のテスト"""

    def test_classify_ai(self) -> None:
        assert _classify_single_repo("Python", ["llm", "ai"], "gpt-model") == "AI/機械学習"

    def test_classify_web(self) -> None:
        assert _classify_single_repo("TypeScript", ["react"], "my-app") == "Web開発"

    def test_classify_devops(self) -> None:
        assert _classify_single_repo("Go", ["kubernetes"], "k8s-tool") == "DevOps/インフラ"

    def test_classify_security(self) -> None:
        assert _classify_single_repo("Rust", ["crypto"], "auth-lib") == "セキュリティ"

    def test_classify_other(self) -> None:
        assert _classify_single_repo("", [], "random-project") == "その他"
