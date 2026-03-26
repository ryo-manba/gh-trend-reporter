"""設定管理"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """アプリケーション設定"""

    db_path: Path = field(default_factory=lambda: Path("./data/trends.db"))
    reports_dir: Path = field(default_factory=lambda: Path("./reports"))
    collect_interval: float = 2.0
    github_cache_ttl: int = 86400
    agent_max_turns: int = 10

    github_token: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls) -> Config:
        """環境変数から設定を読み込む"""
        return cls(
            db_path=Path(os.environ.get("GTR_DB_PATH", "./data/trends.db")),
            reports_dir=Path(os.environ.get("GTR_REPORTS_DIR", "./reports")),
            collect_interval=float(os.environ.get("GTR_COLLECT_INTERVAL", "2.0")),
            github_cache_ttl=int(os.environ.get("GTR_CACHE_TTL", "86400")),
            agent_max_turns=int(os.environ.get("GTR_AGENT_MAX_TURNS", "10")),
            github_token=os.environ.get("GITHUB_TOKEN"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        )
