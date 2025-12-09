# regression-test

全テストを実行し、回帰がないことを確認する。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 実行コマンド
```bash
# 全テスト実行（簡易出力）
podman exec lancet pytest tests/ --tb=no -q

# または scripts/test.sh を使用
./scripts/test.sh run tests/
./scripts/test.sh check  # 完了確認
./scripts/test.sh get    # 結果取得
```

## 完了条件
- [ ] 全テストがパス
- [ ] 新規の失敗テストがない

## 出力
- テスト結果サマリ（passed / failed / skipped）
- 失敗がある場合はその詳細

