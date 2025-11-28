# lancet-dev

@requirements.md の仕様に沿ってLancetというプロダクトを開発中である。
@IMPLEMENTATION_PLAN.md を見て、コードベースと照合しつつ現状を把握せよ。
タスクの設計時に、後述する関連ルールを読み込み、それらを遵守できる実行計画をかけ。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc
- テスト関連タスク: @.cursor/rules/test.mdc
- リファクタ関連タスク: @.cursor/rules/refactoring.mdc
- git commit: @.cursor/rules/git-commit.mdc

## タスク選定
1. 優先度（🔴高 > 🟡中 > 🟢低）と依存関係を考慮して**1つ**のタスクを選定
2. 選定理由とともにユーザーに確認し、承認を得てから着手
3. 🔴タスクの場合は影響範囲・リスクを先に提示

## 作業フロー
1. ブランチ作成: `feature/phase-{N}-{M}-{short-description}`
2. 実装 → テスト → 品質確認 → 回帰確認
3. コミット（@git-commit.mdc 準拠）→ mainマージ → チェックアウト

## 完了条件
- [ ] 実装コードが完成
- [ ] テストコードが完成
- [ ] テストコードが §7.1 の品質基準を満たす（独立ステップで判定）
- [ ] 該当テストが全パス
- [ ] 全テスト実行で回帰なし（`podman exec lancet pytest tests/ --tb=no -q`）
- [ ] 実装計画書の進捗を更新
- [ ] mainにマージ完了（作業ブランチは削除不要）

## 完了報告
- 変更ファイル一覧
- テスト結果サマリ
- 実装計画書の更新差分

## 中断時
- 現時点の進捗を「🔄」で実装計画書に記録
- 未完了項目を明示してコミット

## scripts/ の使い方

### quick_test.sh（AIフレンドリーなテスト実行）
```bash
./scripts/quick_test.sh run [target]  # テスト開始（デフォルト: tests/）
./scripts/quick_test.sh check         # 完了確認（DONE/RUNNING）
./scripts/quick_test.sh get           # 結果取得（最後の20行）
./scripts/quick_test.sh kill          # pytestプロセス強制終了
```

### dev.sh（開発環境管理）
```bash
./scripts/dev.sh up       # コンテナ起動
./scripts/dev.sh down     # コンテナ停止
./scripts/dev.sh shell    # 開発シェルに入る
./scripts/dev.sh logs     # ログ表示
./scripts/dev.sh status   # コンテナ状態確認
```

### start-chrome.sh（E2Eテスト用Chrome起動）
```bash
./scripts/start-chrome.sh [port] [profile]  # デフォルト: 9222, Profile-Research
```
WSL/Windows/Linuxで動作。Playwright CDPで接続:
`chromium.connect_over_cdp('http://localhost:9222')`

