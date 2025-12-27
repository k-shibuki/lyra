## rg 置換で事故らないためのルール（正規化フェーズ向け）

このガイドは「破壊的な命名正規化」を **`rg` ベースで実施する場合**に、誤爆（意図しない置換）を避けるための作法を固定化する。
（※現時点は docs-only。実施はまだ行わない）

### 1. 絶対ルール

- **裸の単語を置換しない**（例: `confidence` / `type` / `status` の“生文字”を全体置換しない）
- **引用符つきキーのみ**を置換対象にする
  - Python: `["key"]` / `.get("key")` / `{"key": ...}`
  - JSON: `"key": ...`
- **ファイルスコープを必ず絞る**
  - 1キーずつ、1ファイル（または1ディレクトリ）ずつ
- **“長いキー → 短いキー”の順で**置換する
  - 例: `brier_score_calibrated` を先に、`brier_score` を後に（部分一致事故防止）

### 2. 禁止（このTier1で特に危険）

- `\"confidence\"` の **全体置換**
  - `confidence` は複数意味（edge legacy / timeline event / decomposition internal / …）を持つため、必ず **split** 扱い
- `\"type\"` / `\"status\"` の **全体置換**
  - 汎用語は **split** 扱いが原則（producer/object を付けて意味分割してから）

### 3. 推奨フロー（“一撃”に近いが安全）

1. `rg` で該当キーの出現箇所を **ファイル単位で把握**
2. そのキーの意味が単一か（split不要か）を確認
3. 置換は **引用符つきキー**に限定して実行
4. `rg` で旧キーがそのファイル内で 0 件になったことを確認
5. 次のファイルへ

### 4. 置換対象パターン（推奨）

以下のパターンのみを対象にする（= 事故りにくい）。

- **Python dict access**
  - `\\[\"OLD\"\\]`
  - `\\.get\\(\"OLD\"`
- **Python dict literal**
  - `\"OLD\"\\s*:`（キーとして使われる箇所に限定）
- **JSON**
  - `\"OLD\"\\s*:`

### 5. Tier1 “review” の決定ファイル

- `docs/archive/parameter-registry.tier1-review-decisions.json`
  - `decision=normalize`: 原則そのまま置換OK（引用符キーのみ）
  - `decision=split`: **絶対にグローバル置換禁止**（ファイル単位で条件付き）
  - `decision=keep`: この波では置換しない（Tier0のみで対応／または将来の全項目正規化で検討）

### 6. split-key を先に処理するための“チェック”

split の `replacements[]` に `expected_matches_in_scope` がある場合:
- 置換前に `rg`（スコープ限定）で **一致件数が想定どおり**であることを確認
- 置換後に同じスコープで **旧キーが0件**になったことを確認

これにより「別の意味の同名キー」を誤って巻き込む事故を抑止する

