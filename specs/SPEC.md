# gh-trend-reporter — GitHub Trending 解析レポーター

## 1. プロジェクト概要

### 1.1 プロジェクト名
`gh-trend-reporter`

### 1.2 一言説明
GitHub Trending リポジトリを自動収集し、Gemini API（Function Calling）で技術トレンドを分析・分類して日本語の週次レポートを Markdown で出力する CLI ツール。

### 1.3 解決する課題
- GitHub Trending を毎日チェックする時間がない
- Trending に上がったリポジトリの技術的意味を素早く把握したい
- 技術トレンドの変化を週単位で追いたい

### 1.4 レジュメへの記載イメージ
> **gh-trend-reporter** — CLI tool that collects GitHub Trending repositories and generates weekly technology trend analysis reports in Japanese. Built with Gemini API Function Calling for multi-step data gathering (trending scrape → repo detail fetch → README analysis → trend classification), featuring an agent loop (Plan → Act → Observe → Reflect) and persistent trend history with week-over-week comparison.

### 1.5 面接で語れるポイント
- **エージェント設計**: Plan → Act → Observe → Reflect のエージェントループ実装
- **Function Calling**: GitHub API 呼び出しを Gemini の Function Calling で制御
- **データ収集パイプライン**: スクレイピング + API の組み合わせ
- **トレンド分析**: 週次比較・カテゴリ分類のプロンプト設計
- **レート制限の二重管理**: GitHub API（5000 req/h）+ Gemini 無料枠（10 RPM / 250 RPD）

---

## 2. 技術スタック

| カテゴリ | 技術 | 理由 |
|---------|------|------|
| 言語 | Python 3.12+ | SB OAI Japan の業務中心言語 |
| LLM | Gemini 2.5 Flash | 無料枠。Function Calling 対応 |
| HTTP クライアント | httpx | 非同期、GitHub API + スクレイピング |
| HTML パーサー | BeautifulSoup4 | Trending ページの解析 |
| CLI フレームワーク | Click | Project C と共通 |
| データ永続化 | SQLite（sqlite3 標準ライブラリ）| トレンド履歴の蓄積 |
| 出力 | Markdown (.md) | そのまま GitHub / Zenn で閲覧可能 |
| テスト | pytest + pytest-asyncio | |
| パッケージ管理 | uv | Project C と共通 |
| リンター | Ruff | |
| 型チェック | mypy (strict) | |

---

## 3. アーキテクチャ

### 3.1 全体フロー

```
[CLI コマンド]
     │
     ├── gtr collect ──────────────────────┐
     │   (Trending データ収集・DB保存)       │
     │                                      │
     ├── gtr analyze ──────────────────────┤
     │   (エージェントがトレンド分析)         │
     │                                      │
     └── gtr report ───────────────────────┘
         (Markdown レポート生成)
```

### 3.2 データ収集パイプライン

```
[Step 1] GitHub Trending ページをスクレイピング
  │  GET https://github.com/trending?since=daily
  │  GET https://github.com/trending?since=weekly
  │  → リポジトリ名, 説明, 言語, スター数, 期間内スター増加数
  │
  ▼
[Step 2] GitHub REST API でリポジトリ詳細を取得
  │  GET /repos/{owner}/{repo}
  │  → トピックタグ, README 冒頭, ライセンス, 最終更新日, Issue/PR数
  │  ※ Function Calling でエージェントが必要なリポジトリを選択
  │
  ▼
[Step 3] SQLite に保存
  │  trending_repos テーブル: 日次スナップショット
  │  repo_details テーブル: リポジトリ詳細キャッシュ
  │
  ▼
[Step 4] エージェントによるトレンド分析（Gemini Function Calling）
  │  エージェントループ:
  │  1. Plan: 今週のデータを見て分析方針を決定
  │  2. Act: 必要に応じて追加データ取得（Function Calling）
  │  3. Observe: 取得データを確認
  │  4. Reflect: トレンドを分類・分析
  │
  ▼
[Step 5] Markdown レポート生成
  │
  ▼
reports/{year}-W{week}.md
```

### 3.3 エージェント設計（核心部分）

エージェントは Gemini の Function Calling を使い、以下のツール（関数）を呼び出せる:

```python
AGENT_TOOLS = [
    {
        "name": "get_trending_repos",
        "description": "指定期間のGitHub Trendingリポジトリ一覧をDBから取得する",
        "parameters": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "enum": ["daily", "weekly"]},
                "language": {"type": "string", "description": "プログラミング言語フィルタ（空文字で全言語）"},
                "limit": {"type": "integer", "description": "取得件数（デフォルト25）"}
            },
            "required": ["since"]
        }
    },
    {
        "name": "get_repo_detail",
        "description": "特定リポジトリの詳細情報（トピック、README冒頭、Issue数等）を取得する",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"}
            },
            "required": ["owner", "repo"]
        }
    },
    {
        "name": "get_previous_week_trending",
        "description": "前週のTrendingデータをDBから取得し、今週との比較に使う",
        "parameters": {
            "type": "object",
            "properties": {
                "weeks_ago": {"type": "integer", "description": "何週間前のデータか（デフォルト1）"}
            }
        }
    },
    {
        "name": "classify_repos",
        "description": "リポジトリ群を技術カテゴリに分類する",
        "parameters": {
            "type": "object",
            "properties": {
                "repos": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "language": {"type": "string"},
                        "topics": {"type": "array", "items": {"type": "string"}}
                    }}
                }
            },
            "required": ["repos"]
        }
    }
]
```

エージェントループの実装:

```python
async def run_agent(self, week_data: WeekData) -> AnalysisResult:
    """Plan → Act → Observe → Reflect のエージェントループ"""
    
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"今週（{week_data.week_label}）のGitHub Trendingデータを分析してください。"}
    ]
    
    max_turns = 10  # 無限ループ防止
    
    for turn in range(max_turns):
        response = await self.client.generate_content(
            model="gemini-2.5-flash",
            contents=messages,
            tools=AGENT_TOOLS,
        )
        
        # Function Call があれば実行
        if response.function_calls:
            for fc in response.function_calls:
                result = await self.execute_function(fc.name, fc.args)
                messages.append({"role": "function", "name": fc.name, "content": json.dumps(result)})
        else:
            # テキスト応答 → 分析完了
            return self.parse_analysis(response.text)
    
    raise AgentMaxTurnsError("エージェントが最大ターン数に達しました")
```

### 3.4 ディレクトリ構造

```
gh-trend-reporter/
├── src/
│   └── gh_trend_reporter/
│       ├── __init__.py
│       ├── cli.py              # Click CLI エントリーポイント
│       ├── config.py           # 設定管理
│       ├── scraper.py          # GitHub Trending ページスクレイピング
│       ├── github_api.py       # GitHub REST API クライアント
│       ├── database.py         # SQLite データ管理
│       ├── agent.py            # Gemini Function Calling エージェント
│       ├── reporter.py         # Markdown レポート生成
│       ├── rate_limiter.py     # Gemini レート制限管理
│       └── models.py           # データモデル（Pydantic）
├── tests/
│   ├── conftest.py
│   ├── test_scraper.py
│   ├── test_github_api.py
│   ├── test_database.py
│   ├── test_agent.py
│   ├── test_reporter.py
│   └── fixtures/
│       ├── trending_daily.html
│       ├── trending_weekly.html
│       └── repo_detail.json
├── prompts/
│   ├── agent_system.txt        # エージェントのシステムプロンプト
│   └── report_format.txt       # レポートフォーマット指示
├── reports/                    # 生成されたレポート
├── data/                       # SQLite DB
├── pyproject.toml
├── README.md
└── .env.example
```

### 3.5 データモデル

```python
from pydantic import BaseModel
from datetime import date, datetime

class TrendingRepo(BaseModel):
    """GitHub Trending ページから取得した情報"""
    owner: str
    name: str
    description: str | None
    language: str | None
    stars: int
    stars_since: int          # 期間内のスター増加数
    forks: int
    since: str                # "daily" | "weekly"
    collected_at: date

class RepoDetail(BaseModel):
    """GitHub REST API から取得した詳細情報"""
    owner: str
    name: str
    full_name: str
    topics: list[str]
    readme_excerpt: str       # README 冒頭500文字
    license: str | None
    open_issues: int
    open_prs: int
    last_pushed: datetime
    created_at: datetime
    homepage: str | None

class CategoryGroup(BaseModel):
    """カテゴリ分類結果"""
    category: str             # "AI/ML", "Web開発", "DevOps", "セキュリティ" 等
    repos: list[str]          # リポジトリの full_name リスト
    summary_ja: str           # カテゴリの動向要約

class WeeklyAnalysis(BaseModel):
    """週次分析結果"""
    week_label: str           # "2025-W03"
    period_start: date
    period_end: date
    total_repos_collected: int
    top_languages: list[dict] # [{"language": "Python", "count": 12, "percentage": 24.0}]
    categories: list[CategoryGroup]
    highlights: list[str]     # 注目ポイント（3〜5個）
    new_entries: list[str]    # 先週にはなかった新登場リポジトリ
    rising_repos: list[dict]  # スター急増リポジトリ
    week_over_week: str       # 先週との比較コメント

class WeeklyReport(BaseModel):
    """最終レポート"""
    analysis: WeeklyAnalysis
    generated_at: datetime
    model: str
```

---

## 4. 機能仕様

### 4.1 CLI インターフェース

```bash
# データ収集（毎日実行推奨）
gtr collect
gtr collect --language python    # 言語フィルタ
gtr collect --since weekly       # weekly のみ

# トレンド分析（週次）
gtr analyze
gtr analyze --week 2025-W03     # 特定週の分析

# レポート生成
gtr report
gtr report --week 2025-W03
gtr report --format md           # Markdown（デフォルト）

# 一括実行（collect + analyze + report）
gtr run

# ステータス確認
gtr status                       # DB の統計、残り API 呼び出し数
```

### 4.2 出力 Markdown フォーマット

```markdown
---
week: "2025-W03"
period: "2025-01-13 〜 2025-01-19"
generated_at: "2025-01-19T18:00:00+09:00"
model: "gemini-2.5-flash"
total_repos: 50
---

# GitHub Trending 週次レポート — 2025-W03

## 今週のハイライト

- ポイント1: 〇〇が急上昇。背景として△△がある
- ポイント2: ...
- ポイント3: ...

## 言語別ランキング

| 順位 | 言語 | リポジトリ数 | 割合 |
|------|------|------------|------|
| 1 | Python | 12 | 24% |
| 2 | TypeScript | 9 | 18% |
| 3 | Rust | 7 | 14% |

## カテゴリ別分析

### AI / 機械学習

この週は AI エージェントフレームワーク関連のリポジトリが多数 Trending 入り。...

**注目リポジトリ**
| リポジトリ | スター増加 | 概要 |
|-----------|-----------|------|
| owner/repo | +1,234 | 概要説明 |

### Web 開発

...

### DevOps / インフラ

...

## 新登場リポジトリ

先週の Trending には登場せず、今週新たに Trending 入りしたリポジトリ:

| リポジトリ | 言語 | スター増加 | 概要 |
|-----------|------|-----------|------|
| owner/repo | Python | +567 | ... |

## 先週との比較

先週（2025-W02）と比較して...

---
*Generated by gh-trend-reporter*
```

### 4.3 スクレイピング（scraper.py）

**対象**: `https://github.com/trending` + `https://github.com/trending?since=weekly`

**抽出する情報**（各リポジトリ行から）:
- リポジトリ名（owner/name）
- 説明文
- プログラミング言語
- 総スター数
- 期間内スター増加数
- フォーク数

**実装方針**:
- httpx で HTML 取得
- BeautifulSoup4 で `article.Box-row` 要素を解析
- 言語フィルタ: `?spoken_language_code=&language={lang}&since={period}`

**エラーハンドリング**:
- GitHub が Trending ページを空で返す場合がある → 空リスト警告
- レート制限（429）→ リトライ（最大3回、バックオフ）
- HTML 構造変更 → パース失敗を検出し、ユーザーに通知

### 4.4 GitHub REST API（github_api.py）

**認証**: GITHUB_TOKEN 環境変数（Personal Access Token）。なくても動くが、レート制限が 60 req/h に低下。

**使用するエンドポイント**:
- `GET /repos/{owner}/{repo}` — リポジトリ詳細
- `GET /repos/{owner}/{repo}/readme` — README 取得（Base64 → デコード → 冒頭500文字）
- `GET /rate_limit` — レート制限確認

**キャッシュ**:
- repo_details テーブルに保存し、24時間以内なら DB から返す
- README は冒頭500文字のみ保存（トークン節約）

### 4.5 データベース（database.py）

SQLite スキーマ:

```sql
CREATE TABLE IF NOT EXISTS trending_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    language TEXT,
    stars INTEGER,
    stars_since INTEGER,
    forks INTEGER,
    since TEXT NOT NULL,            -- "daily" | "weekly"
    collected_at DATE NOT NULL,
    UNIQUE(owner, name, since, collected_at)
);

CREATE TABLE IF NOT EXISTS repo_details (
    full_name TEXT PRIMARY KEY,      -- "owner/name"
    topics TEXT,                      -- JSON array
    readme_excerpt TEXT,
    license TEXT,
    open_issues INTEGER,
    open_prs INTEGER,
    last_pushed TEXT,
    created_at TEXT,
    homepage TEXT,
    fetched_at TEXT NOT NULL          -- キャッシュ有効期限判定用
);

CREATE TABLE IF NOT EXISTS weekly_analyses (
    week_label TEXT PRIMARY KEY,      -- "2025-W03"
    analysis_json TEXT NOT NULL,      -- WeeklyAnalysis の JSON
    generated_at TEXT NOT NULL
);
```

### 4.6 エージェント（agent.py）

AGENT_SYSTEM_PROMPT:

```
あなたは GitHub の技術トレンドを分析するエキスパートです。

Function Calling を使って必要なデータを取得し、今週の GitHub Trending を分析してください。

## あなたが使えるツール
- get_trending_repos: 今週の Trending リポジトリ一覧を取得
- get_repo_detail: 特定リポジトリの詳細（トピック、README等）を取得
- get_previous_week_trending: 前週のデータを取得（比較用）
- classify_repos: リポジトリ群をカテゴリに分類

## 分析手順
1. まず get_trending_repos で今週の daily と weekly のデータを取得
2. 注目リポジトリ（スター増加が多いもの）を数個選び、get_repo_detail で詳細を確認
3. get_previous_week_trending で前週データを取得し、新登場リポジトリを特定
4. classify_repos でカテゴリ分類を実行
5. 分析結果を以下の JSON 形式で出力

## 出力形式（JSON）
{
  "top_languages": [{"language": "Python", "count": 12, "percentage": 24.0}],
  "categories": [
    {
      "category": "AI/機械学習",
      "repos": ["owner/repo1", "owner/repo2"],
      "summary_ja": "今週はAIエージェント関連が活発..."
    }
  ],
  "highlights": ["ポイント1", "ポイント2", "ポイント3"],
  "new_entries": ["owner/new-repo1"],
  "rising_repos": [{"name": "owner/repo", "stars_since": 1234, "reason": "理由"}],
  "week_over_week": "先週と比べて..."
}

## ルール
- 日本語で分析する
- カテゴリは5〜8個程度（AI/ML, Web開発, DevOps, セキュリティ, 言語/ツール, データ, モバイル, その他）
- highlights は技術的に興味深い動向に絞る（3〜5個）
- 分析が完了したら JSON のみを出力する
```

### 4.7 レート制限管理

二重のレート制限を管理:

| API | 制限 | 対策 |
|-----|------|------|
| Gemini | 10 RPM / 250 RPD | rate_limiter.py（Project C と同じ設計） |
| GitHub REST API | 5000 req/h（認証時）/ 60 req/h（未認証）| X-RateLimit ヘッダー監視 |
| GitHub Trending（スクレイピング）| 明示的な制限なし | 礼儀的に 2秒インターバル |

### 4.8 Gemini API コスト見積もり

| 処理 | 呼び出し回数/週 | 備考 |
|------|---------------|------|
| エージェントループ（Function Calling） | 5〜8回 | ツール呼び出し + 最終分析 |
| カテゴリ分類 | 1回 | classify_repos 内部 |
| **合計** | **6〜9回/週** | 日次 collect は Gemini 不使用 |

250 RPD の枠に対して週9回は余裕。Project C と共存しても問題なし。

---

## 5. エラーハンドリング

| エラー種別 | 対処 |
|-----------|------|
| Trending ページが空 | 警告ログ出力、DB への保存スキップ |
| Trending ページの HTML 構造変更 | パース失敗を検出 → エラーメッセージ |
| GitHub API 401 | トークン無効 → 未認証モードにフォールバック |
| GitHub API 403（レート制限） | X-RateLimit-Reset まで待機 |
| Gemini API 429 | レート制限待機（自動リトライ） |
| エージェント最大ターン超過 | 途中結果で部分レポートを生成 |
| DB 破損 | バックアップから復旧 or 再作成 |
| collect 未実行で analyze | 「先にcollectを実行してください」メッセージ |

---

## 6. 設定

### 6.1 環境変数

```bash
# .env
GEMINI_API_KEY=your_gemini_api_key
GITHUB_TOKEN=your_github_pat          # Optional（なくても動くがレート制限あり）
```

### 6.2 設定ファイル

```toml
[tool.gh-trend-reporter]
db_path = "./data/trends.db"
reports_dir = "./reports"
collect_interval = 2.0            # スクレイピング間隔（秒）
github_cache_ttl = 86400          # repo_details キャッシュ有効期限（秒）
agent_max_turns = 10
```

---

## 7. 実装の優先順位

| Phase | 範囲 | 目安 |
|-------|------|------|
| Phase 1（Day 1-2） | scraper + github_api + database + models | データ収集が動く |
| Phase 2（Day 3-4） | agent（Function Calling エージェントループ）| 分析が動く |
| Phase 3（Day 5） | reporter + CLI 全コマンド | レポート生成完成 |
| Phase 4（Day 6-7） | テスト・README・CI | 公開品質に仕上げ |

---

## 8. 将来の拡張

- **スケジューラ**: cron / GitHub Actions で日次 collect を自動化
- **Slack / Discord 通知**: レポート生成後に自動投稿
- **Project C 連携**: Trending リポジトリのブログ記事を自動翻訳・要約
- **ダッシュボード**: Streamlit でトレンド可視化
- **言語別深掘り**: 特定言語（Python, Rust 等）に絞った詳細分析
