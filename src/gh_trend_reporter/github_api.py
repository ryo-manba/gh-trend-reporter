"""GitHub REST API クライアント.

リポジトリ詳細・README・レート制限情報の取得を提供する。
``X-RateLimit-Remaining`` ヘッダーを監視し、枠が 0 になると
:class:`RateLimitExceeded` を送出する。
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

import httpx

from gh_trend_reporter.models import RepoDetail

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """GitHub API 関連エラーの基底クラス."""


class RateLimitExceeded(GitHubAPIError):
    """GitHub API レート制限超過エラー.

    Attributes:
        reset_at: レート制限がリセットされる日時。
    """

    def __init__(self, reset_at: datetime) -> None:
        self.reset_at = reset_at
        super().__init__(f"Rate limit exceeded. Resets at {reset_at}")


class GitHubAPI:
    """GitHub REST API の非同期クライアント.

    Args:
        token: GitHub Personal Access Token。None の場合は未認証（60 req/h）。
        client: 外部から注入する httpx クライアント。None で内部生成。
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: dict[str, str] = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "gh-trend-reporter/0.1",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=headers,
                timeout=30.0,
            )
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        """内部で生成した HTTP クライアントを閉じる。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _check_rate_limit(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            reset_ts = int(response.headers.get("X-RateLimit-Reset", "0"))
            reset_at = datetime.fromtimestamp(reset_ts)
            raise RateLimitExceeded(reset_at)

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any] | None:
        """リポジトリのメタデータを取得する.

        Args:
            owner: リポジトリオーナー。
            repo: リポジトリ名。

        Returns:
            API レスポンスの辞書。404 の場合は None。

        Raises:
            RateLimitExceeded: レート制限に到達した場合。
        """
        client = await self._get_client()
        response = await client.get(f"/repos/{owner}/{repo}")

        if response.status_code == 404:
            return None
        if response.status_code == 403:
            self._check_rate_limit(response)
        response.raise_for_status()

        return response.json()  # type: ignore[no-any-return]

    async def get_readme(self, owner: str, repo: str, max_chars: int = 500) -> str:
        """README を取得して冒頭を返す.

        Base64 エンコードされた README コンテンツをデコードし、
        先頭 ``max_chars`` 文字に切り詰めて返す。

        Args:
            owner: リポジトリオーナー。
            repo: リポジトリ名。
            max_chars: 返す最大文字数（デフォルト: 500）。

        Returns:
            README の冒頭テキスト。README が存在しない場合は空文字列。
        """
        client = await self._get_client()
        response = await client.get(f"/repos/{owner}/{repo}/readme")

        if response.status_code == 404:
            return ""
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        content_b64 = data.get("content", "")
        try:
            content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            return ""
        return content[:max_chars]

    async def get_rate_limit(self) -> dict[str, Any]:
        """現在の GitHub API レート制限状況を取得する.

        Returns:
            ``/rate_limit`` エンドポイントのレスポンス辞書。
        """
        client = await self._get_client()
        response = await client.get("/rate_limit")
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_repo_detail(self, owner: str, repo: str) -> RepoDetail | None:
        """リポジトリ情報と README を取得して RepoDetail に変換する.

        ``get_repo()`` と ``get_readme()`` を順次呼び出し、
        結果を :class:`RepoDetail` モデルに統合する。

        Args:
            owner: リポジトリオーナー。
            repo: リポジトリ名。

        Returns:
            変換された RepoDetail。リポジトリが存在しない場合は None。
        """
        repo_data = await self.get_repo(owner, repo)
        if repo_data is None:
            return None

        readme_excerpt = await self.get_readme(owner, repo)

        license_info = repo_data.get("license")
        license_name = license_info.get("spdx_id") if isinstance(license_info, dict) else None

        return RepoDetail(
            owner=owner,
            name=repo,
            full_name=repo_data.get("full_name", f"{owner}/{repo}"),
            topics=repo_data.get("topics", []),
            readme_excerpt=readme_excerpt,
            license=license_name,
            open_issues=repo_data.get("open_issues_count", 0),
            open_prs=0,
            last_pushed=datetime.fromisoformat(
                repo_data["pushed_at"].replace("Z", "+00:00")
            ),
            created_at=datetime.fromisoformat(
                repo_data["created_at"].replace("Z", "+00:00")
            ),
            homepage=repo_data.get("homepage"),
        )
