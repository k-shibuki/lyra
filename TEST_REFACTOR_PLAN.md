# Test Strategy Compliance Plan

このドキュメントは `.cursor/rules/test-strategy.mdc` への全テストファイルの準拠計画を定義する。

## 1. 現状分析

### 1.1 全体統計（2024年時点）

| 指標 | 値 |
|------|-----|
| テストファイル総数 | 57 |
| テストケース総数 | 約2,200 |
| テスト観点表あり | 18 (32%) |
| Given/When/Then完備 | 7 (12%) |
| pytestmarkあり | 45 (79%) |

### 1.2 準拠状態の定義

各ファイルは以下の準拠レベルで分類される：

| レベル | 定義 | 要件 |
|--------|------|------|
| **Level 0** | 未準拠 | 観点表なし、G/W/Tなし |
| **Level 1** | 部分準拠 | 観点表あり、G/W/T一部 |
| **Level 2** | ほぼ準拠 | 観点表あり、G/W/T大部分 |
| **Level 3** | 完全準拠 | 観点表あり、G/W/T全件、pytestmarkあり |

### 1.3 ファイル別現状

| ファイル | テスト数 | 行数 | 観点表 | G/W/T数 | Mark | Level | Phase |
|----------|---------|------|--------|---------|------|-------|-------|
| test_storage.py | 37 | 791 | ✓ | 37 | ✓ | 3 | Done |
| test_search_parsers.py | 65 | 1117 | ✓ | 65 | ✓ | 3 | Done |
| test_search_provider.py | 37 | 781 | ✓ | 37 | ✓ | 3 | Done |
| test_browser_search_provider.py | 30 | 912 | ✓ | 31 | ✓ | 3 | Done |
| test_fetcher.py | 49 | 952 | ✓ | 49 | - | 2 | 1 |
| test_robots.py | 44 | 722 | ✓ | 38 | ✓ | 2 | 1 |
| test_filter.py | 21 | 445 | ✓ | 21 | ✓ | 3 | Done |
| test_evidence_graph.py | 41 | 897 | ✓ | 41 | ✓ | 3 | Done |
| test_deduplication.py | 23 | 436 | ✓ | 23 | ✓ | 3 | Done |
| test_extractor.py | 20 | 496 | ✓ | 20 | ✓ | 3 | Done |
| test_calibration.py | 72 | 1307 | ✓ | 72 | ✓ | 3 | Done |
| test_policy_engine.py | 18 | 362 | ✓ | 18 | ✓ | 3 | Done |
| test_metrics.py | 26 | 398 | ✓ | 26 | ✓ | 3 | Done |
| test_intervention_queue.py | 42 | 1406 | ✓ | 42 | ✓ | 3 | Done |
| test_notification.py | 31 | 1038 | ✓ | 31 | ✓ | 3 | Done |
| test_notification_provider.py | 74 | 1055 | ✓ | 74 | ✓ | 3 | Done |
| test_circuit_breaker.py | 29 | 471 | ✓ | 29 | ✓ | 3 | Done |
| test_domain_policy.py | 88 | 1332 | ✓ | 88 | ✓ | 3 | Done |
| test_ab_test.py | 38 | 565 | - | 0 | ✓ | 0 | 3 |
| test_bfs.py | 31 | 659 | - | 0 | ✓ | 0 | 3 |
| test_browser_archive.py | 37 | 789 | - | 0 | ✓ | 0 | 3 |
| test_browser_provider.py | 44 | 781 | - | 0 | ✓ | 0 | 3 |
| test_budget.py | 42 | 728 | - | 0 | ✓ | 0 | 3 |
| test_chain_of_density.py | 30 | 784 | - | 0 | ✓ | 0 | 3 |
| test_claim_decomposition.py | 36 | 609 | - | 0 | ✓ | 0 | 3 |
| test_claim_timeline.py | 47 | 920 | - | 0 | ✓ | 0 | 3 |
| test_crt_transparency.py | 22 | 519 | - | 0 | ✓ | 0 | 3 |
| test_dns_policy.py | 37 | 672 | - | 0 | ✓ | 0 | 3 |
| test_e2e.py | 17 | 1052 | - | 0 | ✓ | 0 | 4 |
| test_engine_config.py | 49 | 774 | - | 0 | ✓ | 0 | 3 |
| test_entity_integration.py | 19 | 576 | - | 0 | ✓ | 0 | 3 |
| test_entity_kb.py | 52 | 939 | - | 0 | ✓ | 0 | 3 |
| test_http3_policy.py | 45 | 891 | - | 0 | ✓ | 0 | 3 |
| test_human_behavior.py | 44 | 637 | - | 0 | ✓ | 0 | 3 |
| test_integration.py | 25 | 607 | - | 0 | - | 0 | 4 |
| test_ipv6_manager.py | 64 | 1084 | - | 0 | ✓ | 0 | 3 |
| test_lifecycle.py | 29 | 666 | - | 0 | - | 0 | 4 |
| test_llm_provider.py | 62 | 1206 | - | 0 | ✓ | 0 | 3 |
| test_page_classifier.py | 39 | 1045 | - | 0 | ✓ | 0 | 3 |
| test_pivot.py | 33 | 448 | - | 0 | ✓ | 0 | 3 |
| test_profile_audit.py | 30 | 736 | - | 0 | ✓ | 0 | 3 |
| test_quality_analyzer.py | 40 | 919 | - | 0 | ✓ | 0 | 3 |
| test_rdap_whois.py | 22 | 420 | ✓ | 22 | ✓ | 3 | Done |
| test_replay.py | 20 | 453 | - | 0 | ✓ | 0 | 3 |
| test_report.py | 32 | 295 | - | 0 | ✓ | 0 | 3 |
| test_research.py | 29 | 863 | - | 0 | - | 0 | 4 |
| test_search.py | 68 | 1114 | - | 0 | - | 0 | 3 |
| test_sec_fetch.py | 65 | 874 | - | 0 | - | 0 | 3 |
| test_session_transfer.py | 35 | 669 | - | 0 | ✓ | 0 | 3 |
| test_site_search.py | 30 | 478 | - | 0 | ✓ | 0 | 3 |
| test_stealth.py | 26 | 317 | - | 0 | - | 0 | 3 |
| test_temporal_consistency.py | 45 | 588 | - | 0 | ✓ | 0 | 3 |
| test_ucb_allocator.py | 45 | 600 | - | 0 | ✓ | 0 | 3 |
| test_undetected.py | 27 | 477 | - | 0 | ✓ | 0 | 3 |
| test_utils.py | 29 | 417 | - | 0 | ✓ | 0 | 3 |
| test_wayback.py | 33 | 598 | - | 0 | ✓ | 0 | 3 |
| test_wayback_fallback.py | 36 | 815 | - | 0 | ✓ | 0 | 3 |

---

## 2. 準拠要件（test-strategy.mdc より）

### 2.1 テスト観点表（必須）

各テストファイルのdocstringに以下の形式のMarkdown表を追加：

```markdown
## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-XXX-N-01 | Valid input | Equivalence – normal | Success | - |
| TC-XXX-B-01 | Empty input | Boundary – empty | Error | Edge case |
...
```

### 2.2 Given/When/Then コメント（必須）

各テストケースに以下の構造を追加：

```python
def test_example(self):
    """Test description."""
    # Given: 前提条件の説明
    setup_data = create_test_data()

    # When: 実行する操作
    result = function_under_test(setup_data)

    # Then: 期待する結果
    assert result.ok is True
    assert result.value == expected_value
```

### 2.3 pytestmark（推奨）

ファイル冒頭に適切なマーカーを追加：

```python
import pytest
pytestmark = pytest.mark.unit  # または integration, e2e
```

### 2.4 例外検証（異常系で必須）

```python
with pytest.raises(ValueError, match="expected message"):
    function_that_raises()
```

---

## 3. Phase 計画

### Phase 1: Level 2 → Level 3 昇格（6ファイル）

**目標**: 既に観点表があり、G/W/Tが一部あるファイルを完全準拠に

| ファイル | テスト数 | 現状G/W/T | 残作業 |
|----------|---------|-----------|--------|
| test_fetcher.py | 49 | 49 | pytestmark追加 |
| test_robots.py | 44 | 38 | 残6件のG/W/T追加 |
| test_evidence_graph.py | 41 | 12 | 残29件のG/W/T追加、pytestmark |
| test_deduplication.py | 23 | 4 | 残19件のG/W/T追加 |
| test_extractor.py | 20 | 1 | 残19件のG/W/T追加 |

**推定作業量**: 約70テストケースにG/W/T追加

### Phase 2: Level 1 → Level 3 昇格（8ファイル） ✅ 完了

**目標**: 観点表はあるがG/W/Tがないファイルを完全準拠に

| ファイル | テスト数 | 作業内容 | 状態 |
|----------|---------|----------|------|
| ~~test_calibration.py~~ | ~~72~~ | ~~72件のG/W/T追加~~ | ✅ Done |
| ~~test_policy_engine.py~~ | ~~18~~ | ~~18件のG/W/T追加~~ | ✅ Done |
| ~~test_metrics.py~~ | ~~26~~ | ~~26件のG/W/T追加~~ | ✅ Done |
| ~~test_intervention_queue.py~~ | ~~42~~ | ~~42件のG/W/T追加、pytestmark~~ | ✅ Done |
| ~~test_notification.py~~ | ~~31~~ | ~~31件のG/W/T追加、pytestmark~~ | ✅ Done |
| ~~test_notification_provider.py~~ | ~~74~~ | ~~74件のG/W/T追加、pytestmark~~ | ✅ Done |
| ~~test_circuit_breaker.py~~ | ~~29~~ | ~~29件のG/W/T追加、pytestmark~~ | ✅ Done |
| ~~test_domain_policy.py~~ | ~~88~~ | ~~88件のG/W/T追加~~ | ✅ Done |

**完了**: 380テストケースにG/W/T追加完了

### Phase 3: Level 0 → Level 3（33ファイル）

**目標**: 観点表もG/W/Tもないファイルを完全準拠に

| ファイル | テスト数 | 作業内容 |
|----------|---------|----------|
| test_ab_test.py | 38 | 観点表作成、38件のG/W/T追加 |
| test_bfs.py | 31 | 観点表作成、31件のG/W/T追加 |
| test_browser_archive.py | 37 | 観点表作成、37件のG/W/T追加 |
| test_browser_provider.py | 44 | 観点表作成、44件のG/W/T追加 |
| test_budget.py | 42 | 観点表作成、42件のG/W/T追加 |
| test_chain_of_density.py | 30 | 観点表作成、30件のG/W/T追加 |
| test_claim_decomposition.py | 36 | 観点表作成、36件のG/W/T追加 |
| test_claim_timeline.py | 47 | 観点表作成、47件のG/W/T追加 |
| test_crt_transparency.py | 22 | 観点表作成、22件のG/W/T追加 |
| test_dns_policy.py | 37 | 観点表作成、37件のG/W/T追加 |
| test_engine_config.py | 49 | 観点表作成、49件のG/W/T追加 |
| test_entity_integration.py | 19 | 観点表作成、19件のG/W/T追加 |
| test_entity_kb.py | 52 | 観点表作成、52件のG/W/T追加 |
| test_http3_policy.py | 45 | 観点表作成、45件のG/W/T追加 |
| test_human_behavior.py | 44 | 観点表作成、44件のG/W/T追加 |
| test_ipv6_manager.py | 64 | 観点表作成、64件のG/W/T追加 |
| test_llm_provider.py | 62 | 観点表作成、62件のG/W/T追加 |
| test_page_classifier.py | 39 | 観点表作成、39件のG/W/T追加 |
| test_pivot.py | 33 | 観点表作成、33件のG/W/T追加 |
| test_profile_audit.py | 30 | 観点表作成、30件のG/W/T追加 |
| test_quality_analyzer.py | 40 | 観点表作成、40件のG/W/T追加 |
| ~~test_rdap_whois.py~~ | ~~22~~ | ~~観点表作成、22件のG/W/T追加~~ ✅ |
| test_replay.py | 20 | 観点表作成、20件のG/W/T追加 |
| test_report.py | 32 | 観点表作成、32件のG/W/T追加 |
| test_search.py | 68 | 観点表作成、68件のG/W/T追加、pytestmark |
| test_sec_fetch.py | 65 | 観点表作成、65件のG/W/T追加、pytestmark |
| test_session_transfer.py | 35 | 観点表作成、35件のG/W/T追加 |
| test_site_search.py | 30 | 観点表作成、30件のG/W/T追加 |
| test_stealth.py | 26 | 観点表作成、26件のG/W/T追加、pytestmark |
| test_temporal_consistency.py | 45 | 観点表作成、45件のG/W/T追加 |
| test_ucb_allocator.py | 45 | 観点表作成、45件のG/W/T追加 |
| test_undetected.py | 27 | 観点表作成、27件のG/W/T追加 |
| test_utils.py | 29 | 観点表作成、29件のG/W/T追加 |
| test_wayback.py | 33 | 観点表作成、33件のG/W/T追加 |
| test_wayback_fallback.py | 36 | 観点表作成、36件のG/W/T追加 |

**推定作業量**: 観点表33件作成、約1,300テストケースにG/W/T追加

### Phase 4: E2E/Integration 特別対応（6ファイル）

**目標**: E2E/Integration テストの準拠対応

| ファイル | テスト数 | 作業内容 |
|----------|---------|----------|
| test_e2e.py | 17 | 観点表作成、G/W/T追加、e2eマーク確認 |
| test_integration.py | 25 | 観点表作成、G/W/T追加、integrationマーク追加 |
| test_lifecycle.py | 29 | 観点表作成、G/W/T追加、pytestmark追加 |
| test_research.py | 29 | 観点表作成、G/W/T追加、pytestmark追加 |

---

## 4. 作業量サマリ

| Phase | ファイル数 | 観点表作成 | G/W/T追加 | pytestmark |
|-------|----------|-----------|-----------|------------|
| 1 | 5 | 0 | ~70 | 2 |
| 2 | 8 | 0 | ~380 | 4 |
| 3 | 33 | 33 | ~1,300 | 3 |
| 4 | 4 | 4 | ~100 | 4 |
| **合計** | **50** | **37** | **~1,850** | **13** |

**注**: Done済み（Level 3）のファイルは 10 件（Phase 1 完了により +3）

---

## 5. 進捗管理

### 完了済み

- [x] test_storage.py (Level 3)
- [x] test_search_parsers.py (Level 3)
- [x] test_search_provider.py (Level 3)
- [x] test_browser_search_provider.py (Level 3)
- [x] test_filter.py (Level 3)
- [x] test_fetcher.py (Level 3) ※要pytestmark確認
- [x] test_robots.py (Level 2→3 要確認)

### Phase 1 完了 ✅

- [x] test_evidence_graph.py (Level 3)
- [x] test_deduplication.py (Level 3)
- [x] test_extractor.py (Level 3)

### Phase 2 完了 ✅

- [x] test_policy_engine.py (Level 3) ✅
- [x] test_metrics.py (Level 3) ✅
- [x] test_circuit_breaker.py (Level 3) ✅
- [x] test_notification.py (Level 3) ✅
- [x] test_intervention_queue.py (Level 3) ✅
- [x] test_calibration.py (Level 3) ✅
- [x] test_notification_provider.py (Level 3) ✅
- [x] test_domain_policy.py (Level 3) ✅

### Phase 3 完了 ✅

- [x] test_rdap_whois.py (Level 3) ✅
- [x] test_ab_test.py (Level 3) ✅
- [x] test_bfs.py (Level 3) ✅
- [x] test_browser_archive.py (Level 3) ✅
- [x] test_browser_provider.py (Level 3) ✅
- [x] test_budget.py (Level 3) ✅
- [x] test_chain_of_density.py (Level 3) ✅
- [x] test_claim_decomposition.py (Level 3) ✅
- [x] test_claim_timeline.py (Level 3) ✅
- [x] test_crt_transparency.py (Level 3) ✅
- [x] test_dns_policy.py (Level 3) ✅
- [x] test_engine_config.py (Level 3) ✅
- [x] test_entity_integration.py (Level 3) ✅
- [x] test_entity_kb.py (Level 3) ✅
- [x] test_http3_policy.py (Level 3) ✅
- [x] test_human_behavior.py (Level 3) ✅
- [x] test_ipv6_manager.py (Level 3) ✅
- [x] test_llm_provider.py (Level 3) ✅
- [x] test_page_classifier.py (Level 3) ✅
- [x] test_pivot.py (Level 3) ✅
- [x] test_profile_audit.py (Level 3) ✅
- [x] test_quality_analyzer.py (Level 3) ✅
- [x] test_replay.py (Level 3) ✅
- [x] test_report.py (Level 3) ✅
- [x] test_search.py (Level 3) ✅
- [x] test_sec_fetch.py (Level 3) ✅
- [x] test_session_transfer.py (Level 3) ✅
- [x] test_site_search.py (Level 3) ✅
- [x] test_stealth.py (Level 3) ✅
- [x] test_temporal_consistency.py (Level 3) ✅
- [x] test_ucb_allocator.py (Level 3) ✅
- [x] test_undetected.py (Level 3) ✅
- [x] test_utils.py (Level 3) ✅
- [x] test_wayback.py (Level 3) ✅
- [x] test_wayback_fallback.py (Level 3) ✅

### Phase 4 待機中

（Phase 3 完了、Phase 4 開始可能）

---

## 6. 品質ゲート

各Phaseの完了条件：

1. **全テストがパス**: `./scripts/test.sh run tests/` が成功
2. **観点表が存在**: grep で "Test Perspectives Table" が見つかる
3. **G/W/T完備**: テスト数 = G/W/Tコメント数
4. **pytestmark存在**: grep で "pytestmark" が見つかる（unit/integration/e2e）
5. **Lintエラーなし**: `read_lints` でエラーがない

