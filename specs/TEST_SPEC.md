# gh-trend-reporter — テスト仕様書

## 1. テスト戦略

| レベル | 対象 | 実行頻度 |
|-------|------|---------|
| Unit | 各モジュールの関数単位 | コミットごと |
| Integration | collect → DB → analyze → report の全体フロー | PR ごと |
| Agent テスト | Function Calling のエージェントループ | PR ごと（モック） |

- **外部 API は全てモック化**（Unit テスト）: GitHub API, Gemini API, Trending ページ
- **SQLite はインメモリ DB を使用**: テスト間の副作用なし
- **Agent テストは Function Call のシーケンスを検証**: 正しい順序でツールが呼ばれるか

---

## 2. Unit テスト

### 2.1 scraper.py

```python
# tests/test_scraper.py

class TestTrendingScraper:

    # --- 正常系 ---

    async def test_scrape_daily_trending(self):
        """daily Trending ページから正しくリポジトリを抽出"""
        # fixtures/trending_daily.html を使用
        # Assert: len(repos) > 0, 各 repo に owner, name, stars が存在

    async def test_scrape_weekly_trending(self):
        """weekly Trending ページから正しくリポジトリを抽出"""

    async def test_extract_repo_name(self):
        """owner/name 形式でリポジトリ名を抽出"""
        # Assert: repo.owner == "google", repo.name == "gemma"

    async def test_extract_stars_since(self):
        """期間内スター増加数を正しく抽出"""
        # "1,234 stars today" → stars_since == 1234

    async def test_extract_language(self):
        """プログラミング言語を正しく抽出"""

    async def test_extract_description(self):
        """説明文を正しく抽出（None の場合もあり）"""

    async def test_language_filter(self):
        """言語フィルタ付き URL が正しく構築される"""
        # language="python" → URL に "&language=python" が含まれる

    # --- 異常系 ---

    async def test_empty_trending_page(self):
        """空の Trending ページ → 空リスト + 警告"""

    async def test_html_structure_change(self):
        """予期しない HTML 構造 → ScraperError"""

    async def test_network_timeout(self):
        """タイムアウト → リトライ"""

    async def test_rate_limited(self):
        """429 → リトライ（バックオフ）"""
```

### 2.2 github_api.py

```python
# tests/test_github_api.py

class TestGitHubAPI:

    # --- 正常系 ---

    async def test_get_repo_detail(self):
        """リポジトリ詳細を正しく取得"""
        # Mock: GET /repos/owner/repo → fixtures/repo_detail.json
        # Assert: RepoDetail の全フィールド

    async def test_get_readme_excerpt(self):
        """README 冒頭500文字を取得"""
        # Mock: GET /repos/owner/repo/readme → Base64 encoded content
        # Assert: len(excerpt) <= 500

    async def test_get_rate_limit(self):
        """レート制限情報を取得"""

    async def test_no_token_fallback(self):
        """GITHUB_TOKEN 未設定でも動作する（未認証モード）"""

    # --- キャッシュ ---

    async def test_cache_hit(self):
        """24時間以内のキャッシュデータを返す"""
        # DB に新しいデータあり → API 呼び出しなし

    async def test_cache_miss(self):
        """キャッシュ期限切れ → API から再取得"""

    # --- 異常系 ---

    async def test_repo_not_found(self):
        """存在しないリポジトリ → None を返す"""
        # Mock: 404

    async def test_rate_limit_exceeded(self):
        """レート制限超過 → 待機時間を返す"""

    async def test_readme_not_found(self):
        """README がないリポジトリ → excerpt が空文字"""
```

### 2.3 database.py

```python
# tests/test_database.py

class TestDatabase:

    def test_create_tables(self):
        """テーブルが正しく作成される"""

    def test_insert_trending_repo(self):
        """TrendingRepo を挿入できる"""

    def test_upsert_trending_repo(self):
        """同じ (owner, name, since, date) の重複はスキップ"""

    def test_get_repos_by_date(self):
        """日付指定でリポジトリを取得"""

    def test_get_repos_by_week(self):
        """週指定（week_label）でリポジトリを取得"""
        # 2025-W03 → 2025-01-13 〜 2025-01-19 のデータ

    def test_insert_repo_detail(self):
        """RepoDetail を挿入できる"""

    def test_get_repo_detail_cache(self):
        """キャッシュ有効期限内のデータを返す"""

    def test_get_previous_week_repos(self):
        """前週のリポジトリ一覧を取得"""

    def test_save_weekly_analysis(self):
        """WeeklyAnalysis を保存・読み込みできる"""

    def test_get_new_entries(self):
        """今週登場して前週にはなかったリポジトリを取得"""
        # DB に2週分のデータを投入
        # Assert: 差分が正しい

    def test_empty_database(self):
        """空 DB でクエリしてもエラーにならない"""
```

### 2.4 agent.py

```python
# tests/test_agent.py

class TestAnalysisAgent:

    # --- 正常系 ---

    async def test_agent_calls_get_trending_first(self):
        """エージェントの最初の呼び出しが get_trending_repos である"""
        # Mock: Gemini が Function Call を返す
        # Assert: 最初の fc.name == "get_trending_repos"

    async def test_agent_fetches_repo_details(self):
        """エージェントが注目リポジトリの詳細を取得する"""
        # Mock: Gemini が get_repo_detail を呼ぶ
        # Assert: get_repo_detail が1回以上呼ばれる

    async def test_agent_compares_with_previous_week(self):
        """エージェントが前週データを取得して比較する"""

    async def test_agent_classifies_repos(self):
        """エージェントがカテゴリ分類を実行する"""

    async def test_agent_returns_valid_analysis(self):
        """エージェントの最終出力が WeeklyAnalysis 構造を持つ"""
        # Assert: categories, highlights, new_entries が存在

    async def test_agent_loop_terminates(self):
        """エージェントが最大ターン以内に完了する"""
        # Assert: ターン数 <= 10

    async def test_agent_function_execution(self):
        """各ツール関数が正しいパラメータで実行される"""
        # Mock: DB にテストデータ投入
        # Assert: get_trending_repos が正しいデータを返す

    # --- 異常系 ---

    async def test_agent_max_turns_exceeded(self):
        """最大ターン超過 → AgentMaxTurnsError"""
        # Mock: Gemini が常に Function Call を返し続ける

    async def test_agent_invalid_function_name(self):
        """存在しないツール名 → エラーハンドリング"""

    async def test_agent_invalid_json_output(self):
        """不正な JSON 出力 → リトライ"""

    async def test_agent_partial_data(self):
        """collect 不十分（データ少）→ 部分分析を実行"""
```

### 2.5 reporter.py

```python
# tests/test_reporter.py

class TestReportGenerator:

    def test_render_complete_report(self):
        """完全な WeeklyReport から正しい Markdown を生成"""
        # Assert: frontmatter, ハイライト, 言語ランキング, カテゴリ, 新登場

    def test_frontmatter_format(self):
        """YAML frontmatter が正しいフォーマット"""

    def test_language_ranking_table(self):
        """言語ランキングが Markdown テーブル形式"""

    def test_category_sections(self):
        """カテゴリごとにセクションが生成される"""

    def test_new_entries_table(self):
        """新登場リポジトリが Markdown テーブル形式"""

    def test_output_file_naming(self):
        """出力ファイル名が {year}-W{week}.md 形式"""
        # Assert: "2025-W03.md"

    def test_no_previous_week_data(self):
        """前週データがない場合、比較セクションをスキップ"""
```

### 2.6 CLI（cli.py）

```python
# tests/test_cli.py

class TestCLI:

    def test_collect_command(self):
        """collect コマンドが動作する"""
        # Mock: scraper + DB
        # Assert: exit_code == 0

    def test_analyze_command(self):
        """analyze コマンドが動作する"""
        # Mock: agent + DB

    def test_report_command(self):
        """report コマンドが動作する"""
        # Mock: reporter + DB

    def test_run_command(self):
        """run コマンド（一括実行）が動作する"""

    def test_status_command(self):
        """status コマンドで DB 統計を表示"""

    def test_collect_with_language_filter(self):
        """--language オプションが正しく渡される"""

    def test_analyze_specific_week(self):
        """--week オプションで特定週を指定"""

    def test_no_data_error(self):
        """データなしで analyze → エラーメッセージ"""
```

---

## 3. Integration テスト

```python
# tests/test_integration.py

class TestFullPipeline:

    async def test_collect_to_db(self):
        """scrape → DB 保存 → 読み出しの全体フロー"""
        # Mock: Trending ページ HTML
        # Assert: DB にデータが保存されている

    async def test_collect_analyze_report(self):
        """collect → analyze → report の全体フロー"""
        # Mock: Trending HTML + Gemini API
        # Assert: Markdown レポートが生成される

    async def test_two_weeks_comparison(self):
        """2週分のデータで週間比較が正しく動作"""
        # DB に2週分のデータを投入
        # Assert: new_entries, week_over_week が存在

    async def test_agent_full_loop(self):
        """エージェントが Plan → Act → Observe → Reflect を完遂"""
        # Mock: Gemini の Function Call シーケンス全体
        # Assert: 分析結果が WeeklyAnalysis 構造
```

---

## 4. テスト用 Fixtures

### 4.1 HTML Fixtures

| ファイル | 内容 |
|---------|------|
| trending_daily.html | 25件のリポジトリを含む daily Trending ページ |
| trending_weekly.html | 25件の weekly Trending ページ |
| trending_empty.html | 空の Trending ページ |
| trending_python.html | Python フィルタ適用後の Trending ページ |

### 4.2 API レスポンス Fixtures

```python
# tests/conftest.py

MOCK_REPO_DETAIL = {
    "full_name": "google/gemma",
    "description": "Open weights LLM",
    "topics": ["llm", "ai", "machine-learning"],
    "license": {"spdx_id": "Apache-2.0"},
    "open_issues_count": 42,
    "pushed_at": "2025-01-18T12:00:00Z",
    "created_at": "2024-06-01T00:00:00Z",
    "homepage": "https://ai.google.dev/gemma"
}

MOCK_README_CONTENT = "base64encodedstring..."  # 実際の Base64

MOCK_AGENT_FUNCTION_CALLS = [
    # Turn 1: get_trending_repos(since="daily")
    {"name": "get_trending_repos", "args": {"since": "daily", "limit": 25}},
    # Turn 2: get_trending_repos(since="weekly")
    {"name": "get_trending_repos", "args": {"since": "weekly", "limit": 25}},
    # Turn 3: get_repo_detail for top repo
    {"name": "get_repo_detail", "args": {"owner": "google", "repo": "gemma"}},
    # Turn 4: get_previous_week_trending
    {"name": "get_previous_week_trending", "args": {"weeks_ago": 1}},
    # Turn 5: classify_repos
    {"name": "classify_repos", "args": {"repos": [...]}},
    # Turn 6: 最終分析 JSON 出力（Function Call なし）
]

MOCK_ANALYSIS_OUTPUT = {
    "top_languages": [
        {"language": "Python", "count": 12, "percentage": 24.0},
        {"language": "TypeScript", "count": 9, "percentage": 18.0}
    ],
    "categories": [
        {
            "category": "AI/機械学習",
            "repos": ["google/gemma", "meta/llama"],
            "summary_ja": "LLM 関連が活発"
        }
    ],
    "highlights": ["AI エージェントフレームワークが急増"],
    "new_entries": ["new-org/new-repo"],
    "rising_repos": [{"name": "google/gemma", "stars_since": 1234, "reason": "Gemma 2 リリース"}],
    "week_over_week": "先週と比べて AI 関連が増加"
}
```

---

## 5. 実行方法

```bash
# 全テスト
uv run pytest

# Unit テストのみ
uv run pytest tests/ -k "not integration"

# Agent テストのみ
uv run pytest tests/test_agent.py -v

# カバレッジ付き
uv run pytest --cov=src/gh_trend_reporter --cov-report=html
```

### カバレッジ目標

| モジュール | 目標 |
|-----------|------|
| scraper.py | 90%+ |
| github_api.py | 85%+ |
| database.py | 95%+ |
| agent.py | 80%+（Function Calling モック前提） |
| reporter.py | 95%+ |
| rate_limiter.py | 95%+ |
| cli.py | 80%+ |
| **全体** | **85%+** |
