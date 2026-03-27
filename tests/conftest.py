"""テスト共通 fixtures"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from gh_trend_reporter.config import Config
from gh_trend_reporter.database import Database
from gh_trend_reporter.models import TrendingRepo

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def daily_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "trending_daily.html").read_text()


@pytest.fixture
def weekly_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "trending_weekly.html").read_text()


@pytest.fixture
def empty_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "trending_empty.html").read_text()


@pytest.fixture
def db() -> Generator[Database, None, None]:
    database = Database(":memory:")
    database.init()
    yield database
    database.close()


@pytest.fixture
def agent_config() -> Config:
    """エージェントテスト用の設定"""
    return Config(
        agent_max_turns=10,
        gemini_api_key="test-api-key",
    )


def _make_trending_repo(**kwargs: Any) -> TrendingRepo:
    """テスト用の TrendingRepo を生成するヘルパー"""
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


@pytest.fixture
def sample_trending_repos() -> list[TrendingRepo]:
    """エージェントテスト用のサンプル trending repos"""
    today = date.today()
    return [
        _make_trending_repo(
            owner="google",
            name="gemma",
            description="Open weights LLM",
            language="Python",
            stars=50000,
            stars_since=1234,
            since="daily",
            collected_at=today,
        ),
        _make_trending_repo(
            owner="vercel",
            name="next.js",
            description="The React Framework",
            language="TypeScript",
            stars=120000,
            stars_since=567,
            since="daily",
            collected_at=today,
        ),
        _make_trending_repo(
            owner="rustlang",
            name="rust",
            description="The Rust programming language",
            language="Rust",
            stars=95000,
            stars_since=890,
            since="daily",
            collected_at=today,
        ),
    ]


MOCK_REPO_DETAIL: dict[str, Any] = {
    "full_name": "google/gemma",
    "description": "Open weights LLM",
    "topics": ["llm", "ai", "machine-learning"],
    "license": {"spdx_id": "Apache-2.0"},
    "open_issues_count": 42,
    "pushed_at": "2025-01-18T12:00:00Z",
    "created_at": "2024-06-01T00:00:00Z",
    "homepage": "https://ai.google.dev/gemma",
}

MOCK_README_CONTENT: str = (
    "IyBHZW1tYQoKT3BlbiB3ZWlnaHRzIExMTSBieSBHb29nbGUu"  # Base64: "# Gemma\n\nOpen weights LLM by Google."
)

MOCK_AGENT_FUNCTION_CALLS: list[dict[str, Any]] = [
    # Turn 1: get_trending_repos(since="daily")
    {"name": "get_trending_repos", "args": {"since": "daily", "limit": 25}},
    # Turn 2: get_trending_repos(since="weekly")
    {"name": "get_trending_repos", "args": {"since": "weekly", "limit": 25}},
    # Turn 3: get_repo_detail for top repo
    {"name": "get_repo_detail", "args": {"owner": "google", "repo": "gemma"}},
    # Turn 4: get_previous_week_trending
    {"name": "get_previous_week_trending", "args": {"weeks_ago": 1}},
    # Turn 5: classify_repos
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
    },
    # Turn 6: 最終分析 JSON 出力（Function Call なし — text response）
]

MOCK_ANALYSIS_OUTPUT: dict[str, Any] = {
    "top_languages": [
        {"language": "Python", "count": 12, "percentage": 24.0},
        {"language": "TypeScript", "count": 9, "percentage": 18.0},
    ],
    "categories": [
        {
            "category": "AI/機械学習",
            "repos": ["google/gemma", "meta/llama"],
            "summary_ja": "LLM 関連が活発",
        }
    ],
    "highlights": ["AI エージェントフレームワークが急増"],
    "new_entries": ["new-org/new-repo"],
    "rising_repos": [
        {"name": "google/gemma", "stars_since": 1234, "reason": "Gemma 2 リリース"}
    ],
    "week_over_week": "先週と比べて AI 関連が増加",
}


def make_mock_genai_response(
    *,
    text: str | None = None,
    function_calls: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Gemini API のモックレスポンスを生成する"""
    response = MagicMock()

    if function_calls:
        mock_fcs = []
        for fc in function_calls:
            mock_fc = MagicMock()
            mock_fc.name = fc["name"]
            mock_fc.args = fc.get("args", {})
            mock_fcs.append(mock_fc)
        response.function_calls = mock_fcs
        response.text = None
    else:
        response.function_calls = None
        response.text = text or ""

    return response
