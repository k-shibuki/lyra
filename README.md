# Lancet - Local Autonomous Deep Research Agent

**Lancet**は、OSINTデスクトップリサーチを自律的に実行するローカルAIエージェントです。商用APIへの依存を排除し、ローカル環境のリソースのみで稼働します。

## 特徴

- 🔍 **自律的リサーチ**: 問いを分解し、検索クエリを自動生成、再帰的に情報を収集
- 🏠 **完全ローカル**: 商用API不使用、Zero OpEx
- 🔗 **MCP連携**: Cursorと連携し、AIがツールとして直接呼び出し可能
- 📊 **多段階評価**: BM25 → 埋め込み → リランキング → LLM抽出
- 🛡️ **ステルス性**: ブラウザ指紋整合、レート制御、Tor対応
- 📝 **引用管理**: 全ての主張に出典を明記、エビデンスグラフで可視化
- 🐳 **コンテナ化**: Podmanによる完全コンテナ化開発環境

## システム要件

- **OS**: Windows 11 + WSL2 Ubuntu 22.04/24.04
- **RAM**: 64GB (WSL2に32GB割当)
- **GPU**: NVIDIA RTX 4060 Laptop (VRAM 8GB) - オプション
- **コンテナ**: Podman + podman-compose
- **その他**: Chrome (Windows側)

## クイックスタート

### 1. 前提条件のインストール

```bash
# WSL2内で実行
sudo apt update
sudo apt install -y podman podman-compose
```

### 2. 開発環境の起動

```bash
cd /path/to/lancet

# 全サービスを起動 (SearXNG, Tor, Lancet)
./scripts/dev.sh up
```

### 3. 開発シェルに入る

```bash
# インタラクティブな開発シェル
./scripts/dev.sh shell

# シェル内で実行
python -m src.main research --query "AIエージェントの最新動向"
```

### 4. Ollama起動 (ホスト側)

```bash
# WSL2またはWindows側で
ollama serve

# モデルのダウンロード
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
```

### 5. Chrome起動 (Windows側, リモートデバッグ)

```powershell
# PowerShellで実行
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --profile-directory="Profile-Research"
```

## 開発コマンド

```bash
./scripts/dev.sh up        # 全サービス起動
./scripts/dev.sh down      # 全サービス停止
./scripts/dev.sh build     # コンテナビルド
./scripts/dev.sh rebuild   # コンテナ再ビルド (キャッシュなし)
./scripts/dev.sh shell     # 開発シェルに入る
./scripts/dev.sh logs      # ログ表示
./scripts/dev.sh status    # コンテナ状態確認
./scripts/dev.sh clean     # コンテナ・イメージ削除
```

## Cursorとの連携

`config/cursor-mcp.json` を `.cursor/mcp.json` にコピー:

```bash
mkdir -p .cursor
cp config/cursor-mcp.json .cursor/mcp.json
```

MCPサーバーはコンテナ内で動作するため、Cursorからの接続設定が必要です。

## MCPツール一覧

| ツール | 説明 |
|--------|------|
| `search_serp` | 検索エンジンでクエリを実行 |
| `fetch_url` | URLからコンテンツを取得 |
| `extract_content` | HTML/PDFからテキスト抽出 |
| `rank_candidates` | パッセージの関連性ランキング |
| `llm_extract` | LLMで事実・主張を抽出 |
| `nli_judge` | 主張間の立場判定 |
| `notify_user` | ユーザーへの通知 |
| `schedule_job` | ジョブのスケジュール |
| `create_task` | リサーチタスクの作成 |
| `get_task_status` | タスク状態の取得 |
| `generate_report` | レポート生成 |

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                         Cursor                              │
│                    (思考・論理構成・判断)                      │
└─────────────────────────────────┬───────────────────────────┘
                                  │ MCP
┌─────────────────────────────────▼───────────────────────────┐
│                    Podman Containers                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Lancet Container                        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │   │
│  │  │  Search  │ │ Crawler  │ │  Filter  │            │   │
│  │  │ Extractor│ │ Scheduler│ │  Report  │            │   │
│  │  └──────────┘ └──────────┘ └──────────┘            │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌──────────────┐ ┌──────────────┐                        │
│  │   SearXNG    │ │     Tor      │                        │
│  │  Container   │ │  Container   │                        │
│  └──────────────┘ └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
                    │                           │
        ┌───────────▼───────────┐   ┌───────────▼───────────┐
        │   Ollama (Host)       │   │   Chrome (Windows)    │
        └───────────────────────┘   └───────────────────────┘
```

## ディレクトリ構造

```
lancet/
├── src/                  # ソースコード
│   ├── mcp/              # MCPサーバー
│   ├── search/           # 検索エンジン連携
│   ├── crawler/          # クローリング/取得
│   ├── extractor/        # コンテンツ抽出
│   ├── filter/           # フィルタリング/評価
│   ├── report/           # レポート生成
│   ├── scheduler/        # ジョブスケジューラ
│   ├── storage/          # データストレージ
│   └── utils/            # ユーティリティ
├── config/
│   ├── settings.yaml     # メイン設定
│   ├── engines.yaml      # 検索エンジン設定
│   ├── domains.yaml      # ドメインポリシー
│   └── searxng/          # SearXNG設定
├── data/                 # 永続データ (マウント)
├── logs/                 # ログ (マウント)
├── scripts/              # 開発スクリプト
├── tests/                # テストコード
├── Dockerfile            # 本番用
├── Dockerfile.dev        # 開発用
└── podman-compose.yml    # コンテナ構成
```

## トラブルシューティング

### SearXNGに接続できない

```bash
# コンテナの状態確認
podman ps

# ログ確認
podman logs lancet-searxng

# 再起動
podman restart lancet-searxng
```

### ネットワーク接続の問題

```bash
# Podmanネットワーク確認
podman network ls
podman network inspect lancet_lancet-net

# ネットワーク再作成
podman network rm lancet_lancet-net
./scripts/dev.sh up
```

### Chromeに接続できない

```bash
# Windows側でChromeを再起動
# --remote-debugging-port=9222 を確認

# WSLからの接続テスト
curl http://localhost:9222/json
```

### OllamaでGPUが使えない

```bash
# CUDAの確認
nvidia-smi

# Ollamaの再インストール
curl -fsSL https://ollama.com/install.sh | sh
```

## ライセンス

MIT License

## 参考

- [要件定義書](requirements.md)
- [実装計画](IMPLEMENTATION_PLAN.md)
- [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
