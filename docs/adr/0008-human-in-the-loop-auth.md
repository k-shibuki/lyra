# ADR-0008: Human-in-the-Loop Authentication

## Status
Accepted

## Date
2024-XX-XX（プロジェクト開始時）

## Context

Web自動化において、以下の認証障壁に遭遇する：

| 障壁 | 頻度 | 自動突破 |
|------|:----:|:--------:|
| CAPTCHA/reCAPTCHA | 高 | 困難・違法リスク |
| Cloudflare Turnstile | 高 | 困難 |
| ログイン要求 | 中 | 認証情報が必要 |
| クッキーバナー | 高 | 可能だが脆弱 |
| 年齢確認 | 低 | 可能 |

自動CAPTCHA突破には以下のリスクがある：
- 法的リスク（CFAA等への抵触可能性）
- サービス利用規約違反
- 検出・ブロックの高速化
- 高コスト（商用CAPTCHA解決サービス）

また、ADR-0002（Zero OpEx）の制約により、有償のCAPTCHA解決サービスは使用できない。

## Decision

**認証は人手介入を前提とし、認証待ちキューでバッチ処理可能にする。**

### 設計原則

| 原則 | 詳細 |
|------|------|
| 認証突破しない | CAPTCHAの自動解決を試みない |
| 並行処理 | 認証待ち中も認証不要ソースの探索を継続 |
| バッチ処理 | ユーザーの都合で複数の認証をまとめて処理可能 |
| 明示スキップ | ユーザーが`resolve_auth(skip=true)`で明示的にスキップ可能 |

### 認証待ちキューのフロー

```
1. URL取得時にCloudflare検出
   └─ 認証待ちキューに追加（ドメイン、URL、認証タイプ記録）

2. 探索は継続（認証不要ソースを優先処理）

3. ユーザーの都合で:
   a) get_auth_queue() で認証待ち一覧を取得
   b) ブラウザで手動認証実行
   c) resolve_auth(domain, success=true) で完了報告

4. 認証成功:
   - 当該ドメインの保留URLを再取得
   - セッションを再利用

5. 認証スキップ:
   - resolve_auth(domain, skip=true)
   - 当該ドメインのURLは取得しない
```

### MCPツール

#### get_auth_queue

```json
{
  "group_by": "domain",
  "groups": {
    "arxiv.org": [
      {
        "id": "iq_abc123",
        "url": "https://arxiv.org/pdf/...",
        "auth_type": "cloudflare",
        "priority": "high",
        "created_at": "2025-12-21T10:00:00Z"
      }
    ]
  },
  "total_pending": 5
}
```

#### resolve_auth

```json
// 成功報告
{
  "target": "domain",
  "domain": "arxiv.org",
  "action": "complete",
  "success": true
}

// スキップ
{
  "target": "domain",
  "domain": "arxiv.org",
  "action": "skip"
}
```

### 優先度付与

| 優先度 | 条件 |
|--------|------|
| high | 一次資料（政府、学術）へのアクセス |
| normal | 一般ソース |
| low | 重複・低優先度ソース |

MCPクライアントは優先度を見て、高優先度の認証を先に解決するようユーザーに促せる。

### 自動リトライ

認証待ちキューに移行する前に、以下の自動リトライを試行：

1. 回線更新（IP変更）
2. ヘッドレス→ヘッドフル昇格
3. クールダウン適用

3回失敗で認証待ちキューに移行。

## Consequences

### Positive
- **法的安全**: CAPTCHA突破を試みない
- **Zero OpEx維持**: 有償サービス不使用
- **ユーザー制御**: いつ認証するかをユーザーが決定
- **効率的**: 認証待ち中も他のソース探索を継続

### Negative
- **ユーザー負担**: 認証作業が必要
- **遅延**: 認証待ちソースは後回し
- **一部ソース非取得**: ユーザーがスキップした場合

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| 商用CAPTCHA解決サービス | 全自動 | Zero OpEx違反、法的リスク | 却下 |
| ブラウザ拡張連携 | 半自動 | 追加インストール必要、複雑 | 将来検討 |
| 認証必須ソースを除外 | シンプル | 重要ソース（arxiv等）を失う | 却下 |

## References
- `docs/archive/REQUIREMENTS.md` §3.6（アーカイブ）
- `src/mcp/server.py` - get_auth_queue, resolve_auth実装
- `src/crawler/` - 認証検出・セッション管理
