# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-27

### Added

- GitHub Trending ページのスクレイピング（daily/weekly、言語フィルタ対応）
- GitHub REST API クライアント（リポジトリ詳細・README 取得、キャッシュ付き）
- SQLite によるデータ永続化（trending_repos, repo_details, weekly_analyses）
- Gemini Function Calling エージェント（Plan → Act → Observe → Reflect ループ）
  - `get_trending_repos`: DB からトレンドデータ取得
  - `get_repo_detail`: リポジトリ詳細取得（キャッシュ優先）
  - `get_previous_week_trending`: 前週データ取得
  - `classify_repos`: ヒューリスティックベースのカテゴリ分類
- Markdown 週次レポート生成（YAML フロントマター付き）
- CLI コマンド: `collect`, `analyze`, `report`, `run`, `status`
- Gemini API レート制限管理（10 RPM / 250 RPD）
- Pydantic v2 による型安全なデータモデル
- pytest によるテストスイート（unit + integration）
