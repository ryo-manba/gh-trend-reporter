"""テスト共通 fixtures"""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_trend_reporter.database import Database

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
def db() -> Database:
    database = Database(":memory:")
    database.init()
    yield database  # type: ignore[misc]
    database.close()
