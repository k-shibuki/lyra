# テスト観点表: ヒューマンライク操作の統合テスト

## 対象機能
- `BrowserFetcher.fetch()`でのヒューマンライク操作適用（§4.3.4）
- `BrowserSearchProvider.search()`でのヒューマンライク操作適用（§4.3.4）

## テスト観点表

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|--------------------------------------|-----------------|-------|
| TC-BF-HB-01 | `simulate_human=True`, ページに要素あり | Equivalence – normal | `simulate_reading()`と`move_mouse_to_element()`が呼ばれる | - |
| TC-BF-HB-02 | `simulate_human=False` | Equivalence – disabled | ヒューマンライク操作が呼ばれない | - |
| TC-BF-HB-03 | `simulate_human=True`, ページに要素なし | Boundary – empty page | `simulate_reading()`は呼ばれるが、マウス移動はスキップ | - |
| TC-BF-HB-04 | `simulate_human=True`, 要素検索で例外発生 | Boundary – exception | 例外がキャッチされ、ログ出力してスキップ、通常フロー継続 | - |
| TC-BF-HB-05 | `simulate_human=True`, 要素が5個以上 | Equivalence – multiple elements | 最初の5個からランダムに選択 | - |
| TC-BF-HB-06 | `simulate_human=True`, 要素が1個 | Boundary – single element | その1個が選択される | - |
| TC-BSP-HB-01 | 検索実行、結果ページにリンクあり | Equivalence – normal | `simulate_reading()`と`move_mouse_to_element()`が呼ばれる | - |
| TC-BSP-HB-02 | 検索実行、結果ページにリンクなし | Boundary – empty results | `simulate_reading()`は呼ばれるが、マウス移動はスキップ | - |
| TC-BSP-HB-03 | 検索実行、リンク検索で例外発生 | Boundary – exception | 例外がキャッチされ、ログ出力してスキップ、通常フロー継続 | - |
| TC-BSP-HB-04 | 検索実行、リンクが5個以上 | Equivalence – multiple links | 最初の5個からランダムに選択 | - |
| TC-BSP-HB-05 | 検索実行、リンクが1個 | Boundary – single link | その1個が選択される | - |
| TC-BSP-HB-06 | 検索実行、`simulate_reading()`で例外発生 | Boundary – exception | 例外がキャッチされ、ログ出力してスキップ、通常フロー継続 | - |

## テスト実行コマンド

```bash
# テスト実行
./scripts/test.sh run "tests/test_fetcher.py::TestBrowserFetcherHumanBehavior"
./scripts/test.sh run "tests/test_browser_search_provider.py::TestBrowserSearchProviderHumanBehavior"

# 完了確認
./scripts/test.sh check

# 結果取得
./scripts/test.sh get

# カバレッジ取得
pytest tests/test_fetcher.py::TestBrowserFetcherHumanBehavior tests/test_browser_search_provider.py::TestBrowserSearchProviderHumanBehavior --cov=src/crawler/fetcher --cov=src/search/browser_search_provider --cov-report=term-missing
```
