"""github_api.py のテスト"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from gh_trend_reporter.database import Database
from gh_trend_reporter.github_api import GitHubAPI, RateLimitExceeded
from gh_trend_reporter.models import RepoDetail

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json=json_data,
        headers=headers or {},
    )


class TestGitHubAPI:
    """GitHubAPI のテスト"""

    # --- 正常系 ---

    async def test_get_repo_detail(self) -> None:
        """リポジトリ詳細を正しく取得"""
        repo_json = json.loads((FIXTURES_DIR / "repo_detail.json").read_text())
        readme_content = base64.b64encode(b"# Gemma\nOpen weights LLM model").decode()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [
            _make_response(json_data=repo_json),
            _make_response(json_data={"content": readme_content}),
        ]

        api = GitHubAPI(client=mock_client)
        detail = await api.get_repo_detail("google", "gemma")

        assert detail is not None
        assert detail.full_name == "google/gemma"
        assert detail.owner == "google"
        assert detail.name == "gemma"
        assert "llm" in detail.topics
        assert detail.license == "Apache-2.0"
        assert detail.readme_excerpt.startswith("# Gemma")

    async def test_get_readme_excerpt(self) -> None:
        """README 冒頭500文字を取得"""
        long_content = "A" * 1000
        encoded = base64.b64encode(long_content.encode()).decode()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_response(json_data={"content": encoded})

        api = GitHubAPI(client=mock_client)
        excerpt = await api.get_readme("google", "gemma", max_chars=500)
        assert len(excerpt) == 500

    async def test_get_rate_limit(self) -> None:
        """レート制限情報を取得"""
        rate_data = {"resources": {"core": {"limit": 5000, "remaining": 4999, "reset": 1700000000}}}
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_response(json_data=rate_data)

        api = GitHubAPI(client=mock_client)
        result = await api.get_rate_limit()
        assert "resources" in result

    async def test_no_token_fallback(self) -> None:
        """GITHUB_TOKEN 未設定でも動作する"""
        api = GitHubAPI(token=None)
        # client が作成される（エラーにならない）
        client = await api._get_client()
        assert "Authorization" not in client.headers
        await api.close()

    # --- キャッシュ ---

    async def test_cache_hit(self, db: Database) -> None:
        """24時間以内のキャッシュデータを返す"""
        detail = RepoDetail(
            owner="google",
            name="gemma",
            full_name="google/gemma",
            topics=["llm"],
            readme_excerpt="# Gemma",
            license="Apache-2.0",
            open_issues=10,
            open_prs=5,
            last_pushed=datetime(2025, 1, 18, 12, 0),
            created_at=datetime(2024, 6, 1),
            homepage="https://ai.google.dev/gemma",
        )
        db.insert_repo_detail(detail)

        cached = db.get_repo_detail("google/gemma", cache_ttl=86400)
        assert cached is not None
        assert cached.full_name == "google/gemma"

    async def test_cache_miss(self, db: Database) -> None:
        """キャッシュ期限切れ → None"""
        detail = RepoDetail(
            owner="google",
            name="gemma",
            full_name="google/gemma",
            topics=["llm"],
            readme_excerpt="# Gemma",
            license="Apache-2.0",
            open_issues=10,
            open_prs=5,
            last_pushed=datetime(2025, 1, 18, 12, 0),
            created_at=datetime(2024, 6, 1),
            homepage=None,
        )
        db.insert_repo_detail(detail)

        # TTL = 0 → 即期限切れ
        cached = db.get_repo_detail("google/gemma", cache_ttl=0)
        assert cached is None

    # --- 異常系 ---

    async def test_repo_not_found(self) -> None:
        """存在しないリポジトリ → None"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_response(status_code=404)

        api = GitHubAPI(client=mock_client)
        result = await api.get_repo("nonexistent", "repo")
        assert result is None

    async def test_rate_limit_exceeded(self) -> None:
        """レート制限超過 → RateLimitExceeded"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_response(
            status_code=403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1700000000",
            },
        )

        api = GitHubAPI(client=mock_client)
        with pytest.raises(RateLimitExceeded):
            await api.get_repo("google", "gemma")

    async def test_readme_not_found(self) -> None:
        """README がないリポジトリ → 空文字"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_response(status_code=404)

        api = GitHubAPI(client=mock_client)
        result = await api.get_readme("google", "gemma")
        assert result == ""
