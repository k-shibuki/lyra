# Lancet Test Execution Layers

このドキュメントでは、Lancetプロジェクトのテスト実行階層について説明します。

## 概要

Lancetは**ハイブリッドアーキテクチャ**（Windows + WSL2 + Podmanコンテナ）を前提に設計されており、テストも環境に応じた階層で実行されます。

```
┌─────────────────────────────────────────────────────────────┐
│ L3: E2E Layer (Full Environment)                            │
│   - All tests including E2E                                 │
│   - Requires: Chrome CDP, Ollama, GPU, Display              │
│   - Run: pytest (all) or pytest -m e2e                      │
├─────────────────────────────────────────────────────────────┤
│ L2: Local Layer (Developer WSL2)                            │
│   - Unit + Integration tests                                │
│   - Requires: WSL2, venv, (optional) Podman containers      │
│   - Run: ./scripts/test.sh run                              │
├─────────────────────────────────────────────────────────────┤
│ L1: CI Layer (Cloud Agent / GitHub Actions)                 │
│   - Unit + Integration tests only                           │
│   - No external services required                           │
│   - Run: pytest -m "not e2e and not slow"                   │
└─────────────────────────────────────────────────────────────┘
```

## テストマーカー

| マーカー | 説明 | L1 | L2 | L3 |
|----------|------|:--:|:--:|:--:|
| `unit` | 外部依存なし、高速 | ✅ | ✅ | ✅ |
| `integration` | モック化された外部依存 | ✅ | ✅ | ✅ |
| `e2e` | 実環境必須 | ❌ | ⚠️ | ✅ |
| `slow` | 5秒以上 | ❌ | ⚠️ | ✅ |
| `external` | E2E + 中リスク外部サービス | ❌ | ❌ | ✅ |
| `rate_limited` | E2E + 高リスク外部サービス | ❌ | ❌ | ✅ |
| `manual` | 人間の介入必要 | ❌ | ❌ | ✅ |

## クラウドエージェント環境

以下の環境が自動検出されます：

| 環境 | 検出方法 |
|------|----------|
| Cursor Cloud Agent | `CURSOR_CLOUD_AGENT`, `CURSOR_SESSION_ID`, `CURSOR_BACKGROUND` |
| Claude Code | `CLAUDE_CODE` 環境変数 |
| GitHub Actions | `GITHUB_ACTIONS=true` |
| GitLab CI | `GITLAB_CI` 環境変数 |
| Generic CI | `CI=true` |
| Headless | DISPLAYなし（WSL以外） |

### クラウドエージェント環境での動作

1. **E2Eテストは自動スキップ**: Chrome CDP、Ollama等の外部サービスが利用できないため
2. **Slowテストは自動スキップ**: 実行時間制限のため
3. **Unit/Integrationテストのみ実行**: すべてモック化されており、外部依存なし

## テスト実行方法

### L1: Cloud Agent / CI

```bash
# 自動的に適切なテストが選択される
./scripts/test.sh run

# または明示的に
pytest -m "not e2e and not slow"
```

### L2: ローカル開発

```bash
# デフォルト（unit + integration）
./scripts/test.sh run

# 特定のテストファイル
./scripts/test.sh run tests/test_search.py

# E2Eを含める（Podmanコンテナが必要）
LANCET_TEST_LAYER=e2e ./scripts/test.sh run
```

### L3: フル環境

```bash
# すべてのテスト
LANCET_TEST_LAYER=all ./scripts/test.sh run

# E2Eのみ
pytest -m e2e

# 特定のリスクレベル
pytest -m "e2e and external"
pytest -m "e2e and rate_limited"
```

## 環境情報の確認

```bash
# 現在の環境検出結果を確認
./scripts/test.sh env
```

出力例：
```
=== Lancet Test Environment ===

Environment Detection:
  OS Type: wsl
  In Container: false
  Container Name: N/A
  Is ML Container: false

Cloud Agent Detection:
  Is Cloud Agent: false
  Agent Type: none
  E2E Capable: true

Test Configuration:
  Test Layer: default (unit + integration)
  Markers: not e2e
```

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|----------|
| `LANCET_TEST_LAYER` | テスト層の指定（`e2e`, `all`） | 自動検出 |
| `LANCET_LOCAL` | ローカルモードを強制（クラウド検出を無効化） | - |
| `LANCET_HEADLESS` | ヘッドレスE2Eを有効化 | `false` |

## モック戦略 (§7.1.7)

Unit/Integrationテストでは以下のサービスをモック化：

- **Ollama (LLM)**: `mock_ollama` フィクスチャ
- **Chrome/Playwright**: `mock_browser` フィクスチャ
- **Database**: `memory_database` フィクスチャ（インメモリSQLite）
- **Network**: `aioresponses` / `responses` ライブラリ

## E2E環境の準備

E2Eテストを実行するには以下の準備が必要：

1. **Chromeの起動**
   ```bash
   ./scripts/chrome.sh start
   ```

2. **Podmanコンテナの起動**
   ```bash
   ./scripts/dev.sh up
   ```

3. **環境確認**
   ```bash
   python tests/scripts/verify_environment.py
   ```

## トラブルシューティング

### クラウドエージェントでテストがスキップされる

これは意図された動作です。クラウドエージェント環境では外部サービスが利用できないため、E2Eテストは自動的にスキップされます。

強制的にローカルモードで実行する場合：
```bash
LANCET_LOCAL=1 ./scripts/test.sh run
```

### E2Eテストが失敗する

1. Chrome CDPが接続されているか確認：
   ```bash
   ./scripts/chrome.sh diagnose
   ```

2. Podmanコンテナが稼働しているか確認：
   ```bash
   podman ps
   ```

3. 環境検証スクリプトを実行：
   ```bash
   python tests/scripts/verify_environment.py
   ```

## 関連ドキュメント

- [要件定義書](requirements.md) - §7 受け入れ基準
- [実装計画書](IMPLEMENTATION_PLAN.md) - Phase G テスト基盤
