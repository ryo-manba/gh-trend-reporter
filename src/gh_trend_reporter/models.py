"""データモデル（Pydantic）"""

from datetime import date, datetime

from pydantic import BaseModel


class TrendingRepo(BaseModel):
    """GitHub Trending ページから取得した情報"""

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
    """GitHub REST API から取得した詳細情報"""

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


class CategoryGroup(BaseModel):
    """カテゴリ分類結果"""

    category: str
    repos: list[str]
    summary_ja: str


class WeeklyAnalysis(BaseModel):
    """週次分析結果"""

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
    """最終レポート"""

    analysis: WeeklyAnalysis
    generated_at: datetime
    model: str
