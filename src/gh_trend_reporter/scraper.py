"""GitHub Trending ページのスクレイピングモジュール.

``https://github.com/trending`` の HTML を取得・解析し、
各リポジトリ行から名前・スター数・言語などを抽出する。
429 応答やタイムアウトに対する指数バックオフリトライを内蔵。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup, Tag

from gh_trend_reporter.models import TrendingRepo

logger = logging.getLogger(__name__)

TRENDING_URL = "https://github.com/trending"


class ScraperError(Exception):
    """スクレイピング処理で発生するエラーの基底クラス."""


class TrendingScraper:
    """GitHub Trending ページの非同期スクレイパー.

    Args:
        client: 外部から注入する httpx クライアント。None の場合は内部で生成。
        interval: リクエスト間のインターバル（秒）。
        max_retries: リトライ最大回数。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        interval: float = 2.0,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._interval = interval
        self._max_retries = max_retries

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": "gh-trend-reporter/0.1"},
                timeout=30.0,
            )
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        """内部で生成した HTTP クライアントを閉じる。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def build_url(since: str = "daily", language: str | None = None) -> str:
        """Trending ページの URL をクエリパラメータ付きで構築する.

        Args:
            since: 期間フィルタ（``"daily"`` または ``"weekly"``）。
            language: プログラミング言語フィルタ。None で全言語。

        Returns:
            完全な URL 文字列。
        """
        url = TRENDING_URL
        params: list[str] = []
        if language:
            params.append(f"language={language}")
        params.append(f"since={since}")
        if params:
            url += "?" + "&".join(params)
        return url

    async def fetch_html(self, url: str) -> str:
        """URL から HTML を取得する（指数バックオフリトライ付き）.

        Args:
            url: 取得対象の URL。

        Returns:
            レスポンスの HTML 文字列。

        Raises:
            ScraperError: 全リトライ失敗時、または 429/タイムアウト以外の HTTP エラー時。
        """
        client = await self._get_client()
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await client.get(url)
                if response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Rate limited (429), retrying in %ds...", wait)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response.text
            except httpx.TimeoutException as e:
                last_error = e
                wait = 2 ** (attempt + 1)
                logger.warning("Timeout, retrying in %ds...", wait)
                await asyncio.sleep(wait)
            except httpx.HTTPStatusError as e:
                raise ScraperError(f"HTTP error: {e.response.status_code}") from e
        raise ScraperError(f"Failed after {self._max_retries} retries: {last_error}")

    @staticmethod
    def parse_trending_page(
        html: str, since: str, collected_at: date | None = None
    ) -> list[TrendingRepo]:
        """Trending ページの HTML をパースしてリポジトリ一覧を返す.

        ``article.Box-row`` 要素を走査し、各行から情報を抽出する。
        パースに失敗した行はスキップして警告ログを出力する。

        Args:
            html: GitHub Trending ページの HTML 文字列。
            since: 期間ラベル（``"daily"`` または ``"weekly"``）。
            collected_at: 収集日。None の場合は今日の日付を使用。

        Returns:
            パース成功した TrendingRepo のリスト。空ページの場合は空リスト。
        """
        if collected_at is None:
            collected_at = date.today()

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("article.Box-row")

        if not rows:
            logger.warning("No trending repos found (empty page or structure change)")
            return []

        repos: list[TrendingRepo] = []
        for row in rows:
            try:
                repo = _parse_row(row, since, collected_at)
                repos.append(repo)
            except (ValueError, AttributeError) as e:
                logger.warning("Failed to parse row: %s", e)
                continue

        return repos

    async def scrape(
        self,
        since: str = "daily",
        language: str | None = None,
        collected_at: date | None = None,
    ) -> list[TrendingRepo]:
        """Trending ページの取得からパースまでを一括実行する.

        Args:
            since: 期間フィルタ。
            language: 言語フィルタ。
            collected_at: 収集日（テスト用に外部指定可能）。

        Returns:
            TrendingRepo のリスト。
        """
        url = self.build_url(since=since, language=language)
        html = await self.fetch_html(url)
        return self.parse_trending_page(html, since=since, collected_at=collected_at)


def _parse_row(row: Tag, since: str, collected_at: date) -> TrendingRepo:
    """単一の ``article.Box-row`` 要素から TrendingRepo を抽出する.

    Args:
        row: BeautifulSoup の Tag オブジェクト。
        since: 期間ラベル。
        collected_at: 収集日。

    Returns:
        抽出された TrendingRepo。

    Raises:
        ValueError: リポジトリ名が見つからない、または不正な形式の場合。
    """
    # リポジトリ名
    h2 = row.select_one("h2 a")
    if h2 is None:
        raise ValueError("Repository link not found")
    full_name = h2.get("href", "").strip("/")  # type: ignore[union-attr]
    parts = full_name.split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid repo name: {full_name}")
    owner, name = parts[0].strip(), parts[1].strip()

    # 説明文
    desc_tag = row.select_one("p")
    description = desc_tag.get_text(strip=True) if desc_tag else None

    # プログラミング言語
    lang_tag = row.select_one("[itemprop='programmingLanguage']")
    language = lang_tag.get_text(strip=True) if lang_tag else None

    # スター数・フォーク数
    links = row.select("a.Link--muted")
    stars = 0
    forks = 0
    for link in links:
        href = link.get("href", "")
        text = link.get_text(strip=True).replace(",", "")
        if "/stargazers" in str(href):
            stars = int(text) if text.isdigit() else 0
        elif "/forks" in str(href):
            forks = int(text) if text.isdigit() else 0

    # 期間内スター増加数
    stars_since = 0
    since_span = row.select_one("span.d-inline-block.float-sm-right")
    if since_span:
        match = re.search(r"([\d,]+)\s+stars", since_span.get_text())
        if match:
            stars_since = int(match.group(1).replace(",", ""))

    return TrendingRepo(
        owner=owner,
        name=name,
        description=description,
        language=language,
        stars=stars,
        stars_since=stars_since,
        forks=forks,
        since=since,
        collected_at=collected_at,
    )
