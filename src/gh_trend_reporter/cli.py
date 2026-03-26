"""Click CLI エントリーポイント"""

import click


@click.group()
def main() -> None:
    """gh-trend-reporter: GitHub Trending 解析レポーター"""


@main.command()
def collect() -> None:
    """Trending データを収集して DB に保存"""
    click.echo("collect: not yet implemented")


@main.command()
def analyze() -> None:
    """トレンドを分析"""
    click.echo("analyze: not yet implemented")


@main.command()
def report() -> None:
    """Markdown レポートを生成"""
    click.echo("report: not yet implemented")
