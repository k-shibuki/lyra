# integration-design

モジュール間の連動を設計・検証する。

## 関連ルール
- 連動設計: @.cursor/rules/integration-design.mdc
- コード実行時: @.cursor/rules/code-execution.mdc

## 使用タイミング
- 複数モジュールにまたがる機能実装時
- モジュール間の連動に問題がある場合
- リファクタリングでインターフェース変更時

## 4ステップ（詳細はルール参照）

1. **シーケンス図作成**: `docs/sequences/` にMermaid形式で保存
2. **Pydanticモデル定義**: `src/{module}/schemas.py` に配置
3. **デバッグスクリプト作成**: `tests/scripts/debug_{feature}_flow.py`
4. **シーケンス図更新**: 修正後のフローを記録

## 出力
- シーケンス図（Mermaid形式）
- Pydanticモデル定義
- デバッグスクリプト
- 検証結果
