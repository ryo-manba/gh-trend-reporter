"""Gemini Function Calling を用いたトレンド分析エージェント.

Plan → Act → Observe → Reflect のエージェントループを実装する。
Gemini API の Function Calling 機能を使い、以下のツール関数を自律的に呼び出す:

- ``get_trending_repos``: DB から Trending データを取得
- ``get_repo_detail``: GitHub API でリポジトリ詳細を取得（キャッシュ優先）
- ``get_previous_week_trending``: 前週データを取得して差分比較
- ``classify_repos``: ヒューリスティックベースのカテゴリ分類

エージェントは最大ターン数（デフォルト 10）以内で分析を完了し、
構造化された :class:`WeeklyAnalysis` を返す。
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from gh_trend_reporter.config import Config
from gh_trend_reporter.database import Database
from gh_trend_reporter.github_api import GitHubAPI
from gh_trend_reporter.models import CategoryGroup, TrendingRepo, WeeklyAnalysis
from gh_trend_reporter.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class AgentMaxTurnsError(Exception):
    """エージェントが最大ターン数に到達して分析を完了できなかったエラー."""


class AgentError(Exception):
    """エージェント処理の一般的なエラー."""


def _load_system_prompt() -> str:
    """``prompts/agent_system.txt`` からシステムプロンプトを読み込む.

    Returns:
        プロンプト文字列。
    """
    prompt_path = PROMPTS_DIR / "agent_system.txt"
    return prompt_path.read_text(encoding="utf-8")


def _build_tool_declarations() -> list[types.FunctionDeclaration]:
    """Gemini Function Calling 用のツール宣言リストを構築する.

    Returns:
        4 つのツール（get_trending_repos, get_repo_detail,
        get_previous_week_trending, classify_repos）の FunctionDeclaration リスト。
    """
    return [
        types.FunctionDeclaration(
            name="get_trending_repos",
            description="指定期間のGitHub Trendingリポジトリ一覧をDBから取得する",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "since": types.Schema(
                        type="STRING",
                        description="期間フィルタ",
                        enum=["daily", "weekly"],
                    ),
                    "language": types.Schema(
                        type="STRING",
                        description="プログラミング言語フィルタ（空文字で全言語）",
                    ),
                    "limit": types.Schema(
                        type="INTEGER",
                        description="取得件数（デフォルト25）",
                    ),
                },
                required=["since"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_repo_detail",
            description="特定リポジトリの詳細情報（トピック、README冒頭、Issue数等）を取得する",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "owner": types.Schema(type="STRING", description="リポジトリオーナー"),
                    "repo": types.Schema(type="STRING", description="リポジトリ名"),
                },
                required=["owner", "repo"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_previous_week_trending",
            description="前週のTrendingデータをDBから取得し、今週との比較に使う",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "weeks_ago": types.Schema(
                        type="INTEGER",
                        description="何週間前のデータか（デフォルト1）",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="classify_repos",
            description="リポジトリ群を技術カテゴリに分類する",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "repos": types.Schema(
                        type="ARRAY",
                        description="分類対象のリポジトリ一覧",
                        items=types.Schema(
                            type="OBJECT",
                            properties={
                                "name": types.Schema(type="STRING", description="リポジトリ名"),
                                "description": types.Schema(type="STRING", description="説明"),
                                "language": types.Schema(
                                    type="STRING", description="プログラミング言語"
                                ),
                                "topics": types.Schema(
                                    type="ARRAY",
                                    description="トピックタグ",
                                    items=types.Schema(type="STRING"),
                                ),
                            },
                        ),
                    ),
                },
                required=["repos"],
            ),
        ),
    ]


def _repos_to_dicts(repos: list[TrendingRepo]) -> list[dict[str, Any]]:
    """TrendingRepo のリストを JSON シリアライズ可能な辞書リストに変換する.

    Args:
        repos: 変換元の TrendingRepo リスト。

    Returns:
        各リポジトリの主要フィールドを含む辞書のリスト。
    """
    return [
        {
            "owner": r.owner,
            "name": r.name,
            "full_name": f"{r.owner}/{r.name}",
            "description": r.description,
            "language": r.language,
            "stars": r.stars,
            "stars_since": r.stars_since,
            "forks": r.forks,
            "since": r.since,
        }
        for r in repos
    ]


class AnalysisAgent:
    """Gemini Function Calling を使ったトレンド分析エージェント.

    Plan → Act → Observe → Reflect のループで、Gemini が必要なツール関数を
    自律的に選択・呼び出し、収集したデータに基づいてトレンド分析を行う。

    Args:
        config: アプリケーション設定。
        db: データベースインスタンス。
        github_api: GitHub API クライアント。None の場合はリポジトリ詳細取得を省略。
        rate_limiter: Gemini API 用レート制限。None でデフォルト値を使用。
        client: Gemini API クライアント。None で自動生成。
    """

    def __init__(
        self,
        *,
        config: Config,
        db: Database,
        github_api: GitHubAPI | None = None,
        rate_limiter: RateLimiter | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._github_api = github_api
        self._rate_limiter = rate_limiter or RateLimiter()
        self._client = client or genai.Client(api_key=config.gemini_api_key or "")
        self._tool_declarations = _build_tool_declarations()
        self._function_call_log: list[dict[str, Any]] = []
        self._week_label: str = ""

    @property
    def function_call_log(self) -> list[dict[str, Any]]:
        """実行されたファンクションコールのログ"""
        return list(self._function_call_log)

    async def run_agent(self, week_label: str) -> WeeklyAnalysis:
        """Plan → Act → Observe → Reflect のエージェントループを実行する.

        Gemini にシステムプロンプトとツール定義を渡し、テキスト応答（分析完了）が
        返されるまで Function Calling の実行と結果フィードバックを繰り返す。

        Args:
            week_label: 分析対象の ISO 週ラベル（例: ``"2025-W03"``）。

        Returns:
            エージェントが生成した週次分析結果。

        Raises:
            AgentMaxTurnsError: 最大ターン数以内に分析が完了しなかった場合。
            AgentError: JSON パース失敗や不明な関数呼び出しが発生した場合。
        """
        system_prompt = _load_system_prompt()
        max_turns = self._config.agent_max_turns

        contents: list[types.Content] = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=f"今週（{week_label}）のGitHub Trendingデータを分析してください。"
                    )
                ],
            ),
        ]

        tool = types.Tool(function_declarations=self._tool_declarations)
        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        self._function_call_log.clear()
        self._week_label = week_label

        for turn in range(max_turns):
            logger.info("Agent turn %d/%d", turn + 1, max_turns)

            await self._rate_limiter.acquire()
            response = await self._client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=gen_config,
            )

            function_calls = response.function_calls
            if function_calls:
                # モデルの応答（function call を含む）を会話履歴に追加
                model_parts: list[types.Part] = []
                for fc in function_calls:
                    fc_name = fc.name or ""
                    model_parts.append(
                        types.Part.from_function_call(name=fc_name, args=dict(fc.args or {}))
                    )
                contents.append(types.Content(role="model", parts=model_parts))

                # 各 function call を実行し結果を追加
                response_parts: list[types.Part] = []
                for fc in function_calls:
                    fc_name = fc.name or ""
                    result = await self._execute_function(fc_name, dict(fc.args or {}))
                    self._function_call_log.append({"name": fc_name, "args": dict(fc.args or {})})
                    response_parts.append(
                        types.Part.from_function_response(name=fc_name, response={"result": result})
                    )
                contents.append(types.Content(role="user", parts=response_parts))
            else:
                # テキスト応答 → 分析完了
                text = response.text or ""
                return self._parse_analysis(text, week_label)

        raise AgentMaxTurnsError(f"エージェントが最大ターン数({max_turns})に達しました")

    async def _execute_function(self, name: str, args: dict[str, Any]) -> Any:
        """Gemini が要求したファンクションコールをディスパッチ・実行する.

        Args:
            name: 関数名。
            args: 関数に渡す引数の辞書。

        Returns:
            関数の実行結果。

        Raises:
            AgentError: 未知の関数名が指定された場合。
        """
        logger.info("Executing function: %s(%s)", name, args)

        if name == "get_trending_repos":
            return await self._fn_get_trending_repos(**args)
        elif name == "get_repo_detail":
            return await self._fn_get_repo_detail(**args)
        elif name == "get_previous_week_trending":
            return await self._fn_get_previous_week_trending(**args)
        elif name == "classify_repos":
            return await self._fn_classify_repos(**args)
        else:
            raise AgentError(f"Unknown function: {name}")

    async def _fn_get_trending_repos(
        self,
        since: str = "daily",
        language: str | None = None,
        limit: int = 25,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """DB から対象週の Trending リポジトリを取得する.

        Args:
            since: 期間フィルタ（``"daily"`` / ``"weekly"``）。
            language: 言語フィルタ（大文字小文字不問）。
            limit: 最大取得件数。
            **_kwargs: Gemini が送る余分なパラメータを吸収。

        Returns:
            リポジトリ情報の辞書リスト。
        """
        repos = self._db.get_repos_by_week(self._week_label)
        filtered = [r for r in repos if r.since == since]
        if language:
            filtered = [
                r for r in filtered if r.language and r.language.lower() == language.lower()
            ]
        return _repos_to_dicts(filtered[:limit])

    async def _fn_get_repo_detail(self, owner: str, repo: str, **_kwargs: Any) -> dict[str, Any]:
        """リポジトリ詳細を取得する（DB キャッシュ → GitHub API のフォールバック）.

        Args:
            owner: リポジトリオーナー。
            repo: リポジトリ名。
            **_kwargs: 余分なパラメータを吸収。

        Returns:
            リポジトリ詳細の辞書。取得失敗時はエラー情報を含む辞書。
        """
        full_name = f"{owner}/{repo}"
        cached = self._db.get_repo_detail(full_name, self._config.github_cache_ttl)
        if cached:
            return cached.model_dump(mode="json")

        if self._github_api:
            detail = await self._github_api.get_repo_detail(owner, repo)
            if detail:
                self._db.insert_repo_detail(detail)
                return detail.model_dump(mode="json")

        return {"error": f"Repository {full_name} not found"}

    async def _fn_get_previous_week_trending(
        self, weeks_ago: int = 1, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        """前週の Trending リポジトリを取得する.

        Args:
            weeks_ago: 何週間前のデータを取得するか。
            **_kwargs: 余分なパラメータを吸収。

        Returns:
            前週のリポジトリ情報の辞書リスト。
        """
        repos = self._db.get_previous_week_repos(self._week_label, weeks_ago)
        return _repos_to_dicts(repos)

    async def _fn_classify_repos(
        self, repos: list[dict[str, Any]], **_kwargs: Any
    ) -> list[dict[str, Any]]:
        """リポジトリ群をヒューリスティックで技術カテゴリに分類する.

        言語・トピック・リポジトリ名のキーワードマッチングで分類を行う。

        Args:
            repos: 分類対象のリポジトリ辞書リスト。
            **_kwargs: 余分なパラメータを吸収。

        Returns:
            カテゴリ別に集約された辞書リスト。
        """
        categories: dict[str, list[str]] = {}
        for repo in repos:
            lang = repo.get("language", "") or ""
            topics = repo.get("topics", []) or []
            name = repo.get("name", "")

            category = _classify_single_repo(lang, topics, name)
            if category not in categories:
                categories[category] = []
            categories[category].append(name)

        return [
            {"category": cat, "repos": cat_repos, "summary_ja": f"{cat}関連のリポジトリ"}
            for cat, cat_repos in categories.items()
        ]

    def _parse_analysis(self, text: str, week_label: str) -> WeeklyAnalysis:
        """エージェントのテキスト出力を WeeklyAnalysis にパースする.

        JSON ブロックを抽出し、週ラベルから期間を算出して
        :class:`WeeklyAnalysis` を構築する。

        Args:
            text: Gemini からのテキスト応答。
            week_label: 対象の ISO 週ラベル。

        Returns:
            パースされた WeeklyAnalysis。

        Raises:
            AgentError: JSON のパースに失敗した場合。
        """
        # JSON ブロックを抽出
        json_text = _extract_json(text)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise AgentError(f"Invalid JSON output from agent: {e}") from e

        # week_label から期間を計算
        from datetime import datetime

        monday = datetime.strptime(week_label + "-1", "%G-W%V-%u").date()
        sunday = monday + timedelta(days=6)

        categories = [CategoryGroup(**cat) for cat in data.get("categories", [])]

        return WeeklyAnalysis(
            week_label=week_label,
            period_start=monday,
            period_end=sunday,
            total_repos_collected=sum(len(cat.repos) for cat in categories),
            top_languages=data.get("top_languages", []),
            categories=categories,
            highlights=data.get("highlights", []),
            new_entries=data.get("new_entries", []),
            rising_repos=data.get("rising_repos", []),
            week_over_week=data.get("week_over_week", ""),
        )


def _extract_json(text: str) -> str:
    """テキストから JSON ブロックを抽出する.

    以下の順で抽出を試みる:
    1. ````json ... ```` コードブロック
    2. ```` ... ```` コードブロック
    3. 最初の ``{`` から最後の ``}`` までの範囲

    Args:
        text: JSON を含む可能性のあるテキスト。

    Returns:
        抽出された JSON 文字列。
    """
    # ```json ... ``` ブロックを検索
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        return text[start:end].strip()
    # そのまま JSON として扱う
    # 最初の { から最後の } まで
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        return text[brace_start : brace_end + 1]
    return text.strip()


def _classify_single_repo(language: str, topics: list[str], name: str) -> str:
    """単一リポジトリをキーワードマッチでカテゴリに分類する.

    言語・トピック・リポジトリ名を結合したテキストに対してキーワード検索を行い、
    最初にマッチしたカテゴリを返す。

    Args:
        language: プログラミング言語。
        topics: GitHub トピックタグ。
        name: リポジトリ名。

    Returns:
        カテゴリ名（例: ``"AI/機械学習"``、``"Web開発"``、``"その他"``）。
    """
    all_text = " ".join([language.lower(), name.lower()] + [t.lower() for t in topics])

    if any(kw in all_text for kw in ["ai", "ml", "llm", "machine-learning", "deep-learning"]):
        return "AI/機械学習"
    if any(kw in all_text for kw in ["web", "react", "vue", "next", "frontend", "css"]):
        return "Web開発"
    if any(kw in all_text for kw in ["devops", "docker", "kubernetes", "ci", "cd", "infra"]):
        return "DevOps/インフラ"
    if any(kw in all_text for kw in ["security", "crypto", "auth", "セキュリティ"]):
        return "セキュリティ"
    if any(kw in all_text for kw in ["data", "database", "sql", "analytics"]):
        return "データ"
    if any(kw in all_text for kw in ["mobile", "ios", "android", "flutter", "react-native"]):
        return "モバイル"
    if any(kw in all_text for kw in ["rust", "go", "python", "typescript", "tool", "cli"]):
        return "言語/ツール"
    return "その他"
