# Q_ASYNC_ARCHITECTURE.md 設計メモ

> **作成日**: 2025-12-24
> **結論**: 技術的に優れた設計。Phase 1実装済み。追加対応は不要。

---

## 評価

**◎ 問題なし** - 設計・ADR-0010・実装が一貫している。

---

## 将来検討事項（優先度：低）

### エラーリトライポリシー

現状、失敗したジョブは `state='failed'` で終了し、自動リトライなし。

**選択肢**:
| 選択肢 | 説明 |
|--------|------|
| 自動リトライ | ワーカーが指数バックオフでリトライ（一時的エラー向け） |
| MCPクライアント責任 | クライアントが失敗検知しリトライ判断（現状の暗黙設計） |
| 現状維持 | シンプルさ優先 |

**推奨**: 運用データを見てから判断。現時点では現状維持で問題なし。

---

## 確認済み実装

| 機能 | ファイル | 状態 |
|------|----------|:----:|
| 2ワーカー並列 | `src/scheduler/search_worker.py:26` | ✅ |
| CAS（レース防止） | `src/scheduler/search_worker.py:102-122` | ✅ |
| Long polling | `src/research/state.py:284-340` | ✅ |
| graceful/immediate stop | `src/scheduler/search_worker.py:192-209` | ✅ |
| Browser SERP concurrency=1 | `src/search/browser_search_provider.py:159` | ✅ 意図的設計 |
