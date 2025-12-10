# commit

変更をコミットする。

## 関連ルール
- git commit: @.cursor/rules/commit-message-format.mdc

## コミットメッセージ形式
```
<Prefix>: <サマリ（命令形/簡潔に）>

- 変更内容1（箇条書き）
- 変更内容2（箇条書き）

Refs: #<Issue番号>（任意）
BREAKING CHANGE: <内容>（任意）
```

## Prefix一覧
- feat: 新機能の追加
- fix: バグ修正
- refactor: リファクタリング
- perf: パフォーマンス改善
- test: テスト追加/修正
- docs: ドキュメント更新
- build: ビルド/依存関係の変更
- ci: CI関連の変更
- chore: 雑務
- style: スタイルのみの変更
- revert: 取り消し

## 作業手順（非対話型）
1. `git diff --stat && git diff` で差分を確認
2. 差分に基づいてコミットメッセージを生成（language=en）
3. `git add -A && git commit -m "..."` で一括コミット

**注意**: 対話型エディタを開く `git commit` は使用しない。必ず `-m` オプションでメッセージを渡す。

## 出力
- コミットメッセージ
- コミットハッシュ

