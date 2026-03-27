#!/bin/bash
set -e

PROJECT_NAME="gh-trend-reporter"
COMMIT_INSTRUCTION='

## Git コミット
作業が論理的なまとまりごとに完了したら、都度 git add と git commit を実行してください。
コミットメッセージは Conventional Commits 形式（例: feat:, test:, chore:, docs:）で書くこと。
1つの大きなコミットではなく、機能単位で細かくコミットすること。'

echo "========================================"
echo "  $PROJECT_NAME — Phase 別自動実装"
echo "========================================"
echo ""

if [ ! -d .git ]; then
  git init
  cat > .gitignore << 'GITIGNORE'
specs/
scripts/

__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/

.env
.vscode/
.idea/
.DS_Store
.coverage
htmlcov/
.pytest_cache/

data/*.db
GITIGNORE
  git add .gitignore
  git commit -m "chore: initial commit with .gitignore"
fi

# Phase 1
echo "🚀 Phase 1: スクレイパー + GitHub API + DB"
echo "-------------------------------------------"

claude -p --dangerously-skip-permissions "specs/SPEC.md と specs/TEST_SPEC.md を読んでから実行してください。

## タスク
gh-trend-reporter の Python CLI プロジェクトを新規作成し、GitHub Trending のデータ収集基盤を実装。

## 実装範囲
1. uv でスキャフォールド（pyproject.toml は specs/SPEC.md セクション2）
2. src/gh_trend_reporter/models.py（specs/SPEC.md セクション 3.5）
3. src/gh_trend_reporter/config.py（specs/SPEC.md セクション 6）
4. src/gh_trend_reporter/scraper.py（specs/SPEC.md セクション 4.3）
5. src/gh_trend_reporter/github_api.py（specs/SPEC.md セクション 4.4）
6. src/gh_trend_reporter/database.py（specs/SPEC.md セクション 4.5）
7. src/gh_trend_reporter/rate_limiter.py
8. tests/test_scraper.py, test_github_api.py, test_database.py（specs/TEST_SPEC.md セクション 2.1-2.3）
9. tests/fixtures/: trending_daily.html, trending_weekly.html, trending_empty.html, repo_detail.json

全テストパス + ruff check + mypy エラーなしまで完了させること。${COMMIT_INSTRUCTION}"

echo "✅ Phase 1 完了"
echo ""

# Phase 2
echo "🚀 Phase 2: エージェント（Function Calling）"
echo "-------------------------------------------"

claude -p --dangerously-skip-permissions "specs/SPEC.md と specs/TEST_SPEC.md を読んでから、Phase 1 のコードベースに追加実装してください。

## 実装範囲
1. src/gh_trend_reporter/agent.py — Gemini Function Calling エージェント（specs/SPEC.md セクション 3.3, 4.6）
2. prompts/agent_system.txt（specs/SPEC.md セクション 4.6）
3. tests/test_agent.py（specs/TEST_SPEC.md セクション 2.4）
4. tests/conftest.py にモック追加（specs/TEST_SPEC.md セクション 4.2）

google-genai の Function Calling を使用。Plan → Act → Observe → Reflect のエージェントループを実装。
全テストパス + ruff check + mypy エラーなしまで完了させること。${COMMIT_INSTRUCTION}"

echo "✅ Phase 2 完了"
echo ""

# Phase 3
echo "🚀 Phase 3: レポーター + CLI 全コマンド"
echo "-------------------------------------------"

claude -p --dangerously-skip-permissions "specs/SPEC.md と specs/TEST_SPEC.md を読んでから、Phase 1-2 のコードベースに追加実装してください。

## 実装範囲
1. src/gh_trend_reporter/reporter.py（specs/SPEC.md セクション 4.2）
2. prompts/report_format.txt
3. src/gh_trend_reporter/cli.py — collect, analyze, report, run, status（specs/SPEC.md セクション 4.1）
4. tests/test_reporter.py, test_cli.py, test_integration.py（specs/TEST_SPEC.md セクション 2.5, 2.6, 3）

非同期コマンドは asyncio.run() でラップ。
全テストパス + ruff check + mypy エラーなしまで完了させること。${COMMIT_INSTRUCTION}"

echo "✅ Phase 3 完了"
echo ""

# Phase 4
echo "🚀 Phase 4: 仕上げ"
echo "-------------------------------------------"

claude -p --dangerously-skip-permissions "specs/SPEC.md を読んでから、プロジェクトを公開品質に仕上げてください。

## 実装範囲
1. README.md（概要、使い方、アーキテクチャ、Function Calling エージェント設計の解説、レート制限二重管理の解説、License: MIT）
2. 全ファイルに docstring（Google style）
3. .github/workflows/ci.yml（Python 3.12, uv, ruff, mypy, pytest --cov 85%+）
4. .env.example, CHANGELOG.md（v0.1.0）
5. ruff + mypy 最終修正

README は面接で見せるクオリティに。特にエージェント設計セクションに深さを持たせること。${COMMIT_INSTRUCTION}"

echo "✅ Phase 4 完了"
echo ""
echo "========================================"
echo "  🎉 $PROJECT_NAME 実装完了!"
echo "  📊 git log --oneline でコミット履歴を確認"
echo "========================================"
