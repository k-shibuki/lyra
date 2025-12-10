# scripts-help

開発用スクリプトの使い方リファレンス。

## dev.sh（開発環境管理）
```bash
./scripts/dev.sh up        # コンテナ起動
./scripts/dev.sh down      # コンテナ停止
./scripts/dev.sh shell     # 開発シェルに入る
./scripts/dev.sh build     # コンテナビルド
./scripts/dev.sh rebuild   # キャッシュなしでリビルド
./scripts/dev.sh logs      # ログ表示（最新50行、ハングしない）
./scripts/dev.sh logs -f   # ログをフォロー（Ctrl+Cで終了）
./scripts/dev.sh status    # コンテナ状態確認
./scripts/dev.sh test      # コンテナ内でテスト実行
./scripts/dev.sh mcp       # MCPサーバー起動
./scripts/dev.sh research  # リサーチクエリ実行
./scripts/dev.sh clean     # コンテナ・イメージ削除
```

## test.sh（テスト実行・AI向け）
```bash
./scripts/test.sh run [target]  # テスト開始（デフォルト: tests/）
./scripts/test.sh check         # 完了確認（DONE/RUNNING）
./scripts/test.sh get           # 結果取得（最後の20行）
./scripts/test.sh kill          # pytestプロセス強制終了
```

バックグラウンド実行→ポーリングで結果確認のパターン。

## chrome.sh（Chrome管理）
```bash
./scripts/chrome.sh check [port]  # 接続可能か確認（デフォルト）
./scripts/chrome.sh start [port]  # Chrome起動（独立プロファイル）
./scripts/chrome.sh stop [port]   # Chrome停止
./scripts/chrome.sh setup [port]  # 初回セットアップ手順表示（WSL用）
```

デフォルトポート: 9222。専用プロファイル`LancetChrome`で起動し、既存セッションに影響なし。

## mcp.sh（MCP Server）
```bash
./scripts/mcp.sh  # MCPサーバー起動（Cursor連携用）
```

コンテナ未起動時は自動で `dev.sh up` を実行。検索ツール使用時はChrome接続が必要で、未接続ならエラーメッセージで `chrome.sh start` を案内。

