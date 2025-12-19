# wf-pr

リモートのPull Requestをレビューし、マージ判断・テスト・マージを行う。

**注意**: これは `/wf-dev` とは独立したワークフローです。

## 関連ルール
- コード実行時: @.cursor/rules/code-execution.mdc
- テスト関連: @.cursor/rules/test-strategy.mdc
- git commit: @.cursor/rules/commit-message-format.mdc

## ワークフロー概要

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
└─────────────────────────────────────────────────────────────┘
```

## 1. PR取得

### 1.1. リモート情報の取得とPR候補の列挙

```bash
# リモートの最新情報を取得
git fetch origin

# PRブランチ一覧を確認（リモートブランチ）
git branch -r | grep -E "(pr|PR|pull|merge|claude|feature)"
```

### 1.2. PR順序付け（技術的最適化）

PRをレビューする順序を以下の優先順位で決定する：

#### 優先順位1: 変更量（小→大）
- **理由**: 小さな変更からレビューすることで、コンフリクトリスクを低減
- **判断方法**: `git diff main..<branch> --stat` で変更ファイル数・差分行数を確認
- **優先**: 変更ファイル数が少ないPRから

#### 優先順位2: コミット日時（古→新）
- **理由**: 古いPRは先にマージすべき（依存関係の観点）
- **判断方法**: `git log origin/main..<branch> --format="%ci %s" | head -1` で最初のコミット日時を確認
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
get_pr_by_changes() {
    for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|feature)" | grep -v "HEAD"); do
        # mainとの差分がないブランチはスキップ
        if ! git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
            continue
        fi
        
        # 変更ファイル数と差分行数を取得
        stat=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1)
        if [ -z "$stat" ]; then
            continue
        fi
        
        # 変更行数を抽出（追加+削除）
        changes=$(echo "$stat" | awk '{print $4+$6}' | sed 's/[^0-9]//g')
        if [ -z "$changes" ] || [ "$changes" = "0" ]; then
            changes=0
        fi
        
        # コミット日時を取得（ISO形式）
        date=$(git log origin/main..$branch --format="%ci" 2>/dev/null | tail -1)
        if [ -z "$date" ]; then
            date="9999-12-31 00:00:00 +0000"
        fi
        
        # コミットメッセージのプレフィックスを取得
        prefix=$(git log origin/main..$branch --format="%s" 2>/dev/null | head -1 | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
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
for branch in $(git branch -r | grep -E "(pr|PR|pull|merge|claude|feature)" | grep -v "HEAD"); do
    if git log origin/main..$branch --oneline 2>/dev/null | head -1 > /dev/null; then
        changes=$(git diff origin/main..$branch --stat 2>/dev/null | tail -1 | awk '{print $4+$6}' | sed 's/[^0-9]//g')
        echo "${changes:-0} $branch"
    fi
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
2. **各PRの変更量を確認**: `git diff origin/main..<branch> --stat` で変更ファイル数・行数を確認
3. **コミット日時を確認**: `git log origin/main..<branch> --format="%ci" | tail -1` で最初のコミット日時を確認
4. **変更内容の種類を確認**: `git log origin/main..<branch> --format="%s" | head -1` でコミットメッセージのプレフィックスを確認
5. **優先順位でソート**: 変更量（小→大）→ コミット日時（古→新）→ 変更種類の順でソート
6. **順番にレビュー**: ソートされた順序でPRをレビュー

**注意**: 
- mainとの差分がないブランチはスキップ
- 既にマージ済みのブランチは自動的に除外される（`git log origin/main..<branch>` が空）

## 2. コードレビュー

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

## 4. 回帰テスト

`/regression-test` コマンドを実行。全テストがパスすることを確認。

## 5. マージ判断

### マージ可能条件
- [ ] コードレビューで重大な問題がない
- [ ] lint/型エラーがない（`/quality-check` パス）
- [ ] 全テストがパス（`/regression-test` パス）
- [ ] 仕様書との整合性が取れている

### 判断結果の提示

```
## マージ判断

### 結論: ✅ マージ可能 / ❌ 修正必要

### 理由
- 変更内容が仕様に準拠している
- テストが全てパス
- コード品質に問題なし

### 指摘事項（ある場合）
1. xxx について修正が必要
2. yyy の追加を推奨
```

## 6. マージ実行

ユーザー承認後にのみ実行。`/merge-complete` と同様の手順。

```bash
git checkout main
git merge --no-edit <pr-branch>
```

**注意**: `--no-edit` オプションで対話を避ける。

## 出力

- PR概要（ブランチ名、変更ファイル、差分行数）
- コードレビュー結果
- 品質確認結果（lint/型）
- テスト結果サマリ
- マージ判断（理由付き）
- マージ結果（実行した場合）
