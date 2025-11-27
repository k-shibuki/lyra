# 要件定義書: Local Autonomous Deep Research Agent

## 1. プロジェクト概要
単一の問いに対し、包括的なデスクトップリサーチを自律的に実行し、完結したインテリジェンス・レポートを出力するシステムを構築する。
本システムは、外部SaaSへの依存を排除し、ローカル環境のリソースのみで稼働するOSINT用自律型エージェントを目指す。
Google Deep ResearchにOSINTで勝つローカルAIエージェントを構築する。

### 1.1 実行前提（ハードウェア・運用）
- ハードウェア/OS: Windows 11（UI/Cursor）+ WSL2 Ubuntu（Runtime）。Host RAM 64GB、WSL2割当32GBを前提とする。
- GPU: NVIDIA RTX 4060 Laptop（VRAM約8GB）を前提。WSL2でCUDAを有効化し、Ollama/Torch/ONNX RuntimeはCUDA版を使用（失敗時はCPUへ即時フォールバック）。
- VRAM/推論方針: マイクロバッチとシーケンス長の自動短縮でVRAM≤8GBを維持。重推論とヘッドフル操作は同時スロットで併走させない。
- 用途/対象: OSINTのデスクトップリサーチ（公的・学術・規格・技術中心）。商用API・有償インフラは不使用（Zero OpEx）。
- 人手介入許容: CAPTCHA/hCaptcha/Turnstile/ログイン/強制クッキーバナー等は手動解除を許容（認証待ちキューに積み、ユーザーの都合でバッチ処理。上限回数/時間は§3.6/§7に準拠）。

## 2. 基本方針
- 思考と作業の分業: 思考（論理構成・判断）はCursor上のAIが担当し、作業（検索・閲覧・データ収集）はWSL2上のPythonスクリプト（MCPサーバ）が担当する。
- インターフェース: Cursorとエージェント間の通信にはMCP (Model Context Protocol) を採用し、AIがツールとしてエージェントの機能を直接呼び出せる構成とする。
- Zero OpEx: 運用コストを完全無料とする。商用APIは使用しない。
- Local Constraint: 実行環境はWSL2内に限定し、メモリリソースを厳格に管理する。
- **半自動運用**: Cloudflare/CAPTCHA等の認証突破はユーザーの手動介入を前提とし、認証待ちをキューに積んでバッチ処理可能とする。認証不要ソースを優先処理し、ユーザー介入回数を最小化する。
 - OSINT最適化: 権威・一次資料を優先し、反証探索を強制。収集→抽出→要約の各段の決定根拠を因果ログで連結（チェーン・オブ・カストディ）する。
 - 反スパム方針: SEOアグリゲータ/キュレーション寄りの低品質源泉は初期重みを低下させ、ドメイン学習により恒久スキップ候補へ昇格可能とする。
 - 監査可能性: HTML/PDFのWARC保存とスクリーンショット、抽出断片のハッシュ（出典・見出し・周辺文脈）を保存し、検証/再現を容易にする。
 - ヒューマンインザループ: CAPTCHA/ログイン/クッキーバナー等の突破は人手介入を許容（認証待ちキューでバッチ処理、上限を運用で管理、§3.6参照）。

### 2.1. Cursor AI と Lancet の責任分界（探索制御）

本システムでは「思考（何を調べるか）」と「作業（どう調べるか）」を明確に分離する。OSINT品質を最優先し、**クエリ/サブクエリの設計を含む探索の戦略的判断はすべてCursor AIが担う**。ローカルLLM（Qwen2.5-3B等）はCursor AIより推論力が劣るため、クエリ設計には関与しない。

#### 2.1.1. 責任マトリクス

| 責任領域 | Cursor AI（思考） | Lancet MCP（作業） |
|---------|------------------|-------------------|
| **問いの分解** | サブクエリの設計・優先度決定 | 設計支援情報の提供（エンティティ抽出、テンプレート候補等） |
| **クエリ生成** | すべてのクエリの設計・指定 | 機械的展開のみ（同義語・ミラークエリ・演算子付与） |
| **探索計画** | 計画の立案・決定 | 計画の実行・進捗報告 |
| **探索制御** | 次のアクション判断 | 充足度・新規性メトリクスの計算と報告 |
| **反証探索** | 逆クエリの設計・指定 | 機械パターンの適用（「課題」「批判」等の接尾辞付与） |
| **停止判断** | 探索の終了指示 | 停止条件充足の報告 |
| **レポート構成** | 論理構成・執筆判断 | 素材（断片・引用）の提供 |

**重要**: クエリ/サブクエリの「設計」は例外なくCursor AIが行う。Lancetが「候補を提案」することはない。

#### 2.1.2. 対話フロー

探索サイクルは以下のCursor AI主導のループで進行する：

```
1. Cursor AI → create_task(query)
   └─ Lancet: タスク作成、初期状態返却

2. Cursor AI → get_research_context(task_id)
   └─ Lancet: 設計支援情報を返却
     - 抽出されたエンティティ（人名/組織/地名等）
     - 適用可能な垂直テンプレート（学術/政府/企業等）
     - 類似過去クエリの成功率
     - 推奨エンジン/ドメイン

3. Cursor AI: 情報を基にサブクエリを設計（この判断はCursor AIのみが行う）

4. Cursor AI → execute_subquery(task_id, subquery, priority)
   └─ Lancet: 検索実行→取得→抽出→評価を自律実行
   └─ Lancet: 結果サマリ（収穫率、新規断片数、充足度）を返却

5. Cursor AI → get_exploration_status(task_id)
   └─ Lancet: 現在の探索状態を返却（**推奨なし・メトリクスのみ**）
     - 実行済みサブクエリの状態（充足/部分充足/未充足）
     - 新規性スコア推移
     - 残り予算（ページ数/時間）
     - 発見された新エンティティ（次のクエリ設計の参考）
     - **注意**: 「次に何をすべきか」の推奨は返さない。Cursor AIがこのデータを基に判断する

6. Cursor AI: 状況を評価し、次のサブクエリを設計・実行指示
   （ステップ4-5を繰り返す）

7. Cursor AI → execute_refutation(task_id, claim_ids)
   └─ Lancet: Cursor AI指定の主張に対し機械パターンで反証検索

8. Cursor AI → finalize_exploration(task_id)
   └─ Lancet: 最終状態をDBに記録、未充足項目を明示

9. Cursor AI → generate_report(task_id)
   └─ Lancet: 素材を提供
   └─ Cursor AI: レポート構成・執筆
```

#### 2.1.3. Lancetの自律範囲

Lancetは**Cursor AIの指示に基づいて**以下を自律的に実行する（指示なしに勝手に探索を進めない）：

- **機械的展開のみ**: Cursor AI指定のサブクエリに対する同義語展開、言語横断ミラークエリ、演算子付与
- **取得・抽出パイプライン**: 検索→プリフライト→取得→抽出→ランキング→NLI
- **メトリクス計算**: 収穫率、新規性、充足度、重複率の計算
- **異常ハンドリング**: CAPTCHA/ブロック検知、手動介入トリガー、クールダウン適用
- **ポリシー自動調整**: エンジン重み、ドメインQPS、経路選択（§4.6に準拠）

**Lancetが行わないこと**: サブクエリの設計、クエリ候補の提案、探索方針の決定

#### 2.1.4. ローカルLLMの役割

Lancet内蔵のローカルLLM（Qwen2.5-3B等）は**機械的処理に限定**する。クエリ設計には一切関与しない。

- **許可される用途**:
  - 言語横断ミラークエリの翻訳・正規化（Cursor AI指定のクエリを他言語へ変換）
  - 断片からの事実/主張抽出（§3.3に準拠）
  - 固有表現抽出（エンティティ認識）
  - **コンテンツ品質評価**（§3.3.3に準拠）: AI生成/アグリゲータ/SEOスパムの判定（ルール判定が曖昧な場合のみ）
  - **構造化・コンテキスト付与**: 見出し階層の構築、断片への文脈情報（資料・見出し・段落位置）の付与

- **禁止される用途**:
  - **サブクエリの設計・候補生成**（Cursor AIの専権）
  - 探索の戦略的判断（次に何を調べるか）
  - サブクエリの優先度決定
  - 探索の停止判断
  - 反証クエリの設計（機械パターン適用のみ許可）
  - レポートの論理構成決定

この制約により、**OSINT品質に直結するすべての設計判断**はCursor AI（高性能LLM）が担い、Lancetは効率的な作業実行に専念する。

#### 2.1.5. 判断委譲の例外

以下の状況では、Lancetが一時的に判断を代行し、事後報告する：

- **予算枯渇**: 総ページ数/時間上限に達した場合、探索を自動停止し報告
- **深刻なブロック**: 全ドメインがクールダウン中の場合、探索を一時停止し報告
- **認証セッション放棄**: ユーザーが`skip_authentication`を明示的に呼んだ場合、当該URLをスキップ

## 3. 機能要件

### 3.1. 自律リサーチ機能
- ユーザー入力: 調査テーマ（問い）を受け付けるインターフェースを持つ。
- 検索計画の立案: 問いを分解し、検索クエリを自動生成する。
- 再帰的探索プロセス:
  1. 検索実行
  2. 結果の評価（情報の充足度判定）
  3. 新たな仮説の生成または不足情報の特定
  4. 追加検索の実行
  このサイクルを十分な情報が集まるまで、または規定の上限回数まで繰り返す。
 - 探索パラメータと停止条件:
  - 初期クエリ数: 10〜16件（GPU前提時）。CPUのみ環境は8〜12件。各クエリ上位5〜10件を取得
  - 探索深度: 標準3（サブクエリ展開を含む）／高価値枝は最大4
   - 充足度判定: 各サブクエリについて独立ソース3件以上、または一次資料1件＋二次資料1件以上
   - 情報新規性: 直近20件の閲覧で新規有用断片の出現率が10%未満となる状態が2サイクル継続
  - 予算上限: 総ページ数≤120/タスク、総時間≤60分/タスク（RTX 4060 Laptop想定）。CPUのみ環境は≤75分/タスク
  - LLM投入比率: LLM処理時間が総処理時間の≤30%となるよう制御（GPU時の目標値）
   - 打ち切り時は未充足サブクエリを明示し、フォローアップ候補を出力
 - 探索ログと再現性: すべてのクエリ、評価スコア、決定根拠を構造化ログ（JSON/SQLite）に保存する。
- 手動介入と制御:
  - 認証待ちキュー: 認証が必要なURLはキューに積み、ユーザーの都合でバッチ処理（§3.6.1参照）
  - 並行処理: 認証待ち中も認証不要ソースの探索を継続
  - スキップ条件: 自動リトライ（回線更新・ヘッドフル昇格・冷却適用）3回失敗で認証待ちキューへ移行、ユーザーが`skip_authentication`で明示スキップ可
 
#### 3.1.1. 検索戦略
- クエリ多様化:
  - 同義語・上位/下位概念・関連実体の展開（SudachiPy＋固有表現抽出で派生）
  - フレーズ固定（"..."）、必須/除外（+/-）、演算子（site:, filetype:, intitle:, after:）を体系的に適用
  - 言語横断（日⇄英）のミラークエリを自動生成（ローカルLLMで翻訳・正規化）
  - 英→多言語（de/fr/zh等）のミラークエリを少数サンプルで発行し、回収率に応じて枠を自動拡張
- エンジン選択と重み付け:
  - ブロック耐性優先のallowlistを既定（例: Wikipedia/Wikidata, Mojeek, Marginalia, Qwant, DuckDuckGo-Lite。Google/Bingは既定無効または極小重み）
  - カテゴリ（ニュース/学術/政府/技術）で層別化し、過去の精度/失敗率/ブロック率で重みを学習
  - エンジン別レート制御（並列度=1、厳格QPS）とサーキットブレーカ（故障切替・冷却）を実装
  - 学術・公的は直接ソース（arXiv, PubMed, gov.uk 等）を優先し、一般検索への依存を抑制
  - エンジンキャッシュ／ブラックリストを自動管理（短期で故障・高失敗のエンジンは一定時間無効化）
  - ラストマイル・スロット: 回収率の最後の10%を狙う限定枠としてGoogle/Bing/Brave-Liteを最小限開放（厳格なQPS・回数・時間帯制御）
  - エンジン正規化レイヤ: フレーズ/演算子/期間指定等の対応差を吸収するクエリ正規化を実装（エンジン別に最適化）
- 探索木制御:
  - 初期は幅優先、情報新規性が高い枝は優先的に深掘り（best-first with novelty）
  - サブクエリごとの収穫率（有用断片/取得件数）で予算を動的再配分（UCB1風）
- SERP→自然遷移の徹底:
  - 直行GETは例外扱い。原則 SERP→記事→詳細 でReferer/Origin/`sec-fetch-*`を整合
  - スニペット要約＋BM25/埋め込みでクリック優先度を推定し、低期待値リンクは省く
- 垂直特化テンプレ:
  - 公的・学術・規格: `site:go.jp`, `site:who.int`, `site:iso.org`, `filetype:pdf` 等の定型クエリ群
  - 日本語学術: CiNii, J-STAGE, 国会図書館。英語: arXiv, PubMed, gov.uk（全てHTMLスクレイプで利用、API不使用）
  - PDF主体分野: 目次／索引／章立てページを経由し、索引用語のBM25再評価で対象節を狙撃
- サイト内検索の活用:
  - `site:domain.tld` とキーワードの組合せを既定化。内部検索UIがある場合は高価値ドメインに限定して自動操作を試行し、成功率を記録・学習
- 時間フィルタ/鮮度管理:
  - `after:`やエンジン期間指定を利用。重複ソースは最新を優先し、旧版は補助エビデンスに格下げ
- クエリABテスト:
  - 表記ゆれ/助詞/語順のバリアントを小規模A/B。高収穫クエリはキャッシュし再利用
 - 権威・一次資料ファースト:
   - 規制/登記/政府/公式発表/規格/判例/学術原著を優先。二次・三次の要約サイトは補助証拠に限定
 - ピボット探索（OSINT）:
   - エンティティ拡張: 企業→子会社/役員/所在地/ドメイン、ドメイン→サブドメイン→証明書SAN→組織名、個人→別名/ハンドル/所属
   - 出典遡行: 記事→引用元→一次資料へ段階遡り、引用ループ/セルフリファレンスを検出・減点
 - 時系列軸の併用:
   - 初出→更新→訂正/撤回のタイムラインを構築。WaybackのHTML（API不使用）や旧版PDFを参照して差分を把握
 - スパム耐性:
   - ドメイン/テンプレ/広告密度/本文構造の異常を特徴量化し、アグリゲータ/AI生成が疑われるページは低優先度化
 - 言語横断の強化:
   - 重要断片は日英双方でミラー検索し、内容差分が大きい場合は両系統を併記し相互検証

#### 3.1.2. クローリング戦略
- ドメイン内探索:
  - 同一ドメインは深さ≤2のBFSを既定。見出し/目次/関連記事リンクの係り受けで優先度付け
- サイトマップ/robots遵守:
  - `robots.txt` と `sitemap.xml` を探索し、許可範囲の重要URLを抽出して優先取得
- プリフライト軽量判定:
  - HEAD/軽量GETでCloudflare/JSチャレンジ兆候を検知し、ヘッドフル昇格/スキップ/冷却へ即時分岐
- プリフライト分岐テンプレ:
  - HEAD/軽量GETの結果（例: `server=cloudflare`, `cf-ray`, 403/429兆候）に基づき、直回線/ヘッドフル/Tor/クールダウンを決定
  - 判定と結果はドメインポリシーDBへ反映し、次回以降のデフォルト経路・QPS・冷却時間に活用
- ページタイプ判定:
  - 記事/ナレッジ/掲示/フォーラム/ログイン壁/一覧の分類で抽出・遷移戦略を切替
- スナップショット保存:
  - HTMLと主要アセットのWARC保存（`warcio`）。再現性と再解析性を担保
 - 初回取得の指紋整合:
   - 静的ページであっても初回アクセスは原則ブラウザ経由（ヘッドレス）で実施し、Cookie/ETag/LocalStorage/指紋を自然に確立
   - 2回目以降はHTTPクライアント（`curl_cffi`）でETag/If-None-Match・Last-Modified/If-Modified-Sinceを活用し軽量再訪
 - 動的依存の最小化:
   - DOM変換が必要な箇所のみブラウザへ限定投入し、本文抽出自体は可能な限り`trafilatura`で行う（両経路の差分はWARC/スクショで保存）
- リソースブロック:
  - ブラウザ経路では広告/トラッカー/巨大メディア（動画/高解像度画像）をルール化して遮断（Playwrightの`route.abort`等）。露出・負荷・指紋差分を低減
- セッション移送ユーティリティ:
  - 初回ブラウザで確立したCookie/ETag/UA/Accept-LanguageをHTTPクライアントへ安全に移送（同一ドメイン限定）
  - Referer/`sec-fetch-*`の整合を維持しつつ、304再訪を優先して露出と負荷を低減
 - インフラ・レジストリ直叩き（HTMLのみ）:
   - RDAP/WHOISの公式Web/レジストリ（IANA/各NIC）を対象に登録者/NS/更新履歴を取得（API不使用）
   - 証明書透明性ログ: `crt.sh` でSAN/発行者/発行時系列を抽出し、ドメイン探索の種へ展開
   - 企業登記/官報/規格公示: 各国公的サイトのHTMLを優先取得し、一次資料として格上げ
   - 抽出した名称/所在地/識別子はエンティティKBへ正規化（別表記・住所正規化・同一性推定）
 - 指紋/挙動の一貫化:
   - 実プロファイルを既定とし、viewport/言語/UAメジャーの安定性を優先。ジッターは狭幅に限定し、ヒステリシスで振動を抑制

#### 3.1.3. OSINT垂直テンプレート強化
- 企業/団体プロファイル:
  - 公式サイト/IR/有報/官報/登記、公的規格/認証リスト、プレスリリースの直叩き
  - クエリ例: `site:go.jp 企業名`, `site:edinet.fsa.go.jp 企業名`, `filetype:pdf 会社名 仕様`
- ドメイン/インフラ:
  - RDAP/WHOIS（Web）、`crt.sh`、プロバイダ告知、運用ポリシー/障害報告、セキュリティ勧告
  - クエリ例: `site:crt.sh ドメイン`, `site:iana.org AS NS`
- 学術/技術一次資料:
  - J-STAGE/CiNii/arXiv/PubMed/規格原典/ベンダー白書（HTML/PDF）
- 政策・規制:
  - 官報/法令データベース/規制当局発表/パブコメ
- 採用/人物:
  - 公式採用/求人票/講演資料（ソーシャルは原則スキップまたは手動モード）

#### 3.1.4. 検索エンジン健全性・正規化レイヤ
- ヘルスチェック/サーキットブレーカ:
  - 指標: `success_rate_1h/24h`, `captcha_rate`, `median_latency`, `http_error_rate`, `ban_suspected`
  - 状態: `closed`/`half-open`/`open`（連続失敗≥2で`open`、成功1回で`half-open`→安定で`closed`）
  - 自動無効化: `open`状態のエンジンはTTL（30〜120分）で一時無効化し、`half-open`でプロービング
- エンジン正規化:
  - クエリ正規化: 演算子・期間指定・引用・`site:` のエンジン差を吸収するマッピングテーブルを適用
  - SERP正規化: `title`, `url`, `snippet`, `date`, `engine`, `rank`, `source_tag` を統一スキーマで格納
  - 非互換検知: 正規化失敗率が閾値超過で当該エンジンを自動降格（重み低下）しログを残す
- ヘルスの永続化:
  - SQLiteの`engine_health`テーブルにEMA（1h/24h）を保持し、重み・QPS・探索枠を自動調整

#### 3.1.5. サイト内検索UI自動操作（ホワイトリスト運用）
- 対象: 省庁/学術/規格/大手技術サイト等で内部検索UIが安定しているドメインをallowlist管理
- アプローチ:
  - フォーム自動検出（`input[type=search|text]`＋`button[type=submit]`/Enter送信）→ 結果ページから本文リンク抽出
  - 失敗時は即時フォールバック（`site:domain.tld`＋クエリ）
  - 成功率/収穫率をドメインポリシーへ学習反映（成功率低下で一時停止）
- 制約/安全:
  - QPS≤0.1、並列度=1、連続失敗2で当日スキップ
  - CAPTCHA/ログイン壁検知時は手動誘導へ切替

#### 3.1.6. Wayback差分探索の比率制御（補強）
- トリガ: 直近のブロック率高・対象記事の初出/更新追跡・削除/改訂痕跡検知
- 戦略:
  - 最新版→直近3スナップショットを取得し、見出し・要点・日付の差分を抽出
  - 差分が大きい場合はタイムラインに明示し、本体本文は現行を優先、旧版は補助証拠
- 予算:
  - Wayback取得はドメイン別/タスク別に上限（例: 総ページ数の≤15%）を適用し、新規性が高い主張にのみ付与

#### 3.1.7. 探索サイクル制御（§2.1との連携）

本セクションは§2.1で定義した責任分界に基づき、探索サイクルの詳細を規定する。

##### 3.1.7.1. サブクエリの設計（Cursor AI主導）

サブクエリの設計は**Cursor AIが全面的に行う**。LancetはローカルLLMでサブクエリを生成しない。

- **設計支援情報の提供**（Lancet）:
  - `get_research_context` ツールで以下を返却:
    - 抽出されたエンティティ（人名/組織/地名/製品名等）
    - 適用可能な垂直テンプレート（学術/政府/企業/技術等）
    - 類似過去クエリの成功率・収穫率
    - 推奨エンジン/高成功率ドメイン
  - これらは「参考情報」であり、サブクエリの設計判断には関与しない

- **設計フロー**（Cursor AI）:
  1. `get_research_context` で支援情報を取得
  2. 問いを分析し、必要なサブクエリを**自ら設計**:
     - 事実確認クエリ（what/when/where）
     - 背景・文脈クエリ（why/how）
     - 反証クエリ（課題/批判/limitations）
     - エンティティ展開クエリ（関連組織/人物）
  3. 各サブクエリに優先度を付与（high/medium/low）
  4. `execute_subquery` で個別に実行指示

- **設計時の考慮事項**（Cursor AIガイドライン）:
  - 一次資料にアクセスしやすいクエリを優先（site:go.jp, filetype:pdf等）
  - 言語横断が有効なテーマでは日英両方のクエリを設計
  - 反証クエリは主張が固まった段階で設計（早すぎる反証探索は非効率）

##### 3.1.7.2. 探索状態の管理

- **サブクエリ状態**:
  - `pending`: 生成済み・未実行
  - `running`: 実行中
  - `satisfied`: 充足（独立ソース≥3、または一次+二次≥2）
  - `partial`: 部分充足（独立ソース1〜2件）
  - `exhausted`: 予算消化または新規性低下で停止
  - `skipped`: 手動スキップ

- **タスク状態**:
  - `created`: タスク作成済み（Cursor AIがサブクエリを設計中）
  - `exploring`: 探索実行中
  - `awaiting_decision`: Cursor AIの判断待ち（状態報告後）
  - `finalizing`: 探索完了処理中
  - `completed`: 完了
  - `failed`: エラーで中断

##### 3.1.7.3. 充足度判定

各サブクエリの充足度は以下の基準で計算する：

- **独立ソース数**: 異なるドメインかつ同一ナラティブクラスタに属さないソースの数
- **一次資料有無**: 政府/学術/規格/公式発表からの直接証拠
- **充足スコア**: `min(1.0, (独立ソース数 / 3) * 0.7 + (一次資料有無 ? 0.3 : 0))`
- **充足判定**: スコア ≥ 0.8 で `satisfied`

##### 3.1.7.4. 新規性判定と停止条件

- **新規性スコア**: 直近k=20件の取得断片における新規有用断片の比率
- **停止条件**:
  - 新規性 < 10% が2サイクル（各サイクル=10件取得）継続で当該サブクエリを停止
  - 全サブクエリが `satisfied` / `exhausted` / `skipped` で探索完了
  - 予算（ページ数/時間）枯渇で強制終了

##### 3.1.7.5. 反証探索の強制

- **トリガ**: Cursor AIが反証探索を指示（通常はサブクエリが `satisfied` になった後）
- **逆クエリ設計**（Cursor AI）:
  - 主張に対する反証クエリを設計（例: "X の課題", "X 批判", "X limitations"）
  - 対立仮説や否定形のクエリを設計
- **機械パターン適用**（Lancet）:
  - Cursor AI指定のクエリに対し、定型接尾辞を機械的に付与（"課題/批判/問題点/limitations/反論/誤り"）
  - **注意**: ローカルLLMによる逆クエリ設計は行わない
- **反証探索の結果**:
  - 反証発見: エビデンスグラフに `refutes` エッジを追加
  - 反証ゼロ: 信頼度を5%減衰し、「反証未発見」を明記

### 3.2. エージェント実行機能（Python）
- ブラウザ操作: Playwright（CDP接続）を一次手段とし、Windows側Chromeの実プロファイルをpersistent contextで利用。必要時のみヘッドフルに昇格する。
- 検索エンジン統合: ローカルで稼働するSearXNG（メタ検索エンジン）に対しクエリを送信し、結果を取得する。
- コンテンツ抽出: 検索結果のページ（HTML/PDF）からテキスト情報を抽出する。不要な広告やナビゲーションは除外する。
- GUI連携: WSL2からWindows側Chromeへ`connect_over_cdp`で接続し、既存ユーザープロファイルを再利用する
 - 調査専用プロファイル運用:
   - 研究専用のChromeプロファイルを`--user-data-dir`/`--profile-directory`で固定化（例: `--profile-directory="Profile-Research"`）、日常利用プロファイルと分離
   - プロファイルは拡張機能を最小・フォント/言語/タイムゾーンはOS設定と整合。クラッシュ時の影響面を局所化

#### 3.2.1. MCPツールIF仕様

##### 基本ツール（Phase 1-10）
- `search_serp(query, engines, limit, time_range)` → `[{title, url, snippet, date, engine, rank}]`
- `fetch_url(url, context, policy)` → `{ok, status, headers, html_path|pdf_path, warc_path?, screenshot_path?, reason}`
- `extract_content(input_path|html, type)` → `{text, title?, headings?, language?, tables?, meta}`
- `rank_candidates(query, passages)` → `[{id, score_bm25, score_embed, score_rerank}]`
- `llm_extract(passages, task)` → `{facts[], claims[], citations[]}`
- `decompose_question(question, use_llm?, use_slow_model?)` → `{claims[], decomposition_method, success}`
  - **用途**: §3.3.1「問い→主張分解」。リサーチクエスチョンを原子主張へ分解
  - **注意**: `llm_extract`とは入力形式が異なる（passages[] vs question: string）ため独立ツール
- `nli_judge(pairs)` → `[{pair_id, stance(supports|refutes|neutral), confidence}]`
- `notify_user(event, payload)` → `{shown, deadline_at}`
- `schedule_job(job)` → `{accepted, slot(gpu|browser_headful|network|cpu_nlp), priority, eta}`
- `create_task(query, config?)` → `{task_id, status}`
- `get_task_status(task_id)` → `{task, progress}`
- `get_report_materials(task_id, include_evidence_graph)` → `{claims[], fragments[], evidence_graph?, summary}`
  - **注意**: レポート「生成」ではなく素材「提供」。構成・執筆はCursor AIが担当（§2.1準拠）

##### 探索制御ツール（Phase 11）

- `get_research_context(task_id)` → サブクエリ設計の支援情報を提供（候補生成は行わない）
  - 入力:
    - `task_id`: 対象タスクID
  - 出力:
    ```json
    {
      "ok": true,
      "task_id": "...",
      "original_query": "元の問い",
      "extracted_entities": [
        {
          "text": "エンティティ名",
          "type": "person|organization|location|product|event",
          "context": "抽出元の文脈"
        }
      ],
      "applicable_templates": [
        {
          "name": "academic|government|corporate|technical",
          "description": "テンプレートの説明",
          "example_operators": ["site:go.jp", "filetype:pdf"]
        }
      ],
      "similar_past_queries": [
        {
          "query": "過去の類似クエリ",
          "harvest_rate": 0.45,
          "success_engines": ["duckduckgo", "qwant"]
        }
      ],
      "recommended_engines": ["duckduckgo", "qwant", "mojeek"],
      "high_success_domains": ["go.jp", "who.int", "arxiv.org"],
      "notes": "設計時の参考情報（Cursor AIへのヒント）"
    }
    ```
  - **注意**: このツールはサブクエリ候補を生成しない。Cursor AIがこの情報を参考にサブクエリを設計する。

- `execute_subquery(task_id, subquery, priority?, budget?)` → サブクエリを実行
  - 入力:
    - `task_id`: タスクID
    - `subquery`: サブクエリテキストまたはID
    - `priority`: 実行優先度（オプション）
    - `budget`: このサブクエリの予算制限（オプション、ページ数/時間）
  - 出力:
    ```json
    {
      "ok": true,
      "subquery_id": "sq_001",
      "status": "running|satisfied|partial|exhausted",
      "pages_fetched": 15,
      "useful_fragments": 8,
      "harvest_rate": 0.53,
      "independent_sources": 3,
      "has_primary_source": true,
      "satisfaction_score": 0.85,
      "novelty_score": 0.42,
      "new_claims": [...],
      "budget_remaining": {"pages": 45, "time_seconds": 480}
    }
    ```

- `get_exploration_status(task_id)` → 探索状態を取得（メトリクスのみ、推奨なし）
  - 入力: `task_id`
  - 出力:
    ```json
    {
      "ok": true,
      "task_id": "...",
      "task_status": "exploring|awaiting_decision|...",
      "subqueries": [
        {
          "id": "sq_001",
          "text": "...",
          "status": "satisfied|partial|exhausted|pending|skipped",
          "satisfaction_score": 0.85,
          "independent_sources": 3,
          "refutation_status": "pending|found|not_found"
        }
      ],
      "metrics": {
        "satisfied_count": 3,
        "partial_count": 2,
        "pending_count": 1,
        "exhausted_count": 0,
        "total_pages": 78,
        "total_fragments": 124,
        "total_claims": 15,
        "elapsed_seconds": 480
      },
      "budget": {
        "pages_used": 78,
        "pages_limit": 120,
        "time_used_seconds": 480,
        "time_limit_seconds": 1200
      },
      "ucb_scores": {
        "enabled": true,
        "arm_scores": {"sq_001": 1.23, "sq_002": 0.87},
        "arm_budgets": {"sq_001": 15, "sq_002": 20}
      },
      "authentication_queue": {
        "pending_count": 3,
        "high_priority_count": 1,
        "domains": ["protected.go.jp", "secure.example.com"],
        "oldest_queued_at": "2024-01-15T10:00:00Z",
        "blocking_exploration": false
      },
      "warnings": ["ドメインX がクールダウン中", "予算残り20%", "認証待ち3件（高優先度1件）"]
    }
    ```
  - **注意**: `recommendations`フィールドは返さない。Cursor AIがこのデータを基に次のアクションを判断する。
  - **認証待ち通知**: `authentication_queue`でCursor AIに認証待ち状況を報告。`pending_count≥3`または`high_priority_count≥1`で`warnings`にも追加。

- `execute_refutation(task_id, claim_id?, subquery_id?)` → 反証探索を実行
  - 入力:
    - `task_id`: タスクID
    - `claim_id`: 特定の主張に対する反証（オプション）
    - `subquery_id`: 特定のサブクエリ全体に対する反証（オプション）
  - 出力:
    ```json
    {
      "ok": true,
      "target": "claim_id or subquery_id",
      "reverse_queries_executed": 3,
      "refutations_found": 1,
      "refutation_details": [
        {
          "claim_text": "...",
          "refuting_fragment_id": "...",
          "source_url": "...",
          "nli_confidence": 0.82
        }
      ],
      "confidence_adjustment": -0.05
    }
    ```

- `finalize_exploration(task_id)` → 探索を終了
  - 入力: `task_id`
  - 出力:
    ```json
    {
      "ok": true,
      "task_id": "...",
      "final_status": "completed|partial",
      "summary": {
        "satisfied_subqueries": 4,
        "partial_subqueries": 2,
        "unsatisfied_subqueries": ["sq_006"],
        "total_claims": 18,
        "verified_claims": 12,
        "refuted_claims": 2,
        "unverified_claims": 4
      },
      "followup_suggestions": [
        "sq_006 は追加調査が必要: 一次資料が見つかっていません"
      ],
      "evidence_graph_summary": {
        "nodes": 45,
        "edges": 78,
        "primary_source_ratio": 0.65
      }
    }
    ```

##### 共通仕様
- すべてJSON I/O、タイムアウト・再試行・因果ログ（呼出元ID）を必須付与
- 探索制御ツールは`task_id`を必須とし、タスクスコープでの状態管理を行う
- 長時間実行が予想される`execute_subquery`は進捗コールバックをサポート（オプション）

##### MCPツール一覧（責任分界準拠）

| カテゴリ | ツール名 | Cursor AI（思考） | Lancet（作業） |
|----------|----------|-------------------|----------------|
| **タスク管理** | `create_task` | タスク作成の指示 | タスクID発行・DB登録 |
| | `get_task_status` | 状態確認の指示 | 状態データ返却 |
| **探索制御** | `get_research_context` | 設計支援情報の取得指示 | エンティティ/テンプレ/成功率の返却 |
| | `execute_subquery` | **サブクエリの設計**・実行指示 | 検索→取得→抽出→評価の実行 |
| | `get_exploration_status` | 状態確認・**次判断はCursor AI** | メトリクス/予算の報告（**推奨なし**） |
| | `execute_refutation` | 反証対象の指定 | 機械パターン適用・反証検索 |
| | `finalize_exploration` | 終了判断 | 最終状態のDB記録 |
| **取得・抽出** | `search_serp` | クエリの指定 | 検索エンジン実行・SERP返却 |
| | `fetch_url` | URL/ポリシーの指定 | HTTP/ブラウザ取得・WARC保存 |
| | `extract_content` | 抽出指示 | HTML/PDFからテキスト抽出 |
| **フィルタ・評価** | `rank_candidates` | クエリ/候補の指定 | BM25/埋め込み/リランク実行 |
| | `llm_extract` | 抽出タスクの指定 | ローカルLLMで事実/主張抽出 |
| | `decompose_question` | 分解対象questionの指定 | 原子主張への分解（§3.3.1） |
| | `nli_judge` | 対象ペアの指定 | スタンス推定（supports/refutes/neutral） |
| **レポート素材** | `get_report_materials` | 素材取得の指示 | 主張/断片/エビデンスグラフ返却 |
| | `get_evidence_graph` | グラフ参照の指示 | ノード/エッジの構造化データ返却 |
| **校正・評価** | `add_calibration_sample` | 正解フィードバックの送信 | サンプル蓄積・再校正トリガー |
| | `get_calibration_stats` | 校正状態の確認 | パラメータ/デグレ検知の報告 |
| | `rollback_calibration` | ロールバック判断・指示 | パラメータ復元の実行 |
| | `save_calibration_evaluation` | 評価実行の指示 | Brier/ECE算出・DB保存 |
| | `get_calibration_evaluations` | 評価履歴の取得指示 | 構造化データ返却 |
| | `get_reliability_diagram_data` | ビンデータ取得指示 | 信頼度-精度曲線データ返却 |
| **通知・ジョブ** | `notify_user` | 通知内容の指定 | トースト送信・待機 |
| | `schedule_job` | ジョブの指定 | スロット管理・スケジューリング |

**重要**: 
- 「設計」「判断」「構成」はCursor AIの責任
- Lancetは「実行」「計算」「データ返却」に専念
- `get_report_materials`は素材提供のみ。レポート構成・執筆はCursor AIが行う

##### ユースケース別フロー

**UC-1: 標準調査タスク**

```
Cursor AI                          Lancet MCP
   │                                   │
   ├─ create_task(query) ─────────────►│ タスク作成
   │◄───────────── {task_id} ──────────┤
   │                                   │
   ├─ get_research_context(task_id) ──►│ 設計支援情報取得
   │◄─── {entities, templates, ...} ───┤
   │                                   │
   │  [Cursor AIがサブクエリを設計]     │
   │                                   │
   ├─ execute_subquery(task_id, sq) ──►│ サブクエリ実行
   │◄─── {harvest_rate, claims, ...} ──┤
   │                                   │
   ├─ get_exploration_status(task_id)─►│ 状態確認
   │◄─── {subqueries, budget, ...} ────┤
   │                                   │
   │  [充足/予算に応じて繰り返し]       │
   │                                   │
   ├─ execute_refutation(task_id, c)──►│ 反証探索
   │◄─── {refutations_found, ...} ─────┤
   │                                   │
   ├─ finalize_exploration(task_id) ──►│ 探索終了
   │◄─── {summary, followup, ...} ─────┤
   │                                   │
   ├─ get_report_materials(task_id) ──►│ 素材取得
   │◄─── {claims, fragments, graph} ───┤
   │                                   │
   │  [Cursor AIがレポート構成・執筆]   │
   │                                   │
```

**UC-2: 校正フィードバックループ**

```
Cursor AI                          Lancet MCP
   │                                   │
   │  [調査中にLLM予測を観測]           │
   │                                   │
   ├─ add_calibration_sample(...) ────►│ サンプル蓄積
   │◄─── {added, pending_count} ───────┤
   │                                   │
   │  [一定サンプル蓄積後]              │
   │                                   │
   ├─ get_calibration_stats() ────────►│ 校正状態確認
   │◄─── {params, degradation_detected}┤
   │                                   │
   │  [デグレ検知時、Cursor AIが判断]   │
   │                                   │
   ├─ rollback_calibration(source) ───►│ ロールバック実行
   │◄─── {rolled_back_to_version} ─────┤
   │                                   │
```

**UC-3: 手動介入フロー**

```
Cursor AI                          Lancet MCP
   │                                   │
   │  [CAPTCHA/Cloudflare検知]          │
   │                                   │
   │◄─── notify_user(captcha, ...) ────┤ 通知送信
   │                                   │
   │  [ユーザーが手動解除]              │
   │                                   │
   │◄─── {resolved: true} ─────────────┤ 解除通知
   │                                   │
   │  [探索再開]                        │
   │                                   │
```

#### 3.2.2. ジョブスケジューラ/スロット制御
- スロットと排他:
  - `gpu`: 同時実行=1（埋め込み/リランク/7B推論）。`browser_headful`と排他
  - `browser_headful`: 同時実行=1（CDP操作）。`gpu`と排他
  - `network_client`: 同時実行=3〜5（HTTP取得、ドメイン同時実行=1）
  - `cpu_nlp`: 同時実行=並列（BM25/軽量NLI）
- 優先度:
  - `serp > prefetch > extract > embed > rerank > llm_fast(3B) > llm_slow(7B)`
- 予算/バックプレッシャ:
  - タスク総ページ/時間予算と連動し、収穫率が低下した枝は自動縮小
  - キャンセル/一時停止/再開をサポート。因果ログに状態遷移を記録

### 3.3. フィルタリングと評価（Local LLM）
- 関連性判定: 取得したWEBページが調査テーマに関連するかをローカルLLM（Ollama/Phi-3等）で判定する。
- 情報抽出: 関連ありと判定されたページから、問いに対する回答となる要点を抽出する。
  - 多段評価:
   - 第1段: ルール／キーワードとBM25で粗フィルタ
    - 第2段: 埋め込み類似度と軽量リランカー（`bge-m3`＋`bge-reranker-v2-m3` ONNX/int8）で再順位付け
   - 第3段: LLMで要点抽出・主張の仮説／反証ラベル付け
 - 二段LLMゲーティング:
   - 抽出用LLMは既定3B（高速）で実行し、曖昧/難例のみ7Bへ昇格（GPUオフロード, q5_k_m/q6_k）。昇格判断はBM25/埋め込み/リランクのスコアしきい値で制御
 - GPU最適化:
   - 埋め込み`bge-m3`とリランカー`bge-reranker-v2-m3`はONNX Runtime CUDA/FP16（CPUフォールバックあり）。候補上限は100→最大150まで拡張（タスク予算内で自動調整）
 - NLI昇格:
   - 既定はtiny-DeBERTa（CPU）→不一致/矛盾検知の難例のみDeBERTa-v3-small/base（ONNX/CUDA, FP16）へ昇格
 - エビデンスグラフ: 各断片に URL・タイトル・発見日時・抜粋・主張ID・信頼度・出典種別を付与し、SQLite/JSONに格納する。
 - 信頼度スコアリング:
   - ソース階層（例）: 一次資料 > 公的機関 > 学術 > 信頼メディア > 個人ブログ
   - 一致度: 複数独立ソースの一致数・相互矛盾の有無
   - 時点整合: 発行／更新日の新鮮さ
   - スコア合成: [0..1]で算出し、レポートにしきい値と根拠を明記
 - 検証チェック:
   - 重要主張は最低3独立ソースで裏付け、または一次資料1件＋二次資料1件以上
   - 反証検索を必須化（例: 「課題」「批判」「limitations」「反証」などの逆クエリ）
 
#### 3.3.1. 情報分析戦略
- 問い→主張分解:
  - 上位の問いを原子主張へ分解。スキーマ: `claim_id`, `text`, `expected_polarity`, `granularity`
- エビデンス抽出:
  - 段落単位で主張と類似度（BM25＋埋め込み）を計算し、該当箇所の引用・見出し・周辺文脈を保存
- 冗長排除/重複同定:
  - 文/段落をMinHash/SimHashでクラスタリング。サイト跨ぎの重複は1件へ正規化
- 立場推定（supports/refutes/neutral）:
  - 軽量NLI（tiny-DeBERTa系ONNX）またはルールベースでスタンス推定（完全ローカル）
- 信頼度キャリブレーション:
  - ソース階層×一致度×鮮度×一貫性で合成し、しきい値・根拠を断片に明記
- 反証探索の強制:
  - 「limitations/批判/誤り」等の逆クエリを各主張に必ず付与。発見ゼロの場合は信頼度を段階的に減衰
- 圧縮と引用の厳格化:
  - Chain-of-Density風に要約密度を上げつつ、全主張に深いリンク・発見日時・抜粋を必須付与
- エビデンスグラフ拡張:
  - ノード: 主張/断片/ソース、エッジ: supports/refutes/cites。NetworkXで構築しSQLiteへ永続化

#### 3.3.2. 新規性と停止条件
- 新規性スコア:
  - 直近k断片におけるユニークn-gram率を算出。しきい値未満が2サイクル継続で当該枝を停止
- 収穫逓減の検知:
  - 断片/時間の収穫率が連続低下した枝は予算縮小、代替サブクエリへ予算移転

#### 3.3.3. OSINT固有の品質・欺瞞対策
- 出典系統の明示:
  - 記事→引用→一次資料のチェーンをグラフに保持し、レポートでは一次資料を優先引用
- 引用ループ/ラウンドトリップ検出:
  - 相互引用・同一出典反復を検出し、重みを減衰（セルフリファレンスは強減点）
- ナラティブ・クラスタリング:
  - MinHash/SimHash＋埋め込みで論説群をクラスタ化し、同一ナラティブ偏重を可視化・多様性を確保
- 矛盾検出:
  - 主要主張に対し逆主張クエリを強制、NLI/ルールでsupports/refutes/neutralを再評価
- 時系列整合:
  - 主張時点とページ更新日の不整合を検出し、古い主張は信頼度を減衰
- 低品質/生成コンテンツの抑制:
  - テンプレ/広告密度/本文構造/表現の反復からAI生成/アグリゲータを推定して減点
  - **二段品質ゲート**:
    - 第1段（ルールベース・高速）: 構造特徴量（広告密度、テンプレ比率、n-gram反復率、文長均一性等）で粗フィルタ
    - 第2段（LLM・精密）: ルール判定が曖昧（スコア0.4〜0.6）な場合のみローカルLLM（3B）で品質評価
  - **LLM品質評価の観点**:
    - 独自の洞察・分析の有無
    - 一次情報源への依拠度
    - 文章の自然さ・人間らしさ
    - 広告/アフィリエイトの過剰さ
    - AI生成/アグリゲータ/SEOスパムの疑い
  - **スコア合成**: LLM評価を行った場合、最終スコア = 0.6×LLMスコア + 0.4×ルールスコア
  - **ペナルティ適用**: 検出された品質問題に応じてランキングスコアを減衰（最大80%減）

#### 3.3.4. 信頼度キャリブレーション
- 目的: 受け入れ基準のしきい値（例: 0.7）に整合する確率校正を適用
- 方法:
  - 小規模検証セットでPlatt/温度スケーリングを算出し、`llm_extract`/`nli_judge`の信頼度へ適用
  - サンプル蓄積ベースで再校正（新規サンプルが閾値に達したら自動再計算）し、Brierスコアの改善を監視
  - `add_calibration_sample`で予測結果と正解ラベルをフィードバックし、使用するほど精度が向上
- 昇格連動:
  - 3B→7Bの昇格判定は校正済み確率で実施（偽陽性/偽陰性のコストに基づくスレッショルド）

### 3.4. レポート生成機能
- 統合と執筆: 収集された断片的な情報を統合し、論理的なレポートとして構成・執筆する（Cursor/Composer機能の活用）。
- 引用管理: 出力される情報には、必ず情報源（URL/タイトル）を明記する。
 - タイムライン/因果:
   - 重要主張ごとに初出/更新/訂正/撤回のタイムラインを付与し、因果関係と未検証ギャップを明示
 - 出典の優先序:
   - 本文では一次資料を優先引用、二次資料は補足として注記（差分や解釈の相違を併記）

### 3.5. 異常系ハンドリング
- CAPTCHA対応: 自動操作で回避できないCAPTCHAが出現した場合、GUIブラウザを前面に表示し、ユーザーによる手動解除を待機するモードへ移行する。
- エラー回復: タイムアウトや接続エラーが発生した場合、当該タスクをスキップまたは再試行し、プロセス全体を停止させない。
 - ブロック回復: 429/403やCloudflare判定を検知した場合は指数バックオフ、回線更新（Tor）、ヘッドレス→ヘッドフル切替、ドメインのクールダウン（最小60分）を順次適用する。

### 3.6. ユーザー通知と手動介入（半自動運用）

#### 3.6.1. 認証待ちキュー（推奨）
- **キュー積み**: 認証が必要なURLは即時ブロックせず、認証待ちキューに積む
- **バッチ処理**: ユーザーが都合の良いタイミングで「認証セッション」を開始し、まとめて処理
- **優先度管理**: 高優先度（一次資料）、中優先度（二次資料）、低優先度で分類
- **並行処理**: 認証待ち中も認証不要ソースの探索を継続
- **セッション再利用**: 認証済みセッション情報を保存し、同一ドメインの後続リクエストで再利用
- **優先度決定**: Cursor AIがサブクエリ実行時に指定。デフォルトはソース種別から推定（一次資料=high）
- **通知連携**: `get_exploration_status`に`authentication_queue`オブジェクトを含め、Cursor AIがユーザーに判断を仰ぐ契機を提供
  - `pending_count`: 認証待ち総数
  - `high_priority_count`: 高優先度（一次資料）の件数
  - `domains`: 認証待ちドメイン一覧
  - `oldest_queued_at`: 最古のキュー時刻
  - `by_auth_type`: 認証タイプ別カウント（cloudflare/captcha/turnstile等）
  - 閾値アラート: ≥3件でwarning、≥5件または高優先度≥2件でcriticalをwarnings配列に追加
- **MCPツール**:
  - `get_pending_authentications`: 認証待ちキューを取得
  - `start_authentication_session`: 認証セッションを開始（URLを開きウィンドウ前面化のみ、DOM操作なし）
  - `complete_authentication`: ユーザーが認証完了を報告
  - `skip_authentication`: 認証をスキップ

##### 認証セッションの安全運用方針

- **最小介入原則**: 認証待ちURLを開いてウィンドウを前面化するのみ。スクロール・ハイライト・フォーカス等のDOM操作は一切行わない
- **完了検知**: ユーザーによる明示報告（`complete_authentication`）を主とする。補助的にCDPのページ遷移イベント（frameNavigated等）をパッシブ監視してもよいが、DOM操作による検知は禁止
- **通知内容**: URLと認証種別（Cloudflare/CAPTCHA等）のみ。認証要素の位置や操作手順は含めない（ユーザーが自ら発見・突破する）
- **ウィンドウ前面化**: OS APIレベル（Windows: SetForegroundWindow / PowerShell、Linux: wmctrl等）で実施し、CDP/JavaScript経由の`window.focus()`は使用しない
- **CDPの安全運用**:
  - 許可: `Page.navigate`（URLを開く）、`Network.enable`/イベント監視（パッシブ）、`Page.bringToFront`（前面化、OS API併用推奨）
  - 禁止: `Runtime.evaluate`（任意JS実行）、`DOM.*`（DOM操作）、`Input.*`（入力シミュレーション）、`Emulation.*`（デバイス偽装）
  - 原則: 認証セッション中はブラウザを「観察」するのみで、「操作」しない

##### 三者責任分界（認証に関する判断）

| 判断 | ユーザー | Cursor AI | Lancet |
|------|----------|-----------|--------|
| **認証セッション開始** | ✅ 最終決定 | 提案・確認を仲介 | 実行 |
| **認証スキップ** | ✅ 最終決定 | 提案・確認を仲介 | 実行 |
| **優先度設定** | - | ✅ 設計時に指定 | 適用・デフォルト推定 |
| **タイムアウト処理** | - | - | ✅ 自動決定（§2.1.5） |

**フロー**: 認証待ち発生 → Lancetがキューに積む → `get_exploration_status`で報告 → Cursor AIがユーザーに確認 → ユーザー判断 → Cursor AIがMCPツール呼び出し

#### 3.6.2. 即時介入（レガシーモード）【廃止】

本セクションは廃止された。認証処理は§3.6.1の認証待ちキューに統合されている。

廃止理由: 即時介入時のDOM操作（スクロール・ハイライト等）がbot検知リスクを高めるため、ユーザー主導のバッチ処理方式に一本化した。

#### 3.6.3. 共通事項
- セキュリティ: 通知内容はURL/タイトル/理由に限定し、機密トークン/クッキーは通知に含めない
- ログ: 手動介入の開始/完了/超過・所要時間・結果（成功/失敗/スキップ）を構造化記録し、自動適応の改善に用いる

## 4. 非機能要件

### 4.1. 経済性
- 外部API利用不可: Google Search API, OpenAI API等の従量課金SaaSは使用しない。
- コストゼロ: Cursorのサブスクリプション費用以外の追加コストを発生させない。
 - 禁止事項: 有料プロキシ／リクエスト代行SaaS／有料CAPTCHA代行の利用を禁止する。
 - 許容OSS: Tor、Ollama、SearXNG、curl_cffi、undetected-chromedriver、trafilatura 等の無償OSSのみを使用する。

### 4.2. 実行環境とリソース制約
- プラットフォーム: Windows 11 (UI/Cursor) + WSL2 Ubuntu (Runtime/MCP Server)
- メモリ管理: Hostマシン（64GB）のうち、WSL2に割り当てられた32GBの範囲内で動作させる。
- プロセスライフサイクル: ブラウザインスタンスやLLMプロセスはタスク完了ごとに破棄（Kill）し、メモリリークを防ぐ。
- コンテナ: SearXNG等の依存サービスはPodman等の軽量コンテナで運用する。
- 通知: Windowsのトースト通知はWSL2→PowerShell橋渡しで実行（無料）。Linux/WSLgでは`libnotify`（`notify-send`）を用いる
- ブラウザ: Windows側Chromeをリモートデバッグ（既存プロファイル/フォント/ロケールを活用）し、WSL2から制御
 - GPU: RTX 4060 Laptop前提。Windows側にNVIDIAドライバ、WSL2でCUDA Toolkit/ドライバを有効化（`nvidia-smi`で確認）。Ollama/Torch/ONNX RuntimeはCUDA版を利用

### 4.3. 抗堪性とステルス性
- ネットワーク/IP層:
  - Tor（SOCKS5）経由の出口ローテーション（StemでCircuit更新、ドメイン単位Sticky 15分）
  - ドメイン同時実行数=1、リクエスト間隔U(1.5,5.5)s、時間帯・日次の予算上限を設定
  - 429/403/Cloudflare検出時は指数バックオフ、回線更新、ドメインのクールダウンを適用
  - 検索段階の安全化: SearXNGは原則非Tor経路で実行（Google/Bing系は既定無効または低重み）、BANやCAPTCHAの発生率を低減（取得本体は状況によりTor/非Torを選択）
  - 事前軽量チェック: HEAD/軽量GETで`server=cloudflare`やJSチャレンジ指標（`cf-ray`等）を検知し、回線更新・ヘッドフル昇格・クールダウンを即時判断
  - Tor利用ポリシーの厳密化:
    - 既定は非Tor（直回線）で開始し、403/JSチャレンジ/レート制限の発生時のみドメイン限定でTorへ昇格
    - Torは当該ドメインでの一時的回避目的に限定し、成功率が低い場合はヘッドフル直回線へ即時ロールバック
    - ドメイン単位のTor粘着（15分）と日次のTor利用上限（割合/回数）を適用
  - エンジン/ドメイン別レート制御の明確化:
    - エンジンQPS≤0.25（1リクエスト/4s）、ドメインQPS≤0.2、並列度=1を原則
    - サーキットブレーカ: 429/403/タイムアウト連続2回でopen、クールダウン≥30分、成功1回でhalf-open→closed
    - 期間・時間帯のスロット化（夜間/休日は保守的）とジッターを導入
  - IPv6運用:
    - IPv6が利用可能な環境ではv6→v4の順に低優先度で試行し、失敗時のみ切替（ドメイン単位で成功率を学習）
  - DNS方針:
    - 直回線時はOSの名前解決に準拠し、ロケール/地域性の一貫性を維持
    - Tor経路時はPrivoxy/Tor経由でDNS解決し、DNSリークを防止（ドメイン単位の適用）
    - EDNS Client Subnetを無効化（resolverが提供する場合は明示設定）
    - DNSキャッシュTTLを尊重し、短時間の再解決を抑制（曝露の低減）
    - v4/v6のハッピーアイボール風切替をドメイン単位で適用（失敗時のみ切替・成功率を記録）
- トランスポート/TLS層:
  - `curl_cffi`のimpersonate=chrome最新でHTTP/2/TLS指紋を一般ブラウザと整合
  - Accept-Language／Timezone／Locale／EncodingをOS設定と整合させる
  - `sec-ch-ua*`/`sec-fetch-*`/Referer/Originを遷移コンテキストと整合（SERP→記事など自然遷移を模倣）
  - ETag/If-None-Match・Last-Modified/If-Modified-Sinceを活用して再訪時の露出と負荷を軽減
  - HTTP/3(QUIC)方針:
    - ブラウザ経由取得ではHTTP/3を自然利用（サイト側が提供時）。HTTPクライアント経由はHTTP/2を既定とし、挙動差を最小化
    - HTTP/3提供サイトで挙動差が大きい場合は、ブラウザ経路比率を自動的に増加させるスイッチを適用
- ブラウザ/JS層:
  - Playwright（CDP接続）を一次手段。Windows側Chromeの実プロファイルをpersistent contextで使用
  - 必要時のみundetected-chromedriverへフォールバック（Cloudflare強/Turnstile等）
  - `stealth.js`相当のプロパティオーバーライドは最小限（`navigator.webdriver`等）。過剰偽装は避ける
  - ヘッドレス/ヘッドフル自動切替とヒューマンライク操作（移動速度分布、スクロール慣性）
  - 実プロファイル活用: Windows側Chromeのユーザープロファイルを用い、フォント/Canvas/Audio等の指紋を一貫化
  - UAメジャーバージョンの追従とフォントセットの一貫性を定期検査（差分検知時は自動修正）
  - 調査専用プロファイルの原則:
    - 拡張機能は最小、ユーザ操作履歴の混入を防ぎ、Cookie/LocalStorageを研究用に隔離
  - 指紋の一貫性と微ジッター:
    - viewportサイズ/スクロール挙動/待機分布は実プロファイル基準で一貫化しつつ、狭幅ジッターのみ適用（ヒステリシスあり）
  - リソースブロッキング:
    - Playwrightの`route`で広告/トラッカー/巨大アセットを遮断（ドメイン/ページタイプ別ルール、学習的に更新）
  - 負荷分離:
    - GPU重推論とヘッドフル操作を同一スロットで同時実行しないスケジューリングを適用（CDP安定・VRAM断片化の回避）
- 失敗時フォールバック:
  - 静的ページはHTTPクライアント取得→`trafilatura`で抽出、動的必須のみブラウザ利用
  - CAPTCHA多発ドメインはスキップまたは手動モードへ移行する
  - 最終手段としてアーカイブ（Wayback等）からの本文参照を検討（鮮度低下を明記、APIは不使用）
  - ドメイン別の冷却・スコアリング（CAPTCHA率/403率）で恒久スキップを自動判断
  - GPUフォールバック:
    - CUDA/VRAM不足/ドライバ異常を検出した場合はONNX/TorchのEP順序でCPUへ即時切替し、タスク中断を回避

#### 4.3.1. プロファイル健全性監査
- 高頻度チェック: タスク開始時およびブラウザセッション初期化時にUA/メジャーバージョン、フォントセット、言語/タイムゾーン、Canvas/Audio指紋の差分検知を実行
- 自動修復: 逸脱検知時はChrome再起動フラグ/フォント再同期/プロファイル再作成（バックアップから復元）を自動実施
- 安全策: `Profile-Research`のみを対象、日常プロファイルへの影響を遮断
- 監査ログ: 差分・修復内容・再試行回数を構造化記録

#### 4.3.2. ブラウザ経路のアーカイブ保存
- 最低限: `page.content()`の保存＋主要リソースのURL/ハッシュ一覧（CDXJ風）＋スクリーンショット
- 任意: CDPのNetworkイベントから簡易HARを生成し、後追い取得でWARCへ充填
- 一貫性: 同一URLのHTTPクライアント経路WARCと紐付け、再解析時はWARCを優先

- ドメインポリシーDB:
  - `block_score`, `cooldown_until`, `headful_ratio`, `last_captcha_at`, `tor_success_rate`, `tor_usage_ratio`, `captcha_type_last_seen`, `referer_match_rate`, `headful_failures` 等を記録し、経路選択/昇格/スキップ判定に利用
 - ポリシー自動学習:
  - ドメインごとの成功率/失敗率/ブロック種別/ヘッドフル必要性をリクエストごとに即時更新し、QPS・クールダウン・Tor適用可否・デフォルト経路を継続的に最適化（EMAで短期/長期の傾向を追跡）
- セッション運用:
  - Windows側Chromeの実プロファイルでCookie/LocalStorageを維持し、再訪時の露出/ブロック率を低減
- ヒューマンライク操作:
  - ランダム化された視線移動/ホイール慣性/待機時間分布を適用（CDPで制御）

### 4.4. データ管理とセキュリティ
- ローカル保存: 収集したデータ（HTML, PDF, テキスト）および生成されたレポートは全てローカルファイルシステムに保存する。
- 形式: テキストデータはMarkdown形式、構造化データはSQLiteまたはJSON形式で保存する。
- プライバシー: 収集したデータや調査内容を外部クラウドへ送信しない（Local LLM利用のため）。

### 4.5. 品質保証と評価指標
- 主要主張は原則3つ以上の独立ソースで裏付け（一次資料がある場合は1次＋2次で可）
- 信頼度スコア≥0.7の主張のみ本文に採用し、下回る場合は但し書きと改善案を併記
- 全出典に深いリンク（該当節/見出し）と発見日時を付与し、引用抜粋を残す
- ログ完全性: クエリ・選別・判断根拠を100%記録（再現可能性）
### 4.6. 自動適応・メトリクス駆動制御
- メトリクス定義:
  - クエリ収穫率（有用断片/取得件数）、新規性スコア推移、重複率、独立ドメイン多様性、ブロック種別別発生率
  - 露出・回避メトリクス: Tor利用率、ヘッドフル比率、Referer整合率、304活用率、ドメイン別CAPTCHA率/403率、IPv6成功率、v4↔v6切替発動回数/成功率、DNSリーク検知率
  - OSINT品質メトリクス:
    - 一次資料採用率、引用ループ検出率、ナラティブクラスタ多様性、矛盾候補発見率、タイムライン付与率、アグリゲータ比率
- 構造化ログ:
  - 検索計画→取得→抽出→評価の各ステージでイベントをJSON/SQLiteへ記録（因果トレース）
  - ポリシー更新ログ: サーキット状態遷移、QPS変更、Tor適用/解除、クールダウン適用を履歴化
- ポリシー自動更新（高頻度クローズドループ制御）:
  - イベント駆動: 各リクエスト/クエリ完了時に即時フィードバック（成功/失敗/ブロック種別/レイテンシをEMAに反映）
  - 周期補完: 30〜120秒周期でドメイン/エンジン単位のEMA（短期/長期）を集約し、パラメータ調整を確定
  - 制御対象: エンジン重み、QPS、クールダウン時間、`headful_ratio`、`tor_usage_ratio`（上限あり）、サーキット状態（open/half-open/closed）
  - セーフガード: 上下限・ヒステリシス・最小保持時間を設定し、振動を防止（例: 同一パラメータは5分未満で反転させない）
  - 例: Referer整合率や304活用率が低下→ブラウザ経路比率を段階的に増加／403/JS検知が増加→直回線→Torへの限定昇格→失敗で即ロールバック
- リプレイ/再現モード:
  - 決定ログから同一フローを再実行可能にし、改善のA/B検証を容易化

#### 4.6.1. 信頼度キャリブレーションの評価

##### 責任分界（§2.1準拠）

| 責任領域 | Cursor AI（思考） | Lancet MCP（作業） |
|---------|------------------|-------------------|
| **評価タイミング** | 評価実行の指示 | - |
| **評価計算** | - | Brierスコア/ECE/ビンデータの算出 |
| **評価永続化** | - | 評価結果のDB保存 |
| **評価データ取得** | 取得対象・期間の指定 | 構造化データの返却 |
| **デグレ検知** | 対応方針の決定 | 閾値超過の検知と報告 |
| **評価レポート** | 論理構成・執筆・可視化判断 | **構造化データの提供のみ**（レポート生成は行わない） |

**重要**: Lancetは評価「レポート」を生成しない。構造化データを返却し、Cursor AIがそれを解釈・構成する。

##### MCPツールIF仕様

- `save_calibration_evaluation(source, predictions, labels)` → 評価を実行しDBに保存
  - 入力:
    - `source`: ソースモデル識別子（例: "llm_extract", "nli_judge"）
    - `predictions`: 予測確率のリスト
    - `labels`: 正解ラベルのリスト（0 or 1）
  - 出力:
    ```json
    {
      "ok": true,
      "evaluation_id": "eval_001",
      "source": "llm_extract",
      "brier_score": 0.15,
      "brier_score_calibrated": 0.12,
      "improvement_ratio": 0.20,
      "expected_calibration_error": 0.08,
      "samples_evaluated": 100,
      "evaluated_at": "2024-01-15T10:00:00Z"
    }
    ```

- `get_calibration_evaluations(source?, limit?, since?)` → 評価履歴を構造化データで返却
  - 入力:
    - `source`: ソースフィルタ（オプション）
    - `limit`: 取得件数上限（デフォルト: 50）
    - `since`: 開始日時（オプション）
  - 出力:
    ```json
    {
      "ok": true,
      "evaluations": [
        {
          "evaluation_id": "eval_001",
          "source": "llm_extract",
          "brier_score": 0.15,
          "brier_score_calibrated": 0.12,
          "improvement_ratio": 0.20,
          "expected_calibration_error": 0.08,
          "samples_evaluated": 100,
          "evaluated_at": "2024-01-15T10:00:00Z"
        }
      ],
      "total_count": 25
    }
    ```

- `get_reliability_diagram_data(source, evaluation_id?)` → 信頼度-精度曲線用ビンデータを返却
  - 入力:
    - `source`: ソースモデル識別子
    - `evaluation_id`: 特定評価のID（オプション、省略時は最新）
  - 出力:
    ```json
    {
      "ok": true,
      "source": "llm_extract",
      "evaluation_id": "eval_001",
      "n_bins": 10,
      "bins": [
        {
          "bin_lower": 0.0,
          "bin_upper": 0.1,
          "count": 15,
          "accuracy": 0.07,
          "confidence": 0.05,
          "gap": 0.02
        }
      ],
      "overall_ece": 0.08
    }
    ```

##### 永続化スキーマ

`calibration_evaluations`テーブル:
- `id`: 評価ID（主キー）
- `source`: ソースモデル識別子
- `brier_score`: 校正前Brierスコア
- `brier_score_calibrated`: 校正後Brierスコア（NULL可）
- `improvement_ratio`: 改善率
- `expected_calibration_error`: ECE
- `samples_evaluated`: 評価サンプル数
- `bins_json`: ビンデータ（JSON）
- `calibration_version`: 使用した校正パラメータのバージョン
- `evaluated_at`: 評価日時
- `created_at`: レコード作成日時

##### デグレ検知と報告

- **検知条件**: 直近の評価でBrierスコアが前回比5%以上悪化
- **報告内容**: `get_calibration_stats`の返却値に`degradation_detected`フラグと詳細を含める
- **対応判断**: Cursor AIが`rollback_calibration`を呼ぶかどうかを決定（Lancetは自動ロールバックを提案しない）
- **例外**: `enable_auto_rollback=true`設定時のみ、Lancetが自動ロールバックを実行し事後報告

## 5. 技術スタック選定

### 5.1. コアコンポーネント
- Orchestrator: Cursor (LLM: Composer 1)
- Interface: MCP (Model Context Protocol) Server
- Agent Runtime: Python 3.12+ (running inside WSL2)
- Local LLM Runtime: Ollama（CUDA有効）。既定: Qwen2.5-3B/Llama-3.2-3B Instruct q4（高速）→難例のみQwen2.5-7B/Llama-3.1-8B Instruct q5_k_m/q6_kへGPU昇格
- Embeddings: `bge-m3`（多言語・長文安定, ONNX Runtime CUDA/FP16, CPUフォールバックあり）
- Rerank: `bge-reranker-v2-m3`（ONNX Runtime CUDA/FP16, 候補は上位100→最大150まで拡張可, CPUフォールバックあり）
- HTTP Client: curl_cffi（Chrome impersonate）
- Browser Automation: Playwright（CDP接続／Windows側Chromeの実プロファイルpersistent context）＋ undetected-chromedriver（フォールバック）
- Content Extraction: trafilatura（静的ページ抽出）
 - PDF Extraction: PyMuPDF（`fitz`）でPDFからテキスト/画像を抽出（必要時のみOCRをGPUで適用）
- Network: Tor + Stem（回線制御）＋（任意）Privoxy
- Storage: SQLite / JSON（エビデンスグラフ・ログ）
- Search Engine: SearXNG (via Podman)
 - SearXNGエンジンallowlist（既定）: Wikipedia/Wikidata, Mojeek, Marginalia, Qwant, DuckDuckGo-Lite（状況によりBrave）。Google/Bingは既定無効または低重み
- Tokenization/Retrieval: 日本語形態素解析（SudachiPy/MeCab）＋ SQLite FTS5（BM25）で一次粗選別＋（任意）hnswlib/sqlite-vecで近傍検索
 - Notification: Windowsトースト（PowerShell）、Linuxは`libnotify`（`notify-send`）
#### 5.1.1. 補助OSS（任意・無償）
- 抽出系フォールバック: `readability-lxml`, `jusText`, `boilerpy3`
- 重複・類似検出: `datasketch`（MinHash）, `simhash`
- 検索/ランク: `rank-bm25`, `tldextract`, `sqlite-vec`（任意）, `hnswlib`（任意）
- グラフ: `networkx`（エビデンスグラフ構築）
- アーカイブ: `warcio`（WARC保存）
- 軽量NLI: ONNX Runtime + tiny-DeBERTa系モデル（完全ローカル推論）
 - ステルス限定適用: `playwright-stealth`相当の軽量対策（限定ドメインのみ・常用禁止）
 - PDF構造解析: `GROBID`（参考文献・セクション構造の抽出強化）
 - OCR: `PaddleOCR`（GPU対応, スキャンPDF/画像主体の分野のみ適用）, `Tesseract`（軽量フォールバック）
 - 表抽出: `Camelot`, `Tabula`（PDFのテーブル抽出）
 - ベクトル検索: `faiss-gpu`（コーパスが大規模な場合の任意採用）

#### 5.1.2. システム構成補強（キャッシュ/DB/キュー）
- キャッシュ階層:
  - `serp_cache`（キー: 正規化クエリ＋エンジン集合＋期間, TTL既定=24h）
  - `fetch_cache`（キー: 正規化URL＋ETag|Last-Modified, 304優先）
  - `embed_cache`/`rerank_cache`（キー: テキストハッシュ＋モデルID, TTL=7d）
- データベース（SQLite）主要テーブル:
  - `queries`, `serp_items`, `pages`, `fragments`, `claims`, `edges`, `domains`, `engine_health`, `jobs`
  - **`fragments`テーブルのコンテキスト情報**:
    - `heading_context`: 直近の見出し（単一文字列）
    - `heading_hierarchy`: 見出し階層（JSON配列: `[{"level":1,"text":"..."}, ...]`）
    - `element_index`: 見出し配下での要素順序
    - `fragment_type`: 要素種別（paragraph/heading/list/table/quote/figure/code）
- キュー（jobs）:
  - フィールド例: `id, kind, priority, slot, state, budget, created_at, started_at, finished_at, cause_id`
  - スロット/排他・予算・因果トレースを強制

### 5.2. インフラ・OS
- OS: Ubuntu 22.04/24.04 LTS (on WSL2)
- Container Runtime: Podman (Docker代替として推奨、またはDocker Desktop)
- Torサービス（apt）および（任意）PrivoxyをWSL2内で稼働
- Chromium/Chromeはローカルにインストールし、既存プロファイルを再利用（UA/言語/タイムゾーン整合）
- Windows側Chromeを`--remote-debugging-port=9222`で起動し、Playwrightの`connect_over_cdp`でWSL2から接続（実プロファイル/persistent context運用、無料・安定）

## 6. 成果物定義
- インテリジェンス・レポート (Markdown形式)
- 参照資料アーカイブ (保存されたHTML/PDF)
- 調査ログ (検索クエリ履歴、判断ロジックの記録)
- エビデンスグラフDB（SQLite/JSON, 主張—出典—抜粋—信頼度—時刻の対応）
 - 通知モジュール（WSL2→Windowsトースト橋渡しスクリプト/設定、Linux `notify-send`対応）
 - 手動介入運用手順書（認証待ちキュー運用、バッチ処理手順、スキップ判断基準）
 - MCPツール仕様書（I/Oスキーマ・タイムアウト・リトライ方針）
 - ジョブスケジューラ仕様（スロット/排他/優先度/予算/状態遷移）
 - プロファイル健全性監査スクリプトと運用手順
 - 校正データセット/校正パラメータ（Brierスコア評価レポート付）

## 7. 受け入れ基準
- スクレイピング成功率: 一般的なメディア／公的機関／技術ブログ計200URLでの取得成功率≥95%
- 回復力: 429/403発生後、3回以内の自動再取得成功率≥70%
- CAPTCHA: 発生検知100%、自動→手動誘導に確実に移行できること
- 情報品質: 主要主張の3独立ソース裏付け率≥90%、引用漏れ0件
- 深度保証: サブクエリ充足率≥90%（未充足は明示とフォローアップ提示）
- コスト制約: 外部SaaS/有料プロキシ/有料APIを一切使用しないこと（依存チェックで検証）
- 性能: RTX 4060 Laptop搭載機で1タスクあたり60分以内、CPUのみ環境は75分以内（いずれもWSL2 32GB想定）
 - LLM比率: LLM処理の総時間が全体の≤30%（GPU時目標）
 - 認証セッション: 認証待ちキューへの通知成功率≥99%、ウィンドウ前面化成功率≥95%
 - 認証突破効果: 認証セッションで処理した案件の突破率≥80%（Cloudflare/ログイン等を含む）
 - 労力上限: 1タスクあたりのユーザー介入回数≤3回、総介入時間≤5分（目安、強制タイムアウトなし）
 - 露出抑制: ブラウザ投入率≤30%、直行GET比率の低減（Referer整合率≥90%）、再訪問時の304活用率≥70%
 - Tor利用率: 全取得に占めるTor経路の割合≤20%（日次上限とドメイン別上限を両方満たすこと）
 - IPv6運用: IPv6提供サイト訪問時のv6経路成功率≥80%、v4↔v6自動切替の成功率≥80%
 - DNS: Tor経路時のDNSリーク検出0件、EDNS Client Subnet無効化を確認
- 検索収穫・多様性:
  - サブクエリごとの有用断片/取得件数≥0.25、独立ドメイン多様性（上位カテゴリ重複率）≤60%
- 重複率:
  - 断片の重複クラスタ比率≤20%（MinHash/SimHashで算出）
- 反証率:
  - 重要主張のうち反証候補が少なくとも1件以上存在する割合≥80%
- 主張カバレッジ:
  - 原子主張ごとの支持ソース≥2（うち独立ドメイン≥2）、反証がある場合は双方提示
- エビデンスグラフ完全性:
  - 本文に採用した全主張がsupports/refutes/citesのエッジを少なくとも1本以上持つ
- 再現性:
  - 訪問ページのうちWARC保存成功率≥95%、動的ページはスクリーンショット保存率≥95%
 - OSINT品質:
   - 一次資料採用率≥60%、引用ループ検出率≥80%、重要主張のタイムライン付与率≥90%
   - ナラティブクラスタ多様性（同一クラスタ偏重率）≤60%、アグリゲータ比率≤20%
- 検索エンジン健全性:
  - 不健全化の自動検出 適合率≥0.90/再現率≥0.80、`open/half-open/closed`の状態遷移がログで検証可能
- サイト内検索UI:
  - allowlistドメインでの自動操作成功率≥60%、追加収穫（内部検索由来の新規有用断片）≥10%
- Wayback差分:
  - 時系列重要テーマで差分抽出成功率≥80%、ブロック起因の欠落率≤10%（該当ケース内）
- スケジューラ排他:
  - `gpu`と`browser_headful`の同時実行0件/100タスク、ドメイン同時実行=1が侵害されない
- 校正の有効性:
  - Brierスコアが非校正比で≥20%改善、昇格判定の精度向上（誤昇格率の相対低下≥15%）
- キャッシュ/再訪:
  - 304活用率≥70%、SERPキャッシュヒット率≥50%（同テーマ再実行時）
- ブラウザアーカイブ:
  - 動的ページでのスクリーンショット保存率≥95%、主要リソースのハッシュリスト作成率≥90%
- プロファイル健全性:
  - タスク開始時の健全性チェック自動実行成功率≥99%、逸脱検知時の自動修復成功率≥90%

### 7.1. テストコード品質基準

テストは「仕様の検証」であり「テストを通すこと」が目的ではない。以下の基準を遵守する。

#### 7.1.1. 禁止されるテストパターン
以下のパターンはテストの有効性を損なうため、**禁止**とする：

1. **条件付きアサーション（Conditional Assertions）**
   - `if results: assert ...` のような条件分岐でアサーションをスキップするパターン
   - 結果が空の場合もそれ自体を検証すべき（空であることが正しいか、エラーか）
   - 例（禁止）: `if duplicate_ids: assert "f2" in duplicate_ids`
   - 例（正）: `assert "f2" in duplicate_ids`

2. **曖昧なアサーション（Vague Assertions）**
   - `len(x) > 0` や `x is not None` のみで具体的な値を検証しないパターン
   - 期待値が明確な場合は具体値で検証する
   - 例（禁止）: `assert len(similar) > 0`
   - 例（正）: `assert "expected_id" in similar`

3. **OR条件によるアサーション緩和**
   - `assert A or B` で片方が真なら通るパターン（どちらが期待値か不明確）
   - 例（禁止）: `assert "f3" not in ids or "f2" in ids`
   - 例（正）: `assert "f2" in ids` および `assert "f3" not in ids`（別アサーション）

4. **テストを通すためのスレッショルド調整**
   - 本番コードのスレッショルド（例: 類似度0.5）をテスト用に緩和（例: 0.3）するパターン
   - テストは本番設定で動作することを検証すべき
   - 例（禁止）: `MinHashDeduplicator(threshold=0.3)  # テスト用に下げる`
   - 例（正）: 本番デフォルト値を使用、またはテストデータを調整

5. **例外の握りつぶし**
   - `try-except` で例外を捕捉しテストを通過させるパターン
   - 例外が期待される場合は `pytest.raises` を使用

#### 7.1.2. アサーションの要件

1. **具体性（Specificity）**
   - 期待値が既知の場合、具体的な値・ID・件数で検証する
   - 範囲チェックは許容誤差を明示（例: `assert 0.3 <= ratio <= 0.4`）

2. **独立性（Independence）**
   - 各アサーションは単一の検証項目に対応
   - 複合条件は分解して個別にアサート

3. **失敗時の診断性（Diagnosability）**
   - カスタムメッセージまたは明確な変数名で失敗原因を特定可能にする
   - 例: `assert actual == expected, f"Expected {expected}, got {actual}"`

4. **境界条件の網羅**
   - 空入力、単一要素、最大サイズ、境界値を必ずテスト
   - エッジケースを明示的にテストケースとして記述

#### 7.1.3. テストデータの要件

1. **現実性（Realism）**
   - テストデータは本番で想定されるデータに近い特性を持つこと
   - 重複検出テストでは実際に類似するテキストを使用（同一文字列の反復は不可）

2. **多様性（Diversity）**
   - 正例・負例・境界例を網羅
   - 言語（日本語/英語）・長さ・構造のバリエーションを含む

3. **決定性（Determinism）**
   - ランダム性を含む場合はシードを固定し再現可能にする
   - 外部依存（ネットワーク等）はモック化

#### 7.1.4. スレッショルド・パラメータの管理

1. **本番値の明示**
   - 本番で使用するスレッショルドは設定ファイルまたは定数として一元管理
   - テストは原則として本番値を使用

2. **テスト専用値の正当化**
   - テスト専用のスレッショルドを使用する場合、docstringにその理由を明記
   - 例: `"""境界条件テストのため、threshold=0.49で閾値付近の挙動を検証"""`

3. **パラメトリックテスト**
   - 複数のスレッショルド値での挙動を検証する場合は`@pytest.mark.parametrize`を使用

#### 7.1.5. テストの構造要件

1. **Arrange-Act-Assert（AAA）パターン**
   - 準備（Arrange）、実行（Act）、検証（Assert）を明確に分離

2. **docstringによる意図の明示**
   - 各テスト関数に「何を検証するか」「なぜその検証が必要か」を記述
   - 関連する仕様セクション（例: `§3.3.3`）を参照

3. **フィクスチャの適切な使用**
   - 共通セットアップは`@pytest.fixture`で共有
   - テスト固有のデータはテスト関数内で定義

#### 7.1.6. テストレビュー基準

テストコードのレビュー時に以下を確認する：

1. **網羅性**: 仕様の全要件に対応するテストが存在するか
2. **有効性**: テストが実際に仕様違反を検出できるか（ミューテーションテストの観点）
3. **保守性**: テストが実装の詳細に過度に依存していないか
4. **禁止パターン**: §7.1.1の禁止パターンに該当しないか
5. **スレッショルド**: 本番値と異なる場合、正当な理由があるか

#### 7.1.7. 継続的検証

1. **カバレッジ（監視指標）**
   - 行カバレッジ≥70%、分岐カバレッジ≥60%を監視（CIブロックはしない）
   - 前回比5%以上の低下時は警告を発し、PRレビューで理由を確認
   - カバレッジ向上よりも、テストの有効性（ミューテーション検出率）を優先

2. **テストの分類と実行時間**
   - `@pytest.mark.unit`: 外部依存なし、合計≤30秒
   - `@pytest.mark.integration`: モック化された外部依存、合計≤2分
   - `@pytest.mark.e2e`: 実環境（コンテナ内）、必要時のみ手動実行
   - CIでは`unit`と`integration`のみ自動実行（`pytest -m "unit or integration"`）

3. **モック戦略**
   - 外部サービス（SearXNG、Ollama、Chrome）は原則モック化
   - ファイルI/Oは一時ディレクトリ（`tmp_path`フィクスチャ）を使用
   - DBはインメモリSQLite（`:memory:`）または一時ファイルを使用
   - ネットワークアクセスは`unit`テストで禁止（`@pytest.mark.unit`で強制）

4. **ミューテーションテスト**
   - コアモジュール（`filter/`、`search/`）に対し月次で実施
   - 検出率≥50%を下限、≥60%を目標

5. **フレーキーテスト**
   - 不安定なテストは即時対応（修正 or `@pytest.mark.skip`）
   - skip理由とissue番号（またはTODOコメント）を必須記載
   - 同一テストで3回以上skipが発生した場合は根本対応を優先

## 8. 実装難易度評価（AI実装・仕様書駆動前提）
- 検索計画/正規化/ヘルス監視: 中（7〜10日）
  - 主要リスク: SearXNGエンジン破綻への追随。軽減: 正規化失敗率監視と自動無効化
- クローリング/プリフライト/回避: 中（7〜12日）
  - 主要リスク: Cloudflare/Turnstile。軽減: 手動誘導UX＋クールダウン/スキップ自動化
- 抽出/WARC/ブラウザ経路保存: 中（5〜8日）
  - 主要リスク: CDP→WARCの完全互換。軽減: CDXJ風メタ＋後追い取得の二段保存
- 多段フィルタ（BM25→埋め込み→リランク）: 低〜中（4〜7日）
  - 主要リスク: VRAM圧迫。軽減: マイクロバッチ/候補上限自動調整
- LLM抽出/NLI/校正: 中〜高（8〜14日）
  - 主要リスク: 校正データ不足。軽減: 小規模手動ラベル＋リプレイで継続改善
- スケジューラ/スロット排他/予算制御: 中（6〜9日）
  - 主要リスク: デッドロック/飢餓。軽減: 優先度とタイムアウト、因果トレース
- MCPツールIF/因果ログ/再現モード: 中（6〜9日）
  - 主要リスク: I/O肥大。軽減: 圧縮/要約ログ＋詳細はオプトイン保存
- 通知/手動介入/UX: 低〜中（3〜5日）
  - 主要リステスト: OS境界（WSL2→Winトースト）。軽減: スクリプト橋渡しの冪等・リトライ
- 受け入れテスト/ベンチ/メトリクス: 中（7〜10日）
  - 主要リスク: 外部環境の揺らぎ。軽減: リプレイとキャッシュで再現性を確保
- 総評: 4〜6週間でMVP→強化。AI主導の実装は可能（仕様粒度は十分）。最大の不確実性はブロック回避と校正用データ確保だが、いずれも段階導入でリスク吸収可能。