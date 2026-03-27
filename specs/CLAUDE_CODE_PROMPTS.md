# Claude Code 実装プロンプト — gh-trend-reporter

以下のプロンプトを Phase ごとに Claude Code に渡してください。

---

## Phase 1: プロジェクトセットアップ + スクレイパー + GitHub API + DB（Day 1-2）

```
## タスク
`gh-trend-reporter` という Python CLI プロジェクトを新規作成し、GitHub Trending のデータ収集基盤を実装してください。

## プロジェクト仕様
以下のファイルを参照してください:
- SPEC.md: 詳細仕様書
- TEST_SPEC.md: テスト仕様書

## この Phase で実装する範囲
1. プロジェクトのスキャフォールド（uv でセットアップ）
2. `src/gh_trend_reporter/models.py` — Pydantic データモデル
3. `src/gh_trend_reporter/config.py` — 設定管理
4. `src/gh_trend_reporter/scraper.py` — GitHub Trending ページスクレイピング
5. `src/gh_trend_reporter/github_api.py` — GitHub REST API クライアント
6. `src/gh_trend_reporter/database.py` — SQLite データ管理
7. `src/gh_trend_reporter/rate_limiter.py` — Gemini レート制限管理
8. テスト: test_scraper.py, test_github_api.py, test_database.py
9. テスト用 fixtures（HTML, JSON）

## 技術要件
- Python 3.12+
- パッケージ管理: uv
- HTTP: httpx（非同期）
- HTML パース: BeautifulSoup4
- データモデル: Pydantic v2
- DB: sqlite3 標準ライブラリ
- テスト: pytest + pytest-asyncio
- リンター: Ruff
- 型チェック: mypy strict

## pyproject.toml

```toml
[project]
name = "gh-trend-reporter"
version = "0.1.0"
description = "CLI tool to collect GitHub Trending repos and generate weekly technology trend analysis reports"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pydantic>=2.0",
    "click>=8.1",
    "google-genai>=1.0",
    "python-dotenv>=1.0",
]

[project.scripts]
gtr = "gh_trend_reporter.cli:cli"

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

## scraper.py の実装詳細

GitHub Trending ページ（https://github.com/trending）を httpx で取得し、BeautifulSoup4 でパース。

Trending ページの HTML 構造:
- 各リポジトリは `article.Box-row` 要素内
- リポジトリ名: `h2 a` の href 属性（"/owner/name"）
- 説明: `p.col-9` のテキスト
- 言語: `span[itemprop="programmingLanguage"]` のテキスト
- 総スター数: `a[href="/{owner}/{name}/stargazers"]` のテキスト
- 期間内スター増加数: `span.d-inline-block.float-sm-right` のテキスト（"1,234 stars today"）
- フォーク数: `a[href="/{owner}/{name}/forks"]` のテキスト

注意:
- スター数・フォーク数の文字列にカンマが含まれる → int 変換時に除去
- 説明が None の場合がある
- 言語が None の場合がある（Markdown リポジトリ等）

URL パターン:
- daily: https://github.com/trending?since=daily
- weekly: https://github.com/trending?since=weekly
- 言語フィルタ: ?language=python&since=daily

リトライ: 最大3回、指数バックオフ（1秒, 2秒, 4秒）
インターバル: 2秒（礼儀的な待機）

## github_api.py の実装詳細

GitHub REST API v3 を使用:
- Base URL: https://api.github.com
- 認証: Authorization: Bearer {GITHUB_TOKEN}（環境変数、オプション）
- User-Agent ヘッダー必須

エンドポイント:
1. GET /repos/{owner}/{repo} → RepoDetail
   - topics は response["topics"]
   - license は response["license"]["spdx_id"]
2. GET /repos/{owner}/{repo}/readme → Base64 デコード → 冒頭500文字
   - Accept: application/vnd.github.v3+json
   - content フィールドを base64 デコード
3. GET /rate_limit → 残りリクエスト数

キャッシュ:
- repo_details テーブルに保存
- fetched_at から24時間以内なら DB から返す
- TTL 超過 → API から再取得

## database.py の実装詳細

SPEC.md セクション 4.5 の SQL スキーマをそのまま実装。

クラス設計:
- TrendDatabase:
  - __init__(db_path: Path) — DB 接続 + テーブル作成
  - insert_trending_repo(repo: TrendingRepo) → None
  - get_repos_by_date(date: date, since: str) → list[TrendingRepo]
  - get_repos_by_week(week_label: str) → list[TrendingRepo]
  - get_previous_week_repos(week_label: str) → list[TrendingRepo]
  - get_new_entries(current_week: str, previous_week: str) → list[str]
  - insert_repo_detail(detail: RepoDetail) → None
  - get_repo_detail(full_name: str) → RepoDetail | None
  - save_analysis(week_label: str, analysis: WeeklyAnalysis) → None
  - get_analysis(week_label: str) → WeeklyAnalysis | None
  - get_stats() → dict（DB の統計情報）

week_label の計算:
- date(2025, 1, 15).isocalendar() → (2025, 3, 3) → "2025-W03"

## テスト fixtures

tests/fixtures/ に以下を作成:
- trending_daily.html: 25件のリポジトリを含むリアルな Trending ページ HTML
  - 多様な言語（Python, TypeScript, Rust, Go, etc.）
  - スター数にカンマを含む（1,234）
  - 説明が None のリポジトリを1つ含む
- trending_weekly.html: weekly 版
- trending_empty.html: リポジトリ0件
- repo_detail.json: GitHub API のレスポンス例

## 完了条件
- `uv run pytest tests/test_scraper.py tests/test_github_api.py tests/test_database.py -v` が全てパス
- `uv run ruff check src/` がエラーなし
- `uv run mypy src/` がエラーなし
```

---

## Phase 2: エージェント（Function Calling）（Day 3-4）

```
## タスク
gh-trend-reporter に Gemini Function Calling を使ったトレンド分析エージェントを実装してください。
これがプロジェクトの核心部分です。

## 参照
- SPEC.md のセクション 3.3, 4.6
- TEST_SPEC.md のセクション 2.4

## この Phase で実装する範囲
1. `src/gh_trend_reporter/agent.py` — Function Calling エージェント
2. `prompts/agent_system.txt` — エージェントのシステムプロンプト
3. テスト: test_agent.py

## Gemini Function Calling の使い方

google-genai ライブラリの Function Calling:

```python
from google import genai
from google.genai import types

# ツール定義
tools = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_trending_repos",
                description="指定期間のGitHub Trendingリポジトリ一覧をDBから取得する",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "since": types.Schema(type="STRING", enum=["daily", "weekly"]),
                        "language": types.Schema(type="STRING", description="言語フィルタ"),
                        "limit": types.Schema(type="INTEGER", description="取得件数"),
                    },
                    required=["since"],
                ),
            ),
            # ... 他のツールも同様に定義
        ]
    )
]

client = genai.Client(api_key=api_key)

# チャットセッション
chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=tools,
    ),
)

# エージェントループ
response = chat.send_message("今週のトレンドを分析してください")

# Function Call がある場合
if response.candidates[0].content.parts:
    for part in response.candidates[0].content.parts:
        if part.function_call:
            fc = part.function_call
            # ツール実行
            result = execute_function(fc.name, dict(fc.args))
            # 結果をチャットに返す
            response = chat.send_message(
                types.Content(
                    parts=[types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": result}
                        )
                    )]
                )
            )
```

## agent.py の実装詳細

### AnalysisAgent クラス:

```python
class AnalysisAgent:
    def __init__(self, client: genai.Client, db: TrendDatabase, github_api: GitHubAPIClient, rate_limiter: RateLimiter):
        self.client = client
        self.db = db
        self.github_api = github_api
        self.rate_limiter = rate_limiter
        self.max_turns = 10
    
    async def analyze(self, week_label: str) -> WeeklyAnalysis:
        """エージェントループを実行してトレンド分析を返す"""
    
    async def execute_function(self, name: str, args: dict) -> dict:
        """ツール関数を実行"""
        match name:
            case "get_trending_repos":
                return self._get_trending_repos(**args)
            case "get_repo_detail":
                return await self._get_repo_detail(**args)
            case "get_previous_week_trending":
                return self._get_previous_week(**args)
            case "classify_repos":
                return args  # classify は LLM 側で処理、入力をそのまま返す
            case _:
                raise UnknownFunctionError(f"Unknown function: {name}")
```

### ツール関数の実装:

- get_trending_repos: DB から該当週のデータを取得し JSON で返す
- get_repo_detail: まず DB キャッシュを確認、なければ GitHub API で取得して DB に保存
- get_previous_week_trending: DB から前週データを取得
- classify_repos: エージェントの思考プロセスの一部として呼ばれる。引数のリポジトリリストをそのまま返し、LLM が分類結果を生成する

### エージェントループのフロー:

1. システムプロンプトと初期メッセージでチャット開始
2. Gemini のレスポンスを確認:
   - Function Call あり → execute_function → 結果をチャットに返す → 次のターン
   - テキストのみ → JSON パース → WeeklyAnalysis を返す
3. 最大 max_turns 回繰り返し
4. JSON パースエラー → もう1ターンリトライ（「JSONのみ出力してください」と追加）

### プロンプト（prompts/agent_system.txt）:

SPEC.md セクション 4.6 の AGENT_SYSTEM_PROMPT をそのまま使用。

## テスト

テストでは Gemini API をモック化し、Function Call のシーケンスを再現する:

1. Mock が最初のレスポンスとして get_trending_repos の Function Call を返す
2. execute_function の結果を渡すと、次に get_repo_detail の Function Call を返す
3. ... と続き、最後にテキスト（JSON）を返す

conftest.py に MOCK_AGENT_FUNCTION_CALLS と MOCK_ANALYSIS_OUTPUT を定義し、
エージェントが正しい順序でツールを呼び、最終的に有効な WeeklyAnalysis を返すことを検証。

## 完了条件
- `uv run pytest tests/test_agent.py -v` が全てパス
- エージェントが max_turns 以内に分析を完了する
- 各ツール関数が正しいパラメータで呼ばれる
- 最終出力が WeeklyAnalysis の構造を持つ
```

---

## Phase 3: レポーター + CLI 全コマンド（Day 5）

```
## タスク
gh-trend-reporter にレポート生成と全 CLI コマンドを実装してください。

## 参照
- SPEC.md のセクション 4.1, 4.2
- TEST_SPEC.md のセクション 2.5, 2.6, 3

## この Phase で実装する範囲
1. `src/gh_trend_reporter/reporter.py` — Markdown レポート生成
2. `prompts/report_format.txt` — レポートフォーマット指示
3. `src/gh_trend_reporter/cli.py` — Click CLI（全コマンド）
4. テスト: test_reporter.py, test_cli.py, test_integration.py

## reporter.py の実装詳細

- ReportGenerator クラス:
  - render(analysis: WeeklyAnalysis) -> str — Markdown 文字列を生成
  - render_to_file(analysis: WeeklyAnalysis, output_dir: Path) -> Path — ファイルに保存
  - ファイル名: {year}-W{week}.md（例: 2025-W03.md）

Markdown のセクション構成（SPEC.md セクション 4.2 参照）:
1. YAML frontmatter
2. 今週のハイライト（highlights）
3. 言語別ランキング（top_languages テーブル）
4. カテゴリ別分析（categories — 各カテゴリにセクション + 注目リポジトリテーブル）
5. 新登場リポジトリ（new_entries テーブル）
6. 先週との比較（week_over_week）

前週データがない場合（初回実行時）:
- 「新登場リポジトリ」と「先週との比較」セクションをスキップ

## cli.py の実装詳細

Click グループ構成:

```python
@click.group()
def cli():
    """GitHub Trending 解析レポーター"""
    pass

@cli.command()
@click.option("--language", default="", help="言語フィルタ")
@click.option("--since", default="both", type=click.Choice(["daily", "weekly", "both"]))
async def collect(language, since):
    """Trending データを収集して DB に保存"""

@cli.command()
@click.option("--week", default=None, help="分析対象の週（例: 2025-W03）。未指定なら今週")
async def analyze(week):
    """エージェントでトレンド分析を実行"""

@cli.command()
@click.option("--week", default=None)
@click.option("--output", default="./reports", type=click.Path())
async def report(week, output):
    """Markdown レポートを生成"""

@cli.command()
async def run():
    """collect + analyze + report を一括実行"""

@cli.command()
def status():
    """DB の統計と残り API 呼び出し数を表示"""
```

非同期コマンドの処理:
- Click は同期なので、asyncio.run() でラップする
- または click-async 等は使わず、sync wrapper を作成

## Integration テスト

fixture HTML + Gemini モック → collect → DB 確認 → analyze → DB 確認 → report → Markdown 確認

## 完了条件
- `uv run pytest -v` が全てパス（Unit + Integration）
- `gtr collect` で Trending データが DB に保存される
- `gtr analyze` でエージェント分析が実行される
- `gtr report` で Markdown レポートが reports/ に生成される
- `gtr run` で一括実行できる
- `gtr status` で DB 統計が表示される
```

---

## Phase 4: 仕上げ（Day 6-7）

```
## タスク
gh-trend-reporter を公開品質に仕上げてください。

## この Phase で実施する範囲

### 1. README.md の作成
以下のセクションを含む:
- プロジェクト概要（英語 + 日本語）
- 出力レポートのサンプル（スクリーンショット or Markdown 抜粋）
- インストール方法（uv 前提）
- 使い方（collect, analyze, report, run, status）
- アーキテクチャ図（テキストベース）
  - 特に: エージェントループ（Plan → Act → Observe → Reflect）の解説
- 技術スタック
- Function Calling の設計解説（面接で語れるレベル）
  - なぜ Function Calling を使ったのか
  - ツール設計の判断基準
  - エージェントループの設計
- データベース設計の解説
- レート制限（GitHub + Gemini の二重管理）の解説
- 開発方法（テスト実行、リンター）
- License: MIT

### 2. コード品質の最終確認
- Ruff で全ファイルチェック・修正
- mypy strict で全ファイル型チェック
- docstring の追加（Google style）

### 3. 出力サンプルの作成
- 実際に collect → analyze → report を実行し、reports/ にサンプルを配置
- 最低1週分のレポート

### 4. CI/CD 設定
- .github/workflows/ci.yml:
  - Python 3.12
  - uv install
  - Ruff check
  - mypy check
  - pytest with coverage（Gemini / GitHub API はモック）
  - カバレッジ 85% 未満で失敗

### 5. その他
- .env.example
- .gitignore（data/*.db を除外、reports/*.md は含める）
- CHANGELOG.md（v0.1.0）

## 完了条件
- README.md が面接で見せられるクオリティ
- CI が全てグリーン
- reports/ にサンプルレポートが1つ以上
- `git log` が意味のあるコミット履歴
```

---

## 補足: Project C → F の順番で実装する際の注意

1. **rate_limiter.py を共有設計にする**: Project C と F で同じ Gemini 無料枠を使うため、state_file のパスを変えるか、共通の状態ファイルにする。RPD のカウントが別々にならないよう注意。
2. **環境変数**: `.env` に GEMINI_API_KEY は共通、GITHUB_TOKEN は F のみ。
3. **レジュメ上の見せ方**: C はプロンプト設計の深さ、F はエージェント設計（Function Calling）の深さで差別化する。
