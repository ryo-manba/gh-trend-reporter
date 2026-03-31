"""アプリケーション設定管理.

環境変数（``GTR_*`` プレフィクス）から設定値を読み込む。
API キーなどの機密情報は ``repr=False`` で隠蔽される。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """アプリケーション全体の設定を保持するデータクラス.

    Attributes:
        db_path: SQLite データベースファイルのパス。
        reports_dir: 生成レポートの出力ディレクトリ。
        collect_interval: スクレイピング時のリクエスト間隔（秒）。
        github_cache_ttl: ``repo_details`` キャッシュの有効期限（秒）。
        agent_max_turns: エージェントループの最大ターン数。
        github_token: GitHub Personal Access Token。未設定時は未認証モード。
        gemini_api_key: Gemini API キー。
    """

    db_path: Path = field(default_factory=lambda: Path("./data/trends.db"))
    reports_dir: Path = field(default_factory=lambda: Path("./reports"))
    collect_interval: float = 2.0
    github_cache_ttl: int = 86400
    agent_max_turns: int = 10

    github_token: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls) -> Config:
        """環境変数から設定を読み込んでインスタンスを生成する.

        Returns:
            環境変数の値で初期化された Config インスタンス。
        """
        load_dotenv()
        return cls(
            db_path=Path(os.environ.get("GTR_DB_PATH", "./data/trends.db")),
            reports_dir=Path(os.environ.get("GTR_REPORTS_DIR", "./reports")),
            collect_interval=float(os.environ.get("GTR_COLLECT_INTERVAL", "2.0")),
            github_cache_ttl=int(os.environ.get("GTR_CACHE_TTL", "86400")),
            agent_max_turns=int(os.environ.get("GTR_AGENT_MAX_TURNS", "10")),
            github_token=os.environ.get("GITHUB_TOKEN"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        )
