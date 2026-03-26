"""scraper.py のテスト"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from gh_trend_reporter.scraper import ScraperError, TrendingScraper


class TestTrendingScraper:
    """TrendingScraper のテスト"""

    # --- 正常系 ---

    async def test_scrape_daily_trending(self, daily_html: str) -> None:
        """daily Trending ページから正しくリポジトリを抽出"""
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=date(2025, 1, 15)
        )
        assert len(repos) > 0
        for repo in repos:
            assert repo.owner
            assert repo.name
            assert repo.since == "daily"
            assert repo.collected_at == date(2025, 1, 15)

    async def test_scrape_weekly_trending(self, weekly_html: str) -> None:
        """weekly Trending ページから正しくリポジトリを抽出"""
        repos = TrendingScraper.parse_trending_page(
            weekly_html, since="weekly", collected_at=date(2025, 1, 15)
        )
        assert len(repos) > 0
        for repo in repos:
            assert repo.since == "weekly"

    async def test_extract_repo_name(self, daily_html: str) -> None:
        """owner/name 形式でリポジトリ名を抽出"""
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=date(2025, 1, 15)
        )
        gemma = next((r for r in repos if r.name == "gemma"), None)
        assert gemma is not None
        assert gemma.owner == "google"

    async def test_extract_stars_since(self, daily_html: str) -> None:
        """期間内スター増加数を正しく抽出"""
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=date(2025, 1, 15)
        )
        gemma = next((r for r in repos if r.name == "gemma"), None)
        assert gemma is not None
        assert gemma.stars_since == 1234

    async def test_extract_language(self, daily_html: str) -> None:
        """プログラミング言語を正しく抽出"""
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=date(2025, 1, 15)
        )
        gemma = next((r for r in repos if r.name == "gemma"), None)
        assert gemma is not None
        assert gemma.language == "Python"

    async def test_extract_description(self, daily_html: str) -> None:
        """説明文を正しく抽出"""
        repos = TrendingScraper.parse_trending_page(
            daily_html, since="daily", collected_at=date(2025, 1, 15)
        )
        gemma = next((r for r in repos if r.name == "gemma"), None)
        assert gemma is not None
        assert gemma.description is not None
        assert "LLM" in gemma.description

    async def test_language_filter(self) -> None:
        """言語フィルタ付き URL が正しく構築される"""
        url = TrendingScraper.build_url(since="daily", language="python")
        assert "language=python" in url
        assert "since=daily" in url

    # --- 異常系 ---

    async def test_empty_trending_page(self, empty_html: str) -> None:
        """空の Trending ページ → 空リスト"""
        repos = TrendingScraper.parse_trending_page(
            empty_html, since="daily", collected_at=date(2025, 1, 15)
        )
        assert repos == []

    async def test_html_structure_change(self) -> None:
        """予期しない HTML 構造 → 空リスト"""
        html = "<html><body><div>No trending data</div></body></html>"
        repos = TrendingScraper.parse_trending_page(
            html, since="daily", collected_at=date(2025, 1, 15)
        )
        assert repos == []

    async def test_network_timeout(self) -> None:
        """タイムアウト → ScraperError"""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        scraper = TrendingScraper(client=mock_client, max_retries=2)
        with pytest.raises(ScraperError, match="Failed after 2 retries"):
            await scraper.fetch_html("https://github.com/trending")

    async def test_rate_limited(self) -> None:
        """429 → リトライ後に成功"""
        rate_limited = httpx.Response(429, request=httpx.Request("GET", "https://x"))
        ok_response = httpx.Response(
            200,
            request=httpx.Request("GET", "https://x"),
            text="<html></html>",
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [rate_limited, ok_response]

        scraper = TrendingScraper(client=mock_client, max_retries=3)
        with patch("gh_trend_reporter.scraper.asyncio.sleep", new_callable=AsyncMock):
            result = await scraper.fetch_html("https://github.com/trending")
        assert result == "<html></html>"
