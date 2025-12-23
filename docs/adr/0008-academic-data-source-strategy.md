# ADR-0008: Academic Data Source Strategy

## Date
2025-11-28

## Context

学術情報の取得には以下の課題がある：

| 課題 | 詳細 |
|------|------|
| API制限 | 多くの学術DBは有料またはレート制限あり |
| カバレッジ | 単一ソースでは網羅性が不十分 |
| 信頼性 | プレプリントと査読済みの区別が必要 |
| Zero OpEx | ADR-0001により有料APIは使用不可 |

主要な学術データソースの比較：

| ソース | 論文数 | API | 引用データ | コスト |
|--------|--------|-----|------------|--------|
| Semantic Scholar | 2億+ | 無料（制限あり） | あり | 無料 |
| OpenAlex | 2.5億+ | 無料（無制限） | あり | 無料 |
| Google Scholar | 最大 | なし（スクレイピング必要） | あり | 無料（規約リスク） |
| Crossref | 1.4億+ | 無料 | 限定的 | 無料 |
| PubMed | 3600万+ | 無料 | なし | 無料 |
| Scopus/WoS | 大規模 | 有料 | あり | 有料 |

## Decision

**Semantic Scholar (S2) をプライマリ、OpenAlex をセカンダリとする2層戦略を採用する。**

### データソース階層

```
[1] Semantic Scholar API
    ↓ レート制限時 or 見つからない場合
[2] OpenAlex API
    ↓ 見つからない場合
[3] DOI/URL直接アクセス
```

### Semantic Scholar (S2) の選択理由

| 観点 | 詳細 |
|------|------|
| 引用グラフ | 高品質な引用・被引用関係 |
| Abstract | ほぼ全論文でアブストラクト取得可能 |
| TL;DR | AI生成の要約が付属 |
| API品質 | RESTful、ドキュメント充実 |
| 無料枠 | 5,000リクエスト/5分 |

### OpenAlex の補完理由

| 観点 | 詳細 |
|------|------|
| カバレッジ | S2より広い（2.5億+ works） |
| レート制限 | 事実上無制限（politeプール） |
| 機関情報 | 著者の所属機関データが充実 |
| オープン | 完全オープンデータ |

### 引用グラフの構築

```python
# S2から引用関係を取得
paper = s2_client.get_paper(paper_id)
references = paper.references      # この論文が引用している論文
citations = paper.citations        # この論文を引用している論文

# Evidence Graphに統合（ADR-0005参照）
for ref in references:
    graph.add_edge(
        from_node=paper.fragment_id,
        to_node=ref.fragment_id,
        edge_type="CITES",
        citation_source="s2"
    )
```

### フォールバック戦略

```python
async def get_paper_metadata(identifier: str) -> PaperMetadata:
    # 1. S2を試行
    try:
        return await s2_client.get_paper(identifier)
    except RateLimitError:
        await asyncio.sleep(backoff)
        # 2. OpenAlexにフォールバック
        return await openalex_client.get_work(identifier)
    except NotFoundError:
        # 3. DOI直接解決
        if is_doi(identifier):
            return await resolve_doi_metadata(identifier)
        raise
```

### プレプリントの扱い

| ソース | 査読状態 | 信頼度への影響 |
|--------|----------|----------------|
| arXiv | 未査読 | uncertaintyに反映（高め） |
| bioRxiv/medRxiv | 未査読 | uncertaintyに反映（高め） |
| 出版済みジャーナル | 査読済み | 通常通り |

```python
# メタデータに査読状態を記録
if paper.venue in ["arXiv", "bioRxiv", "medRxiv"]:
    paper.peer_reviewed = False
    paper.preprint = True
```

### APIクライアント設定

```python
# Semantic Scholar
S2_CONFIG = {
    "base_url": "https://api.semanticscholar.org/graph/v1",
    "rate_limit": 5000,  # per 5 minutes
    "rate_window": 300,
    "timeout": 30,
    "retry_count": 3
}

# OpenAlex
OPENALEX_CONFIG = {
    "base_url": "https://api.openalex.org",
    "polite_pool_email": "lyra@example.com",  # 設定必須
    "timeout": 30,
    "retry_count": 3
}
```

## Consequences

### Positive
- **Zero OpEx維持**: 両APIとも無料
- **高カバレッジ**: 2層で大半の学術論文をカバー
- **引用グラフ**: エビデンス関係の強化
- **冗長性**: 1つ障害でも継続可能

### Negative
- **API依存**: 外部サービス変更の影響を受ける
- **レート制限**: 大量取得時に待機が必要
- **データ品質**: 自動抽出データのため誤りあり

## Alternatives Considered

| Alternative | Pros | Cons | 判定 |
|-------------|------|------|------|
| Google Scholarスクレイピング | 最大カバレッジ | 規約違反リスク、不安定 | 却下 |
| Crossrefのみ | 安定 | 引用データ不十分 | 却下 |
| Scopus/WoS | 高品質 | 有料（Zero OpEx違反） | 却下 |
| PubMedのみ | 医学に強い | カバレッジ限定 | 却下 |

## References
- `docs/P_EVIDENCE_SYSTEM.md` 決定6（アーカイブ）
- `src/crawler/academic/s2_client.py` - Semantic Scholar実装
- `src/crawler/academic/openalex_client.py` - OpenAlex実装
- ADR-0005: Evidence Graph Structure
