# gh-trend-reporter

GitHub Trending リポジトリを自動収集し、LLM の Function Calling で技術トレンドを分析・分類して、日本語の週次レポートを Markdown で出力する CLI ツール。
Gemini API と Ollama（ローカル LLM）の両方に対応。

[![CI](https://github.com/ryo-manba/gh-trend-reporter/actions/workflows/ci.yml/badge.svg)](https://github.com/ryo-manba/gh-trend-reporter/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│                    CLI (Click)                      │
│   collect ──→ analyze ──→ report                    │
└────┬────────────┬───────────┬───────────────────────┘
     │            │           │
     ▼            ▼           ▼
┌─────────┐ ┌──────────────────────┐ ┌────────────────┐
│ Scraper │ │  Analysis Agent      │ │  Report Gen    │
│ (httpx  │ │  (Function Calling)  │ │  (Markdown)    │
│  + BS4) │ │  Plan→Act→Observe    │ └───────┬────────┘
└────┬────┘ │       →Reflect       │         │
     │      └──┬───────────────────┘         │
     ▼         ▼                             ▼
┌────────────────────────┐      ┌────────────────────┐
│    SQLite Database     │      │ reports/2026-W14   │
│  trending │ details    │      │   -qwen2.5-14b.md  │
│  analyses              │      └────────────────────┘
└────────────────────────┘
```

- **Scraper** — GitHub Trending ページを httpx + BeautifulSoup4 でスクレイピング
- **Analysis Agent** — LLM が Function Calling で必要なデータを自律的に取得・分析
- **Report Generator** — 分析結果を Markdown レポートとして出力

## セットアップ

```bash
git clone https://github.com/ryo-manba/gh-trend-reporter.git
cd gh-trend-reporter
uv sync

cp .env.example .env
# .env の GEMINI_API_KEY を設定
```

## 使い方

```bash
# 一括実行（収集 → 分析 → レポート生成）
uv run gtr run

# 個別実行
uv run gtr collect                    # Trending データを収集
uv run gtr collect --language python  # 言語フィルタ
uv run gtr analyze                    # トレンド分析
uv run gtr analyze --week 2026-W14   # 特定週を分析
uv run gtr report                    # Markdown レポート生成
uv run gtr status                    # DB 統計
```

## LLM プロバイダー

### Gemini（デフォルト）

```bash
GEMINI_API_KEY=your_key
```

### Ollama（ローカル LLM）

```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:14b
```

Ollama を使う場合は事前にモデルを pull してください:

```bash
ollama pull qwen2.5:14b
```

## 技術スタック

| 技術 | 用途 |
|------|------|
| Python 3.12+ | async/await、型ヒント |
| Gemini 2.5 Flash | Function Calling エージェント |
| Ollama | ローカル LLM（OpenAI 互換） |
| httpx + BeautifulSoup4 | スクレイピング・HTTP |
| Click | CLI フレームワーク |
| SQLite | データ永続化・キャッシュ |
| Pydantic v2 | 型安全なデータモデル |

## ファイル構成

```
src/gh_trend_reporter/
├── agent.py         # Function Calling エージェントループ
├── cli.py           # Click CLI エントリーポイント
├── config.py        # 環境変数ベースの設定管理
├── database.py      # SQLite CRUD・キャッシュ
├── github_api.py    # GitHub REST API クライアント
├── models.py        # Pydantic データモデル
├── rate_limiter.py  # Gemini レート制限管理
├── reporter.py      # Markdown レポート生成
└── scraper.py       # GitHub Trending スクレイパー
prompts/
├── agent_system.txt # エージェント用システムプロンプト
└── report_format.txt
```

## テスト

```bash
uv run pytest
uv run pytest --cov=gh_trend_reporter --cov-report=term-missing
uv run ruff check src/ tests/
uv run mypy src/
```

## License

MIT
