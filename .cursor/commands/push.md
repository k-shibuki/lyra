# push

mainブランチをリモートにプッシュする。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc

## 前提条件

- `/merge-complete` の後に実行する場合: 品質確認・テストは既に完了しているため、簡略化された確認でOK
- 直接実行する場合: 品質確認・テストを実行してからプッシュ

## 作業手順

### 1. 現在の状態確認

```bash
# 現在のブランチを確認
current_branch=$(git branch --show-current)
echo "Current branch: $current_branch"

# mainブランチに切り替え（必要に応じて）
if [ "$current_branch" != "main" ]; then
    echo "Switching to main branch..."
    git checkout main
fi

# ローカルのmainとorigin/mainの差分を確認
echo "=== Commits to push ==="
git log origin/main..main --oneline

# プッシュするコミットがない場合は終了
if [ -z "$(git log origin/main..main --oneline)" ]; then
    echo "No commits to push"
    exit 0
fi
```

### 2. プッシュ前の確認

**重要**: プッシュ前に必ず以下を確認・実行する：

#### 2.1. 警告の確認と解消

```bash
# 警告確認
podman exec lancet ruff check src/ tests/
podman exec lancet mypy src/ tests/

# 警告がある場合は自動修正を試みる
podman exec lancet ruff check --fix src/ tests/
```

**注意**: **警告が残っている場合はプッシュを実行しない**（必ず解消してからプッシュ）

#### 2.2. trailing whitespaceの確認

```bash
# trailing whitespace確認
git diff origin/main..main --check
```

**注意**: 警告がある場合は修正してからプッシュ

#### 2.3. 品質確認・テスト（必要に応じて）

`/merge-complete` の後に実行する場合は、既に品質確認・テストが完了しているため省略可能。

直接実行する場合は以下を実行：

```bash
# 品質確認
# /quality-check を実行

# 回帰テスト
# /regression-test を実行
```

### 3. プッシュ実行

```bash
# origin/mainにプッシュ
git push origin main
```

**注意**:
- gitコマンドは必ず非対話型オプションを使用すること（`--no-pager` など）。対話待ちになるとタイムアウトする。
- プッシュが失敗した場合は、エラーメッセージを確認して対処

### 4. プッシュ後の確認

```bash
# プッシュ後の状態確認
git log origin/main..main --oneline

# プッシュが成功した場合、このコマンドは何も出力しない
```

## エラーハンドリング

- **プッシュするコミットがない場合**: エラーではなく、メッセージを出力して正常終了
- **警告が残っている場合**: プッシュを実行せず、警告解消を促すメッセージを出力
- **プッシュ失敗時**: エラーメッセージを出力（例: リモートが先行している場合は `git pull` が必要）
- **コンフリクト時**: リモートとのコンフリクト解決が必要であることを明示

## 出力
- 現在のブランチ名
- プッシュするコミット一覧（`git log origin/main..main --oneline`）
- プッシュ前の確認結果（警告、trailing whitespace等）
- プッシュ結果（成功/失敗）
- プッシュ後の状態確認
