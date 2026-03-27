# gh-trend-reporter

GitHub Trending リポジトリを自動収集し、Gemini API の Function Calling で技術トレンドを分析・分類して、日本語の週次レポートを Markdown で出力する CLI ツール。

[![CI](https://github.com/ryo-manba/gh-trend-reporter/actions/workflows/ci.yml/badge.svg)](https://github.com/ryo-manba/gh-trend-reporter/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

- **GitHub Trending** ページを daily / weekly でスクレイピングし、SQLite に蓄積
- **Gemini 2.5 Flash** の Function Calling エージェントがトレンドデータを自律的に分析
- カテゴリ分類・前週比較・注目ポイント抽出を含む**日本語 Markdown レポート**を自動生成

```
gtr collect       # Trending データを収集
gtr analyze       # エージェントがトレンド分析
gtr report        # Markdown レポート生成
gtr run           # ↑ を一括実行
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI (Click)                              │
│   collect ──→ analyze ──→ report                                │
└──────┬──────────┬───────────┬───────────────────────────────────┘
       │          │           │
       ▼          ▼           ▼
┌──────────┐ ┌────────────────────────┐ ┌────────────────────────┐
│ Scraper  │ │   Analysis Agent       │ │   Report Generator     │
│ (httpx + │ │   (Gemini FC loop)     │ │   (Markdown render)    │
│  BS4)    │ │                        │ │                        │
└────┬─────┘ │  Plan → Act → Observe  │ └───────────┬────────────┘
     │       │       → Reflect        │             │
     │       └──┬───────┬─────────────┘             │
     │          │       │                           │
     ▼          ▼       ▼                           ▼
┌──────────────────────────────────┐    ┌───────────────────────┐
│        SQLite Database           │    │  reports/2025-W03.md  │
│  trending_repos │ repo_details   │    └───────────────────────┘
│  weekly_analyses                 │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│        GitHub REST API           │
│  (repos, readme, rate_limit)     │
└──────────────────────────────────┘
```

## Function Calling エージェント設計

本プロジェクトの核心は、Gemini の Function Calling を活用した **自律型分析エージェント** にあります。

### エージェントループ: Plan → Act → Observe → Reflect

エージェントは単純な 1 回の API コールではなく、**複数ターンの対話ループ**で分析を行います。

```
                    ┌─────────────────────────┐
                    │   System Prompt +       │
                    │   Tool Definitions      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
              ┌────→│   Gemini API Call        │
              │     │   (generate_content)     │
              │     └────────────┬────────────┘
              │                  │
              │         ┌───────┴───────┐
              │         │               │
              │    Function Call?   Text Response?
              │         │               │
              │         ▼               ▼
              │    ┌──────────┐   ┌──────────────┐
              │    │ Execute  │   │ Parse JSON   │
              │    │ Function │   │ → Analysis   │
              │    └────┬─────┘   │   Complete   │
              │         │         └──────────────┘
              │         ▼
              │    ┌──────────┐
              └────│ Feed     │
                   │ Result   │
                   └──────────┘
```

**各フェーズの役割:**

| フェーズ | 内容 | 実装上のポイント |
|---------|------|----------------|
| **Plan** | Gemini がシステムプロンプトに基づき分析方針を決定 | プロンプトに分析手順（5 ステップ）を明示的に記載 |
| **Act** | 必要なツール関数を Function Calling で呼び出し | Gemini が引数（since, language, owner 等）を自動決定 |
| **Observe** | 関数の実行結果を会話履歴にフィードバック | `Part.from_function_response()` で構造化データを返却 |
| **Reflect** | 十分なデータが集まったら JSON 形式で最終分析を出力 | テキスト応答の検出でループ終了を判定 |

### 利用可能なツール関数

エージェントは以下の 4 つのツール関数を自律的に選択・呼び出します。

| ツール | 目的 | データソース |
|-------|------|------------|
| `get_trending_repos` | 今週の Trending 一覧を取得 | SQLite (trending_repos) |
| `get_repo_detail` | 特定リポジトリの詳細（トピック、README）を取得 | DB キャッシュ → GitHub API |
| `get_previous_week_trending` | 前週データを取得して新登場リポジトリを特定 | SQLite (trending_repos) |
| `classify_repos` | リポジトリ群を技術カテゴリに分類 | ヒューリスティック分類 |

### なぜ Function Calling を使うのか

単純にプロンプトにデータを全て詰め込むアプローチと比較して:

1. **トークン効率**: 全リポジトリの詳細を一度に渡すのではなく、エージェントが注目リポジトリのみ `get_repo_detail` で深掘り
2. **柔軟性**: 分析の流れがハードコードされておらず、Gemini が状況に応じてツール呼び出し順序を決定
3. **拡張性**: 新しいツール関数（例: GitHub Discussions の取得）を追加するだけでエージェントの能力を拡張可能
4. **再現性**: `_function_call_log` で全てのツール呼び出しを記録し、デバッグ・テストに活用

### 実装の詳細

```python
# agent.py — エージェントループの核心部分（簡略化）

async def run_agent(self, week_label: str) -> WeeklyAnalysis:
    contents = [user_message(f"今週（{week_label}）のデータを分析してください。")]
    tool = types.Tool(function_declarations=self._tool_declarations)

    for turn in range(max_turns):
        await self._rate_limiter.acquire()  # Gemini レート制限を遵守
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=gen_config,
        )

        if response.function_calls:
            # Act: ツール関数を実行
            for fc in response.function_calls:
                result = await self._execute_function(fc.name, fc.args)
                # Observe: 結果を会話履歴にフィードバック
                contents.append(function_response(fc.name, result))
        else:
            # Reflect: テキスト応答 → 分析完了
            return self._parse_analysis(response.text, week_label)

    raise AgentMaxTurnsError("最大ターン数に到達")
```

## レート制限の二重管理

本ツールは 2 つの異なる API のレート制限を同時に管理します。

### GitHub API: ヘッダーベース監視

| モード | 制限 | 管理方法 |
|-------|------|---------|
| 認証あり (GITHUB_TOKEN) | 5,000 req/h | `X-RateLimit-Remaining` ヘッダー監視 |
| 未認証 | 60 req/h | 同上（自動フォールバック） |
| スクレイピング | なし（礼儀的制限） | `collect_interval` 秒のインターバル |

```python
# github_api.py — レスポンスヘッダーから残り枠を確認
def _check_rate_limit(self, response: httpx.Response) -> None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None and int(remaining) == 0:
        reset_at = datetime.fromtimestamp(
            int(response.headers["X-RateLimit-Reset"])
        )
        raise RateLimitExceeded(reset_at)
```

### Gemini API: スライディングウィンドウ方式

| 制限 | 値 | 超過時の動作 |
|------|---|------------|
| RPM (Requests Per Minute) | 10 | 自動待機 (asyncio.sleep) |
| RPD (Requests Per Day) | 250 | RuntimeError 送出 |

```python
# rate_limiter.py — 分単位・日単位のスライディングウィンドウ
async def acquire(self) -> None:
    while True:
        self._cleanup()  # ウィンドウ外のタイムスタンプを除去

        if len(self._day_timestamps) >= self.max_requests_per_day:
            raise RuntimeError("Daily rate limit exhausted")

        if len(self._minute_timestamps) >= self.max_requests_per_minute:
            wait = 60.0 - (time.monotonic() - self._minute_timestamps[0])
            await asyncio.sleep(wait + 0.1)
            continue

        self._minute_timestamps.append(time.monotonic())
        self._day_timestamps.append(time.monotonic())
        return
```

**設計上の意図**: GitHub API はサーバー側ヘッダーで管理（リアクティブ）、Gemini API はクライアント側タイムスタンプで管理（プロアクティブ）。無料枠の Gemini は超過ペナルティが大きいため、クライアント側で事前に制御しています。

## Data Flow

```
GitHub Trending HTML ──scraper──→ TrendingRepo[] ──database──→ SQLite
                                                                  │
                        ┌─ get_trending_repos ◄───────────────────┤
                        ├─ get_repo_detail ◄── GitHub API (cached)│
Gemini Agent ◄──────────┤                                         │
(Function Calling loop) ├─ get_previous_week_trending ◄───────────┤
                        └─ classify_repos                         │
                               │                                  │
                               ▼                                  │
                        WeeklyAnalysis ──database──→ SQLite ──────┘
                               │
                               ▼
                        ReportGenerator ──→ reports/2025-W03.md
```

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (パッケージマネージャー)

### Installation

```bash
git clone https://github.com/ryo-manba/gh-trend-reporter.git
cd gh-trend-reporter
uv sync
```

### Configuration

```bash
cp .env.example .env
# .env を編集して API キーを設定
```

| 環境変数 | 必須 | 説明 |
|---------|------|------|
| `GEMINI_API_KEY` | Yes | Gemini API キー（[Google AI Studio](https://aistudio.google.com/) で取得） |
| `GITHUB_TOKEN` | No | GitHub PAT（未設定でも動作、レート制限 60 req/h） |

## Usage

```bash
# データ収集（毎日実行推奨）
gtr collect
gtr collect --language python    # 言語フィルタ
gtr collect --since weekly       # weekly のみ

# トレンド分析（週次）
gtr analyze
gtr analyze --week 2025-W03     # 特定週

# レポート生成
gtr report
gtr report --week 2025-W03

# 一括実行（collect → analyze → report）
gtr run

# DB 統計
gtr status
```

### Output Example

生成されるレポートは `reports/` ディレクトリに保存されます:

```
reports/
└── 2025-W03.md
```

レポートには以下のセクションが含まれます:
- 今週のハイライト（3〜5 個の注目ポイント）
- 言語別ランキング（テーブル形式）
- カテゴリ別分析（AI/ML, Web 開発, DevOps 等）
- 新登場リポジトリ一覧
- 先週との比較コメント

## Tech Stack

| カテゴリ | 技術 | 用途 |
|---------|------|------|
| Language | Python 3.12+ | 型ヒント、async/await |
| LLM | Gemini 2.5 Flash | Function Calling エージェント |
| HTTP | httpx | 非同期 HTTP クライアント |
| HTML Parser | BeautifulSoup4 | Trending ページ解析 |
| CLI | Click | コマンドラインインターフェース |
| Data | SQLite (stdlib) | データ永続化・キャッシュ |
| Models | Pydantic v2 | 型安全なデータモデル |
| Test | pytest + pytest-asyncio | 非同期テスト |
| Lint | Ruff | リンター + フォーマッター |
| Type Check | mypy (strict) | 静的型チェック |
| Package | uv | 高速パッケージマネージャー |

## Development

```bash
# テスト実行
uv run pytest

# カバレッジ付きテスト
uv run pytest --cov=gh_trend_reporter --cov-report=term-missing

# リンター
uv run ruff check src/ tests/

# 型チェック
uv run mypy src/
```

## Project Structure

```
gh-trend-reporter/
├── src/gh_trend_reporter/
│   ├── __init__.py          # パッケージ初期化・バージョン定義
│   ├── models.py            # Pydantic データモデル
│   ├── config.py            # 環境変数ベースの設定管理
│   ├── scraper.py           # GitHub Trending スクレイパー
│   ├── github_api.py        # GitHub REST API クライアント
│   ├── database.py          # SQLite CRUD・キャッシュ管理
│   ├── agent.py             # Gemini FC エージェント（核心）
│   ├── rate_limiter.py      # Gemini レート制限管理
│   ├── reporter.py          # Markdown レポート生成
│   └── cli.py               # Click CLI エントリーポイント
├── tests/                   # pytest テストスイート
├── prompts/                 # エージェント用プロンプトテンプレート
├── reports/                 # 生成されたレポート出力先
├── data/                    # SQLite データベース
└── specs/                   # 設計仕様書
```

## License

MIT
