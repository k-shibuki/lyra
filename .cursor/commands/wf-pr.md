# wf-pr

リモートのPull Requestをレビューし、マージ判断・テスト・マージを行う。

**注意**: これは `/wf-dev` とは独立したワークフローです。

## 重要な注意事項

**PRブランチの検出パターン**:
- 以下のパターンで始まるブランチをPRブランチとして扱います：
  - `pr`, `PR`, `pull`, `merge` - 一般的なPRブランチ
  - `claude` - Claude Codeで作成されたブランチ
  - **`cursor`** - **Cursor Cloud Agentで作成されたブランチ（重要）**
  - `feature` - 機能ブランチ

**見落としを防ぐために**:
- 検出されたブランチ数を確認する
- 各ブランチのマージ状態を表示する
- デバッグ出力を有効にする

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc
- テスト関連: @.cursor/rules/test-strategy.mdc
- git commit: @.cursor/rules/commit-message-format.mdc

## ワークフロー概要

**重要**: まず、ローカルのmainブランチとorigin/mainの差分を確認し、以下の2つのケースを判定する：

- **ケースA**: 未マージのPRがある場合 → 個別にレビュー・マージ
- **ケースB**: 既にローカルのmainにマージ済みだがorigin/mainに未プッシュの場合 → mainブランチ全体を確認してからプッシュ

### ケース判定

```bash
# ローカルのmainブランチとorigin/mainの差分を確認
git log origin/main..main --oneline

# 未マージのPRブランチを確認
# パターン: pr, PR, pull, merge, claude, cursor, feature で始まるブランチ
# 注意: cursor ブランチもPRブランチとして扱う（Cursor Cloud Agentで作成されたブランチ）
echo "=== Checking PR branches ==="
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do
    if git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        echo "✓ $branch: Not merged to origin/main"
    else
        echo "  $branch: Already merged to origin/main (skipped)"
    fi
done
echo "=== Summary ==="
echo "Total PR branches: $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | wc -l)"
echo "Unmerged branches: $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null && echo "$branch"; done | wc -l)"
```

**判定基準**:
- `git log origin/main..main` が空で、未マージのPRブランチがある → **ケースA**
- `git log origin/main..main` にコミットがあり、すべてのPRが既にローカルのmainにマージ済み → **ケースB**

### ケースA: 未マージのPRがある場合

```
┌─────────────────────────────────────────────────────────────┐
│  1. PR取得        リモートからPRブランチを取得               │
│         ↓                                                    │
│  2. コードレビュー 変更内容を確認・問題点を指摘              │
│         ↓                                                    │
│  3. 品質確認      /quality-check を実行                     │
│         ↓                                                    │
│  4. 回帰テスト    /regression-test を実行                   │
│         ↓                                                    │
│  5. マージ判断    マージ可否を判断し、理由を説明             │
│         ↓                                                    │
│  6. マージ実行    承認後、mainにマージ                       │
│         ↓                                                    │
│  7. プッシュ      リモートにプッシュ                         │
└─────────────────────────────────────────────────────────────┘
```

### ケースB: 既にマージ済みのPRをプッシュする場合

```
┌─────────────────────────────────────────────────────────────┐
│  1. 状態確認      ローカルのmainとorigin/mainの差分確認      │
│         ↓                                                    │
│  2. 品質確認      /quality-check を実行（mainブランチ全体）  │
│         ↓                                                    │
│  3. 回帰テスト    /regression-test を実行（mainブランチ全体）│
│         ↓                                                    │
│  4. プッシュ判断  プッシュ可否を判断し、理由を説明           │
│         ↓                                                    │
│  5. プッシュ実行  承認後、origin/mainにプッシュ              │
└─────────────────────────────────────────────────────────────┘
```

**注意**: ケースBでは、既にマージ済みのPRを再度マージする必要はない。ローカルのmainブランチ全体を確認してからプッシュする。

## 1. PR取得（ケースAのみ）

### 1.1. リモート情報の取得とPR候補の列挙

```bash
# リモートの最新情報を取得
git fetch origin

# PRブランチ一覧を確認（リモートブランチ）
# パターン: pr, PR, pull, merge, claude, cursor, feature で始まるブランチ
# 注意: cursor ブランチもPRブランチとして扱う（Cursor Cloud Agentで作成されたブランチ）
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"

# デバッグ: 検出されたブランチ数を確認
echo "Found $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | wc -l) PR candidate branches"
```

### 1.2. PR順序付け（技術的最適化）

PRをレビューする順序を以下の優先順位で決定する：

**重要**: ローカルでマージ済みのPRもチェック対象に含める（`main`ブランチとの差分も確認）

#### 優先順位1: 変更量（小→大）
- **理由**: 小さな変更からレビューすることで、コンフリクトリスクを低減
- **判断方法**: `git diff main..<branch> --stat` で変更ファイル数・差分行数を確認
- **優先**: 変更ファイル数が少ないPRから

#### 優先順位2: コミット日時（古→新）
- **理由**: 古いPRは先にマージすべき（依存関係の観点）
- **判断方法**: `git log main..<branch> --format="%ci %s" | head -1` で最初のコミット日時を確認
- **優先**: 古いコミットから

#### 優先順位3: 変更内容の種類
- **優先順位**: バグ修正 → リファクタリング → 新機能 → ドキュメント
- **判断方法**: コミットメッセージのプレフィックス（`fix:` > `refactor:` > `feat:` > `docs:`）

#### 優先順位4: 依存関係
- **理由**: 他のPRに依存するPRは後回し
- **判断方法**: ブランチ名やコミットメッセージから依存関係を推測
- **例**: `feature/phase-m-get-status` は他の機能に依存する可能性が高い

#### 実装例（推奨スクリプト）

```bash
#!/bin/bash
# PR候補を技術的最適順序でソート

# 1. 変更量でソート（小→大）
# ローカルでマージ済みのPRもチェック対象に含める（mainブランチとの差分も確認）
# パターン: pr, PR, pull, merge, claude, cursor, feature で始まるブランチ
get_pr_by_changes() {
    for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"); do
        # ローカルのmainブランチとの差分を確認（ローカルでマージ済みのPRもチェック）
        # git log main..$branch が空なら、ブランチは既にローカルのmainにマージ済み
        if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            # ローカルでマージ済みの場合、origin/mainとの差分を確認
            if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
                continue  # origin/mainにもマージ済みの場合はスキップ
            fi
            # origin/mainには未マージの場合は、プッシュが必要なPRとして扱う
        fi

        # 追加チェック: merge-baseでマージ済みか確認（origin/mainに対して）
        branch_commit=$(git rev-parse $branch 2>/dev/null)
        origin_main_commit=$(git rev-parse origin/main 2>/dev/null)
        if [ -n "$branch_commit" ] && [ -n "$origin_main_commit" ]; then
            if git merge-base --is-ancestor $branch_commit $origin_main_commit 2>/dev/null; then
                # origin/mainにマージ済みの場合はスキップ
                continue
            fi
        fi

        # 変更ファイル数と差分行数を取得（mainブランチとの差分）
        stat=$(git diff main..$branch --stat 2>/dev/null | tail -1)
        if [ -z "$stat" ]; then
            # mainとの差分がない場合、origin/mainとの差分を確認
            stat=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1)
            if [ -z "$stat" ]; then
                continue
            fi
        fi

        # 変更行数を抽出（追加+削除）
        changes=$(echo "$stat" | awk '{print $4+$6}' | sed 's/[^0-9]//g')
        if [ -z "$changes" ] || [ "$changes" = "0" ]; then
            changes=0
        fi

        # コミット日時を取得（ISO形式、mainブランチとの差分）
        date=$(git log main..$branch --format="%ci" 2>/dev/null | tail -1)
        if [ -z "$date" ]; then
            # mainとの差分がない場合、origin/mainとの差分を確認
            date=$(git log origin/main..$branch --format="%ci" 2>/dev/null | tail -1)
            if [ -z "$date" ]; then
                date="9999-12-31 00:00:00 +0000"
            fi
        fi

        # コミットメッセージのプレフィックスを取得（mainブランチとの差分）
        prefix=$(git log main..$branch --format="%s" 2>/dev/null | head -1 | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
        if [ -z "$prefix" ]; then
            # mainとの差分がない場合、origin/mainとの差分を確認
            prefix=$(git log origin/main..$branch --format="%s" 2>/dev/null | head -1 | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
        fi
        case "$prefix" in
            fix) priority=1 ;;
            refactor) priority=2 ;;
            feat) priority=3 ;;
            docs) priority=4 ;;
            *) priority=5 ;;
        esac

        echo "$changes|$date|$priority|$branch"
    done | sort -t'|' -k1,1n -k2,2 -k3,3n | cut -d'|' -f4
}

# 使用例
get_pr_by_changes
```

#### 簡易版（変更量のみ）

```bash
# PR候補を変更量でソート（最もシンプル）
# ローカルでマージ済みのPRもチェック対象に含める
# パターン: pr, PR, pull, merge, claude, cursor, feature で始まるブランチ
for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD"); do
    # ローカルのmainブランチとの差分を確認（ローカルでマージ済みのPRもチェック）
    if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        # ローカルでマージ済みの場合、origin/mainとの差分を確認
        if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            continue  # origin/mainにもマージ済みの場合はスキップ
        fi
        # origin/mainには未マージの場合は、プッシュが必要なPRとして扱う
    fi

    # 追加チェック: merge-baseでマージ済みか確認（origin/mainに対して）
    branch_commit=$(git rev-parse $branch 2>/dev/null)
    origin_main_commit=$(git rev-parse origin/main 2>/dev/null)
    if [ -n "$branch_commit" ] && [ -n "$origin_main_commit" ]; then
        if git merge-base --is-ancestor $branch_commit $origin_main_commit 2>/dev/null; then
            continue  # origin/mainにマージ済みの場合はスキップ
        fi
    fi

    # 変更量を取得（mainブランチとの差分）
    changes=$(git diff main..$branch --stat 2>/dev/null | tail -1 | awk '{print $4+$6}' | sed 's/[^0-9]//g')
    if [ -z "$changes" ]; then
        # mainとの差分がない場合、origin/mainとの差分を確認
        changes=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1 | awk '{print $4+$6}' | sed 's/[^0-9]//g')
    fi
    echo "${changes:-0} $branch"
done | sort -n | awk '{print $2}'
```

### 1.3. PRブランチのチェックアウト

```bash
# 決定した順序でPRブランチをチェックアウト
git checkout -b <pr-branch> origin/<pr-branch>
```

### 1.4. 順序付けの実行手順

実際のワークフローでは以下の手順で実行：

1. **PR候補の列挙**: `git branch -r` でリモートブランチを確認
   - **重要**: `cursor` ブランチもPRブランチとして扱う（Cursor Cloud Agentで作成されたブランチ）
   - パターン: `(pr|PR|pull|merge|claude|cursor|feature)` で始まるブランチを検出
   - デバッグ出力で検出されたブランチ数を確認
2. **マージ済みブランチの判定**:
   - **ローカルでマージ済みのPRもチェック対象に含める**（`main`ブランチとの差分も確認）
   - `git log main..<branch>` が空の場合、`origin/main`との差分を確認
   - `git log origin/main..<branch>` が空の場合はスキップ（両方にマージ済み）
   - `git merge-base --is-ancestor <branch> origin/main` でorigin/mainにマージ済みか確認
   - **デバッグ出力**: 各ブランチのマージ状態を表示
3. **各PRの変更量を確認**: `git diff main..<branch> --stat` で変更ファイル数・行数を確認（ローカルmainとの差分）
4. **コミット日時を確認**: `git log main..<branch> --format="%ci" | tail -1` で最初のコミット日時を確認
5. **変更内容の種類を確認**: `git log main..<branch> --format="%s" | head -1` でコミットメッセージのプレフィックスを確認
6. **優先順位でソート**: 変更量（小→大）→ コミット日時（古→新）→ 変更種類の順でソート
7. **順番にレビュー**: ソートされた順序でPRをレビュー

**注意**:
- **`cursor` ブランチもPRブランチとして扱う**（Cursor Cloud Agentで作成されたブランチ）
- ローカルでマージ済みでも`origin/main`に未プッシュのPRはレビュー対象に含める
- 両方（`main`と`origin/main`）にマージ済みのブランチは自動的に除外される
  - `git log main..<branch>` と `git log origin/main..<branch>` が両方空の場合
  - `git merge-base --is-ancestor <branch> origin/main` がtrueの場合

## 1B. 既マージPRの状態確認（ケースBのみ）

既にローカルのmainにマージ済みだがorigin/mainに未プッシュの場合：

```bash
# ローカルのmainブランチとorigin/mainの差分を確認
git log origin/main..main --oneline
git diff origin/main..main --stat

# マージ済みのPRブランチを確認
# パターン: pr, PR, pull, merge, claude, cursor, feature で始まるブランチ
git branch -r | grep -E "(pr|PR|pull|merge|claude|cursor|feature)" | grep -v "HEAD" | while read branch; do
    if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        echo "$branch: Already merged to origin/main"
    else
        if ! git log main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            echo "$branch: Merged to local main, but not pushed to origin/main"
        fi
    fi
done
```

**重要**: このケースでは、個別のPRを再度マージする必要はない。ローカルのmainブランチ全体を品質確認・テストしてから、origin/mainにプッシュする。

## 2. コードレビュー（ケースAのみ）

### 確認項目

| カテゴリ | 確認内容 |
|---------|---------|
| **変更概要** | 変更ファイル一覧、差分行数 |
| **コード品質** | 可読性、命名規則、重複排除 |
| **仕様準拠** | `docs/REQUIREMENTS.md` との整合性 |
| **テスト** | テストの有無、カバレッジ |
| **セキュリティ** | 認証・認可、データ検証 |

### 差分確認コマンド

```bash
# mainとの差分を確認
git diff main..HEAD --stat
git diff main..HEAD
```

## 3. 品質確認

`/quality-check` コマンドを実行。lint/型エラーを確認・修正。

**重要**:
- lint/型エラーだけでなく、**警告も必ず解消する**
- `ruff check` で警告が出た場合は `ruff check --fix` で自動修正を試みる
- `git diff --check` でtrailing whitespaceなどの警告を確認
- 警告が残っている場合はマージ/プッシュしない

**ケースA（未マージPR）**: PRブランチで品質確認を実行
**ケースB（既マージPR）**: mainブランチ全体で品質確認を実行

## 4. 回帰テスト

`/regression-test` コマンドを実行。全テストがパスすることを確認。

**ケースA（未マージPR）**: PRブランチでテストを実行
**ケースB（既マージPR）**: mainブランチ全体でテストを実行

### 実行例

```bash
# テスト開始
./scripts/test.sh run tests/

# 完了までポーリング（最大5分、5秒間隔）
for i in {1..60}; do
    sleep 5
    status=$(./scripts/test.sh check 2>&1)
    echo "[$i] $status"
    # 完了判定: "DONE"またはテスト結果キーワード（passed/failed/skipped）が含まれる
    if echo "$status" | grep -qE "(DONE|passed|failed|skipped|deselected)"; then
        break
    fi
done

# 結果取得
./scripts/test.sh get
```

**注意**: `check`コマンドは、テスト結果に`passed`/`failed`/`skipped`/`deselected`などのキーワードが含まれていれば自動的に`DONE`を返すため、明示的な`DONE`チェックは不要。

## 5. マージ判断

### マージ可能条件
- [ ] コードレビューで重大な問題がない
- [ ] lint/型エラーがない（`/quality-check` パス）
- [ ] 全テストがパス（`/regression-test` パス）
- [ ] 仕様書との整合性が取れている
- [ ] **警告が全て解消されている**（必須）

### 判断結果の提示

```
## マージ判断

### 結論: ✅ マージ可能 / ❌ 修正必要

### 理由
- 変更内容が仕様に準拠している
- テストが全てパス
- コード品質に問題なし
- **警告が全て解消されている**

### 指摘事項（ある場合）
1. xxx について修正が必要
2. yyy の追加を推奨
3. **警告が残っている場合は必ず解消してからマージ**
```

## 6. マージ実行（ケースAのみ）

ユーザー承認後にのみ実行。`/merge-complete` と同様の手順。

### 6.1. マージ前の確認

**重要**: マージ前に必ず以下を確認・実行する：

1. **警告の解消**: `ruff check` や `mypy` の警告が全て解消されていること
2. **コンフリクトの解決**: マージコンフリクトが発生した場合は、必ず解決してからコミット
3. **trailing whitespaceの解消**: `git diff --check` で警告がないことを確認

```bash
# 警告確認
podman exec lancet ruff check src/ tests/
podman exec lancet mypy src/ tests/

# trailing whitespace確認
git diff --check

# 警告がある場合は自動修正を試みる
podman exec lancet ruff check --fix src/ tests/
```

### 6.2. マージ実行

```bash
git checkout main
git merge --no-edit <pr-branch>
```

**注意**:
- `--no-edit` オプションで対話を避ける
- **警告が残っている場合はマージを実行しない**（必ず解消してからマージ）

### 6.3. リモートへのプッシュ

**重要**: マージ後は必ずリモートにプッシュする

```bash
# マージ後、リモートにプッシュ
git push origin main
```

**理由**:
- リモートが常に最新状態を反映する
- チーム間での同期が取れる
- CI/CDが動作する
- バックアップになる

**注意**:
- プッシュ前に必ずマージが成功していることを確認
- コンフリクトが発生した場合は解決してからプッシュ

## 6B. プッシュ実行（ケースBのみ）

既にローカルのmainにマージ済みのPRをorigin/mainにプッシュする場合。

### 6B.1. プッシュ前の確認

**重要**: プッシュ前に必ず以下を確認・実行する：

1. **警告の解消**: `ruff check` や `mypy` の警告が全て解消されていること
2. **trailing whitespaceの解消**: `git diff --check` で警告がないことを確認
3. **品質確認・テスト完了**: `/quality-check` と `/regression-test` がパスしていること

```bash
# mainブランチにいることを確認
git checkout main

# 警告確認
podman exec lancet ruff check src/ tests/
podman exec lancet mypy src/ tests/

# trailing whitespace確認
git diff origin/main..main --check

# 警告がある場合は自動修正を試みる
podman exec lancet ruff check --fix src/ tests/
```

### 6B.2. プッシュ実行

```bash
# origin/mainにプッシュ
git push origin main
```

**注意**:
- **警告が残っている場合はプッシュを実行しない**（必ず解消してからプッシュ）
- プッシュ前に必ず品質確認・テストが完了していることを確認

## 出力

- PR概要（ブランチ名、変更ファイル、差分行数）
- コードレビュー結果
- 品質確認結果（lint/型）
- テスト結果サマリ
- マージ判断（理由付き）
- マージ結果（実行した場合）

