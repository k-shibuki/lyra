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

### 1. 現在の状態確認

```bash
# 現在のブランチを確認
git branch --show-current

# 未コミットの変更を確認
git status --short

# 変更がない場合は終了
if [ -z "$(git status --porcelain)" ]; then
    echo "No changes to commit"
    exit 0
fi
```

### 2. 差分確認

```bash
# 変更ファイル一覧と差分を確認
git diff --stat
git diff
```

### 3. コミットメッセージ生成

差分に基づいてコミットメッセージを生成（language=en）。

**注意**:
- 変更内容を正確に反映したメッセージを作成
- Prefixは変更の種類に応じて適切に選択
- 複数の変更がある場合は箇条書きで列挙

### 4. コミット実行

```bash
# 全変更をステージングしてコミット
git add -A
git commit -m "<コミットメッセージ>"
```

**注意**:
- 対話型エディタを開く `git commit` は使用しない。必ず `-m` オプションでメッセージを渡す。
- gitコマンドは必ず非対話型オプションを使用すること（`--no-pager` など）。対話待ちになるとタイムアウトする。

## エラーハンドリング

- **変更がない場合**: エラーではなく、メッセージを出力して正常終了
- **コミット失敗時**: エラーメッセージを出力して終了
- **コンフリクト時**: コンフリクト解決が必要であることを明示

## 出力
- 現在のブランチ名
- 変更ファイル一覧（`git diff --stat`）
- コミットメッセージ
- コミットハッシュ
- コミット後の状態（`git log -1 --oneline`）

