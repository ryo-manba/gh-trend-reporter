"""データモデル定義.

Pydantic v2 を使用した型安全なデータモデル群。
データ収集パイプラインの各段階で使用される構造体を定義する。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, model_validator


class TrendingRepo(BaseModel):
    """GitHub Trending ページから取得したリポジトリ情報.

    Attributes:
        owner: リポジトリオーナー名（例: ``"google"``）。
        name: リポジトリ名（例: ``"gemma"``）。
        description: リポジトリの説明文。Trending ページに表示がなければ None。
        language: 主要プログラミング言語。未表示の場合は None。
        stars: 総スター数。
        stars_since: 指定期間内のスター増加数。
        forks: 総フォーク数。
        since: 収集期間（``"daily"`` または ``"weekly"``）。
        collected_at: データ収集日。
    """

    owner: str
    name: str
    description: str | None
    language: str | None
    stars: int
    stars_since: int
    forks: int
    since: str  # "daily" | "weekly"
    collected_at: date


class RepoDetail(BaseModel):
    """GitHub REST API から取得したリポジトリ詳細情報.

    リポジトリのメタデータと README 冒頭を保持する。
    DB にキャッシュされ、TTL 内であれば API コールなしで再利用される。

    Attributes:
        owner: リポジトリオーナー名。
        name: リポジトリ名。
        full_name: ``"owner/name"`` 形式のフルネーム。
        topics: GitHub トピックタグのリスト。
        readme_excerpt: README 冒頭（最大 500 文字）。
        license: SPDX ライセンス識別子（例: ``"MIT"``）。不明の場合は None。
        open_issues: オープン Issue 数。
        open_prs: オープン PR 数。
        last_pushed: 最終プッシュ日時。
        created_at: リポジトリ作成日時。
        homepage: プロジェクトのホームページ URL。未設定の場合は None。
    """

    owner: str
    name: str
    full_name: str
    topics: list[str]
    readme_excerpt: str
    license: str | None
    open_issues: int
    open_prs: int
    last_pushed: datetime
    created_at: datetime
    homepage: str | None


class CategoryRepo(BaseModel):
    """カテゴリ内の個別リポジトリ情報.

    Attributes:
        name: リポジトリの ``full_name``（例: ``"owner/repo"``）。
        description: リポジトリの概要（一言説明）。
    """

    name: str
    description: str = ""


class CategoryGroup(BaseModel):
    """エージェントによる技術カテゴリ分類結果.

    Attributes:
        category: カテゴリ名（例: ``"AI/機械学習"``、``"Web開発"``）。
        repos: カテゴリに属するリポジトリのリスト。
        summary_ja: カテゴリの動向を日本語で要約したテキスト。
    """

    category: str
    repos: list[CategoryRepo]
    summary_ja: str

    @model_validator(mode="before")
    @classmethod
    def _coerce_repos(cls, values: Any) -> Any:
        """旧形式（list[str]）の repos を CategoryRepo に変換する."""
        repos = values.get("repos", [])
        if repos and isinstance(repos[0], str):
            values["repos"] = [{"name": r, "description": ""} for r in repos]
        return values


class WeeklyAnalysis(BaseModel):
    """週次トレンド分析結果.

    エージェントが生成した分析 JSON をパースしたモデル。
    レポート生成と DB 永続化の両方で使用される。

    Attributes:
        week_label: ISO 週ラベル（例: ``"2025-W03"``）。
        period_start: 分析期間の開始日（月曜日）。
        period_end: 分析期間の終了日（日曜日）。
        total_repos_collected: 収集されたリポジトリ総数。
        top_languages: 言語別ランキング。各要素は language, count, percentage を含む。
        categories: カテゴリ別分類結果のリスト。
        highlights: 今週の注目ポイント（3〜5 個）。
        new_entries: 今週新たに Trending 入りしたリポジトリの full_name リスト。
        rising_repos: スター急増リポジトリ。各要素は name, stars_since, reason を含む。
        week_over_week: 先週との比較コメント。
    """

    week_label: str
    period_start: date
    period_end: date
    total_repos_collected: int
    top_languages: list[dict[str, str | int | float]]
    categories: list[CategoryGroup]
    highlights: list[str]
    new_entries: list[str]
    rising_repos: list[dict[str, str | int | float]]
    week_over_week: str


class WeeklyReport(BaseModel):
    """最終出力レポート.

    WeeklyAnalysis にメタ情報を付与した、レポート生成用のラッパーモデル。

    Attributes:
        analysis: 週次分析結果。
        generated_at: レポート生成日時。
        model: 使用した LLM モデル名（例: ``"gemini-2.5-flash"``）。
    """

    analysis: WeeklyAnalysis
    generated_at: datetime
    model: str
