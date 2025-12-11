# Phase O: ハイブリッド構成リファクタリング - 詳細削除リスト

## 概要

後方互換性を完全に削除し、WSLハイブリッド構成のみをサポートする。旧構成関連コードをすべて削除する。

**削除予定行数**: ~224行

---

## 1. socat関連コード削除（~152行）

### 1.1 `scripts/chrome.sh`

| 関数/セクション | 行番号 | 削除内容 |
|----------------|--------|---------|
| `SOCAT_PID_FILE`定数 | L47 | `SOCAT_PID_FILE="/tmp/lancet-socat.pid"` |
| `check_socat()`関数 | L237-255 | 全体削除（~19行） |
| `start_socat()`関数 | L257-293 | 全体削除（~37行） |
| `stop_socat()`関数 | L295-309 | 全体削除（~15行） |
| `get_status()`内socatチェック | L327-336 | socatステータス表示部分（~10行） |
| `start_chrome_wsl()`内socat起動 | L371-384 | socat起動ロジック（~14行） |
| `stop_chrome()`内socat停止 | L499-502 | socat停止ロジック（~4行） |

**合計**: ~99行

### 1.2 `scripts/common.sh`

| 項目 | 行番号 | 削除内容 |
|------|--------|---------|
| `SOCAT_PORT`定数 | L81 | `export SOCAT_PORT="${LANCET_SCRIPT__SOCAT_PORT:-19222}"` |

**合計**: 1行

### 1.3 Pythonソースコード

| ファイル | 行番号 | 削除内容 |
|---------|--------|
| `src/mcp/errors.py` | L328-336 | `is_podman`パラメータとsocatヒント（~9行） |
| `src/mcp/server.py` | L806-811 | `is_podman`検出コード（~6行） |
| `src/search/browser_search_provider.py` | L201-208 | socatヒント（~8行） |
| `src/crawler/playwright_provider.py` | L157-160 | socatヒント（~4行） |
| `src/crawler/fetcher.py` | L765-768 | socatヒント（~4行） |

**合計**: ~31行

### 1.4 テストコード

| ファイル | 行番号 | 削除内容 |
|---------|--------|---------|
| `tests/test_mcp_errors.py` | L420-433 | `test_podman_environment`テスト（~14行） |

**合計**: ~14行

---

## 2. host-gateway関連削除（~5行）

| ファイル | 行番号 | 削除内容 |
|---------|--------|---------|
| `podman-compose.yml` | L23-24 | `extra_hosts: host.containers.internal`設定（2行） |
| `config/settings.yaml` | L133-135 | `10.255.255.254`コメント（3行） |

**合計**: ~5行

---

## 3. execution_mode分岐削除（~30行）

| ファイル | 行番号 | 削除内容 |
|---------|--------|---------|
| `src/utils/config.py` | L226-232 | `execution_mode`フィールドとコメント（~7行） |
| `src/filter/ollama_provider.py` | L89-95 | execution_mode分岐、常にプロキシURL使用（~7行） |
| `src/ml_client.py` | L31-37 | execution_mode分岐、常にプロキシURL使用（~7行） |
| `.env` | L7-9 | `LANCET_EXECUTION_MODE`設定（3行） |
| `.env` | L24-28 | コンテナモード用コメント（5行） |
| `scripts/mcp.sh` | L130 | `LANCET_EXECUTION_MODE`設定（1行） |

**合計**: ~30行

**変更内容**:
- `OllamaProvider`: `elif settings.general.execution_mode == "wsl":` → 常にプロキシURL使用
- `MLClient`: `if self._settings.general.execution_mode == "wsl":` → 常にプロキシURL使用
- `config.py`: `execution_mode`フィールド削除、`proxy_url`のみ残す

---

## 4. コンテナ検出コード削除（~10行）

| ファイル | 行番号 | 削除内容 |
|---------|--------|---------|
| `src/mcp/server.py` | L806 | `os.path.exists("/.dockerenv")`検出（1行） |
| `src/search/browser_search_provider.py` | L201-203 | コンテナ検出とhint生成（~3行） |
| `src/crawler/playwright_provider.py` | L157-159 | コンテナ検出とhint生成（~3行） |
| `src/crawler/fetcher.py` | L765-767 | コンテナ検出とhint生成（~3行） |

**合計**: ~10行

**変更内容**:
- すべてのコンテナ検出コード（`os.path.exists("/.dockerenv")`、`os.environ.get("container") == "podman"`）を削除
- hint生成ロジックも削除（socat関連のため）

---

## 5. ポート設定簡素化（~10行）

| ファイル | 行番号 | 削除内容 |
|---------|--------|---------|
| `.env` | L19-21 | Chromeポートコメント簡素化（3行） |
| `config/settings.yaml` | L132-135 | ポートオーバーライドコメント削除（4行） |
| `.env.example` | L13 | `LANCET_BROWSER__CHROME_PORT=19222`削除（1行） |
| `.env.example` | L16 | セクション名「CONTAINER NETWORKING (Required for Podman)」を「CONTAINER NETWORKING (Internal services)」に変更（1行） |
| `.env.example` | L47-48 | socatポート設定とコメント削除（2行） |

**変更内容**:
- `.env`: `# In WSL mode, chrome.sh can auto-start Chrome when needed` → `# Chrome CDP connection (WSL2 -> Windows Chrome)`
- `settings.yaml`: WSL2+Podman向けコメント（`10.255.255.254`、`19222`、`socat`）を削除
- `.env.example`: 
  - socat関連設定を削除
  - セクション名を「CONTAINER NETWORKING (Required for Podman)」→「CONTAINER NETWORKING (Internal services)」に変更（WSLハイブリッド構成ではPodman必須ではないため）
  - WSLハイブリッド構成の説明に統一

---

## 6. スクリプト更新（~20行 + 16ファイル）

| ファイル | 行番号 | 変更内容 |
|---------|--------|---------|
| **`config/cursor-mcp.json`** | **全体** | **`podman exec`経由をWSL経由（`bash` + `./scripts/mcp.sh`）に変更** |
| `Dockerfile` | L89 | CMDを`src.mcp.server`から`src.proxy.server`に変更（1行） |
| `scripts/dev.sh` | L145 | 「container networking」コメントを「proxy server」に変更（1行） |
| `scripts/dev.sh` | L55-56 | フォールバック設定のコメント更新（2行） |
| `scripts/mcp.sh` | L130 | `LANCET_EXECUTION_MODE`設定削除（1行） |
| `scripts/test.sh` | 全体 | `podman exec`経由のテスト実行を削除、WSL venv経由に統一（~50行） |
| `tests/scripts/verify_environment.py` | L101-114 | コンテナ検出コードの説明更新（WSL実行時の説明追加、~14行） |
| `tests/scripts/*.py` | Usageコメント | `podman exec lancet python`を`python`（WSL venv経由）に変更（16ファイル） |

**変更内容**:
- **`cursor-mcp.json`**: 最重要。Cursor IDEがMCPサーバーを起動する設定を`podman exec`からWSL経由に変更
  ```json
  {
    "mcpServers": {
      "lancet": {
        "command": "bash",
        "args": ["-c", "cd /home/statuser/lancet && ./scripts/mcp.sh"]
      }
    }
  }
  ```
- `Dockerfile`: CMDを`src.proxy.server`に変更（プロキシサーバーとして動作）
- `dev.sh`: フォールバック設定は残すが、コメントを「WSL venv経由でプロキシに接続」に変更
- `test.sh`: コンテナ内実行を削除し、WSL venvから直接実行する方式に変更
- `mcp.sh`: `LANCET_EXECUTION_MODE`設定削除（常にWSLモード）
- `verify_environment.py`: コンテナ検出は残すが、WSL実行時の説明を追加
- E2Eテストスクリプト: Usageコメントの`podman exec lancet python`を`python`（WSL venv経由）に変更

---

## 7. ドキュメント更新

| ファイル | 変更内容 |
|---------|---------|
| `requirements.md` | §5.3.3「実行モード」→「実行アーキテクチャ」に変更、execution_mode説明削除 |
| `IMPLEMENTATION_PLAN.md` | Phase O.5「移行影響」セクション削除、後方互換性説明削除 |
| `IMPLEMENTATION_PLAN.md` §7 | socat関連説明削除 |
| `.env.example` | コメント更新（WSLハイブリッド構成の説明） |

---

## 実装順序

1. **最高優先度（MCP起動設定）**:
   - **O.3.6: `config/cursor-mcp.json`変更** - Cursor IDEがMCPサーバーを起動する設定をWSL経由に変更（最重要）

2. **高優先度（コード削除）**:
   - O.3.1: socat関連コード削除
   - O.3.2: host-gateway関連削除
   - O.3.3: execution_mode分岐削除
   - O.3.4: コンテナ検出コード削除
   - O.3.6: スクリプト更新（`Dockerfile` CMD変更、`test.sh`のコンテナ実行削除）

3. **中優先度（設定・ドキュメント）**:
   - O.3.5: ポート設定簡素化（`.env.example`含む）
   - O.3.6: E2EテストスクリプトのUsageコメント更新（16ファイル）
   - O.3.7: ドキュメント更新

4. **テスト修正**:
   - `tests/test_mcp_errors.py`: `test_podman_environment`削除
   - `tests/scripts/verify_environment.py`: WSL実行時の説明追加
   - その他テストでexecution_mode依存があれば修正

---

## 検証項目

- [ ] **`config/cursor-mcp.json`がWSL経由（`./scripts/mcp.sh`）に変更されている**（最重要）
- [ ] `Dockerfile`のCMDが`src.proxy.server`に変更されている
- [ ] socat関数が完全に削除されている
- [ ] execution_mode分岐が削除され、常にプロキシURLを使用
- [ ] コンテナ検出コードが削除または更新されている
- [ ] `.env`から`LANCET_EXECUTION_MODE`が削除されている
- [ ] `.env.example`からsocat設定が削除されている
- [ ] `podman-compose.yml`から`extra_hosts`が削除されている
- [ ] `scripts/test.sh`がWSL venv経由で実行される
- [ ] `scripts/mcp.sh`から`LANCET_EXECUTION_MODE`設定が削除されている
- [ ] `scripts/dev.sh`のコメントが更新されている
- [ ] E2EテストスクリプトのUsageコメントがWSL venv経由に更新されている
- [ ] テストがすべてパスする
- [ ] ドキュメントが更新されている

