"""Click ベースの CLI エントリーポイント.

``gtr`` コマンドとして以下のサブコマンドを提供する:

- ``collect``: GitHub Trending データの収集
- ``analyze``: Gemini エージェントによるトレンド分析
- ``report``: Markdown レポートの生成
- ``run``: collect → analyze → report の一括実行
- ``status``: DB 統計情報の表示
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

import click

from gh_trend_reporter.config import Config
from gh_trend_reporter.database import Database

logger = logging.getLogger(__name__)


def _current_week_label() -> str:
    """現在の ISO 週ラベルを返す.

    Returns:
        ``"YYYY-WNN"`` 形式の文字列（例: ``"2025-W03"``）。
    """
    today = date.today()
    return f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"


@click.group()
def main() -> None:
    """gh-trend-reporter: GitHub Trending 解析レポーター"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@main.command()
@click.option("--language", default=None, help="プログラミング言語フィルタ")
@click.option(
    "--since",
    default=None,
    type=click.Choice(["daily", "weekly"]),
    help="期間フィルタ（daily/weekly）",
)
def collect(language: str | None, since: str | None) -> None:
    """Trending データを収集して DB に保存"""
    asyncio.run(_collect(language=language, since=since))


async def _collect(language: str | None = None, since: str | None = None) -> None:
    """collect コマンドの非同期実装.

    Args:
        language: 言語フィルタ。None で全言語。
        since: 期間フィルタ。None で daily + weekly の両方を収集。
    """
    from gh_trend_reporter.scraper import TrendingScraper

    config = Config.load()
    db = Database(config.db_path)
    db.init()
    scraper = TrendingScraper(interval=config.collect_interval)

    try:
        periods = [since] if since else ["daily", "weekly"]
        total = 0
        for period in periods:
            click.echo(f"Collecting {period} trending repos...")
            repos = await scraper.scrape(since=period, language=language)
            count = db.insert_trending_repos(repos)
            total += count
            click.echo(f"  {count} repos saved ({period})")

        click.echo(f"Done! {total} repos collected.")
    finally:
        await scraper.close()
        db.close()


@main.command()
@click.option("--week", default=None, help="分析対象の週（例: 2025-W03）")
def analyze(week: str | None) -> None:
    """トレンドを分析"""
    asyncio.run(_analyze(week=week))


async def _analyze(week: str | None = None) -> None:
    """analyze コマンドの非同期実装.

    Args:
        week: 分析対象の週ラベル。None で今週を対象。
    """
    from gh_trend_reporter.agent import AnalysisAgent
    from gh_trend_reporter.github_api import GitHubAPI

    config = Config.load()
    db = Database(config.db_path)
    db.init()

    week_label = week or _current_week_label()

    repos = db.get_repos_by_week(week_label)
    if not repos:
        click.echo(f"Error: {week_label} のデータがありません。先に collect を実行してください。")
        db.close()
        sys.exit(1)

    github_api = GitHubAPI(token=config.github_token)
    agent = AnalysisAgent(config=config, db=db, github_api=github_api)

    try:
        click.echo(f"Analyzing {week_label} ({len(repos)} repos)...")
        analysis = await agent.run_agent(week_label)
        db.save_weekly_analysis(analysis)
        click.echo(f"Analysis complete for {week_label}.")
    finally:
        await github_api.close()
        db.close()


@main.command()
@click.option("--week", default=None, help="レポート対象の週（例: 2025-W03）")
@click.option("--format", "fmt", default="md", type=click.Choice(["md"]), help="出力フォーマット")
def report(week: str | None, fmt: str) -> None:
    """Markdown レポートを生成"""
    _report_sync(week=week, fmt=fmt)


def _report_sync(week: str | None = None, fmt: str = "md") -> None:
    """report コマンドの同期実装.

    Args:
        week: レポート対象の週ラベル。None で今週を対象。
        fmt: 出力フォーマット（現在は ``"md"`` のみ対応）。
    """
    from gh_trend_reporter.reporter import ReportGenerator

    config = Config.load()
    db = Database(config.db_path)
    db.init()

    week_label = week or _current_week_label()

    try:
        analysis = db.get_weekly_analysis(week_label)
        if analysis is None:
            click.echo(
                f"Error: {week_label} の分析結果がありません。先に analyze を実行してください。"
            )
            sys.exit(1)

        generator = ReportGenerator(reports_dir=config.reports_dir)
        weekly_report = ReportGenerator.build_report(analysis, model="gemini-2.5-flash")
        path = generator.save(weekly_report)
        click.echo(f"Report saved to {path}")
    finally:
        db.close()


@main.command()
@click.option("--language", default=None, help="プログラミング言語フィルタ")
@click.option("--week", default=None, help="対象の週（例: 2025-W03）")
def run(language: str | None, week: str | None) -> None:
    """一括実行（collect + analyze + report）"""
    asyncio.run(_run(language=language, week=week))


async def _run(language: str | None = None, week: str | None = None) -> None:
    """run コマンドの非同期実装（collect → analyze → report）.

    Args:
        language: 言語フィルタ。
        week: 対象の週ラベル。
    """
    await _collect(language=language)
    await _analyze(week=week)
    _report_sync(week=week)


@main.command()
def status() -> None:
    """DB の統計情報を表示"""
    config = Config.load()
    db = Database(config.db_path)
    try:
        db.init()
    except Exception as e:
        click.echo(f"Error: DB を開けません: {e}")
        sys.exit(1)

    try:
        trending_count = db.conn.execute("SELECT COUNT(*) FROM trending_repos").fetchone()[0]
        detail_count = db.conn.execute("SELECT COUNT(*) FROM repo_details").fetchone()[0]
        analysis_count = db.conn.execute("SELECT COUNT(*) FROM weekly_analyses").fetchone()[0]

        latest_row = db.conn.execute(
            "SELECT MAX(collected_at) FROM trending_repos"
        ).fetchone()
        latest_date = latest_row[0] if latest_row and latest_row[0] else "N/A"

        click.echo("=== gh-trend-reporter status ===")
        click.echo(f"DB path:           {config.db_path}")
        click.echo(f"Trending repos:    {trending_count}")
        click.echo(f"Repo details:      {detail_count}")
        click.echo(f"Weekly analyses:   {analysis_count}")
        click.echo(f"Latest collection: {latest_date}")
    finally:
        db.close()
