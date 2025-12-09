# scripts-help

開発用スクリプトの使い方リファレンス。

## test.sh（テスト実行）
```bash
./scripts/test.sh run [target]  # テスト開始（デフォルト: tests/）
./scripts/test.sh check         # 完了確認（DONE/RUNNING）
./scripts/test.sh get           # 結果取得（最後の20行）
./scripts/test.sh kill          # pytestプロセス強制終了
```

## dev.sh（開発環境管理）
```bash
./scripts/dev.sh up       # コンテナ起動
./scripts/dev.sh down     # コンテナ停止
./scripts/dev.sh shell    # 開発シェルに入る
./scripts/dev.sh logs     # ログ表示（最新50行、ハングしない）
./scripts/dev.sh logs -f  # ログをフォロー（Ctrl+Cで終了）
./scripts/dev.sh status   # コンテナ状態確認
```

## chrome.sh（Chrome管理）
```bash
./scripts/chrome.sh check   # 接続可能か確認
./scripts/chrome.sh start   # Chrome起動（独立プロファイル）
./scripts/chrome.sh stop    # Chrome停止
./scripts/chrome.sh setup   # 初回セットアップ手順表示
```

既存のChromeセッションに影響せず、専用プロファイル`LancetChrome`で起動。
Playwright CDPで接続（出力されるURLを使用）

