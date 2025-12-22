# get_materialsフロー（問題3: エビデンスグラフ構築）

## 概要

MCPツール`get_materials`がCursor AIから呼び出された際の、claims/fragments/evidence_graphを取得するフロー。

## 仕様要件

- **§3.2.1**: `get_materials(task_id, options?)` → 調査成果物の取得
- **§3.4**: エビデンスグラフ - claims↔fragments↔pagesの関連付け

## 期待される出力スキーマ

```json
{
  "ok": true,
  "task_id": "task_abc123",
  "query": "元の問い",
  "claims": [
      {
        "id": "c_001",
        "text": "主張テキスト",
        "confidence": 0.92,
        "uncertainty": 0.12,
        "controversy": 0.08,
        "evidence_count": 3,
        "has_refutation": false,
        "sources": [
          {"url": "https://...", "title": "...", "is_primary": true}
        ]
      }
  ],
  "fragments": [
    {
      "id": "f_001",
      "text": "引用可能なテキスト断片",
      "source_url": "https://...",
      "context": "見出し > サブ見出し"
    }
  ],
  "evidence_graph": {
    "nodes": [...],
    "edges": [...]
  },
  "summary": {
    "total_claims": 18,
    "verified_claims": 12,
    "refuted_claims": 2,
    "primary_source_ratio": 0.65
  }
}
```

## デバッグ前のシーケンス図

```mermaid
sequenceDiagram
    participant CursorAI as Cursor AI
    participant MCPServer as _handle_get_materials()
    participant Action as get_materials_action()
    participant DB as SQLite DB
    participant Claims as _collect_claims()
    participant Fragments as _collect_fragments()
    participant Graph as _build_evidence_graph()

    CursorAI->>MCPServer: get_materials(task_id, options)
    MCPServer->>Action: get_materials_action(task_id, options)
    
    Note over Action,Claims: Step 1: Collect claims from DB
    Action->>Claims: _collect_claims(db, task_id)
    Claims->>DB: SELECT c.source_url FROM claims...
    Note over DB: ★ エラー: source_urlカラム不存在
    DB-->>Claims: ERROR: no such column: c.source_url
    Claims-->>Action: claims = []  (空配列)
    
    Note over Action,Fragments: Step 2: Collect fragments from DB
    Action->>Fragments: _collect_fragments(db, task_id)
    Fragments->>DB: SELECT text FROM fragments WHERE task_id = ?
    Note over DB: ★ エラー: textカラム不存在（text_contentが正しい）<br/>★ エラー: task_idカラム不存在
    DB-->>Fragments: ERROR: no such column: text
    Fragments-->>Action: fragments = []  (空配列)
    
    Note over Action,Graph: Step 3: Build evidence graph
    Action->>Graph: _build_evidence_graph(db, task_id)
    Graph->>DB: SELECT ... FROM fragments WHERE task_id = ?
    Note over DB: ★ エラー: fragmentsにtask_idカラム不存在
    DB-->>Graph: ERROR
    Graph-->>Action: evidence_graph = {nodes: [], edges: []}
    
    Action-->>MCPServer: {claims: [], fragments: [], evidence_graph: {nodes: [], edges: []}}
    MCPServer-->>CursorAI: Empty results
    Note over CursorAI: ★ 常に空のclaims/fragments
```

### 問題点

1. **_collect_claims() SQLエラー**: `c.source_url`カラムが存在しない（`verification_notes`に格納されている）
2. **_collect_fragments() SQLエラー**: 
   - `text`カラムが存在しない（`text_content`が正しい）
   - `task_id`カラムが存在しない（fragments → edges → claimsで辿る必要あり）
3. **_build_evidence_graph() SQLエラー**: 同様に`task_id`問題

---

## デバッグ後のシーケンス図（実装完了版）

**実装状況**: ✅ 実装完了・動作確認済み

**変更点**:
- `_collect_claims()`: `verification_notes`からsource_urlを抽出、`relevance_reason`からメタデータを抽出
- `_collect_fragments()`: `text_content`カラムを使用、claims→edges経由でfragmentsを取得
- `_build_evidence_graph()`: fallbackクエリをclaims→edges経由に変更

```mermaid
sequenceDiagram
    participant CursorAI as Cursor AI
    participant MCPServer as _handle_get_materials()
    participant Action as get_materials_action()
    participant DB as SQLite DB
    participant Claims as _collect_claims()
    participant Fragments as _collect_fragments()
    participant Graph as _build_evidence_graph()

    CursorAI->>MCPServer: get_materials(task_id, options)
    
    Note over MCPServer: Step 1: Validate task exists
    MCPServer->>DB: SELECT * FROM tasks WHERE id = ?
    DB-->>MCPServer: task row
    
    alt Task not found
        MCPServer-->>CursorAI: {"ok": false, "error": "task_not_found"}
    end
    
    MCPServer->>Action: get_materials_action(task_id, options)
    
    Note over Action,Claims: Step 2: Collect claims from DB
    Action->>Claims: _collect_claims(db, task_id)
    Claims->>DB: SELECT c.id, c.claim_text, c.confidence_score,<br/>c.verification_notes, c.source_fragment_ids,<br/>COUNT(DISTINCT e.id) as evidence_count...
    Note over DB: ✓ O.7修正: verification_notesから<br/>source_urlを抽出
    DB-->>Claims: claim rows
    
    loop For each claim
        Claims->>DB: SELECT f.relevance_reason, f.heading_context<br/>FROM fragments f JOIN edges e...
        Note over DB: ✓ O.7修正: relevance_reasonから<br/>is_primary, urlを抽出
        DB-->>Claims: source info
        Claims->>Claims: Parse verification_notes for source_url
        Claims->>Claims: Parse relevance_reason for is_primary
    end
    Claims-->>Action: claims[] with sources
    
    Note over Action,Fragments: Step 3: Collect fragments from DB
    Action->>Fragments: _collect_fragments(db, task_id)
    Fragments->>DB: SELECT DISTINCT f.id, f.text_content, f.heading_context,<br/>f.relevance_reason FROM fragments f<br/>JOIN edges e ON e.source_id = f.id<br/>JOIN claims c ON e.target_id = c.id<br/>WHERE c.task_id = ?
    Note over DB: ✓ O.7修正: claims→edges経由で取得<br/>✓ text_contentカラム使用
    DB-->>Fragments: fragment rows
    
    loop For each fragment
        Fragments->>Fragments: Parse relevance_reason for url, is_primary
    end
    Fragments-->>Action: fragments[] with metadata
    
    Note over Action,Graph: Step 4: Build evidence graph (if include_graph=true)
    Action->>Graph: _build_evidence_graph(db, task_id)
    
    alt EvidenceGraph module available
        Graph->>Graph: EvidenceGraph(task_id)
        Graph->>DB: load_from_db(task_id)
        DB-->>Graph: edges data
        Graph->>Graph: to_dict()
    else Fallback to direct query
        Graph->>DB: SELECT id, claim_text FROM claims WHERE task_id = ?
        DB-->>Graph: claim nodes
        Graph->>DB: SELECT DISTINCT f.id, f.heading_context<br/>FROM fragments f JOIN edges e...<br/>JOIN claims c... WHERE c.task_id = ?
        Note over DB: ✓ O.7修正: claims経由で取得
        DB-->>Graph: fragment nodes
        Graph->>DB: SELECT * FROM edges WHERE target_id IN (...) OR source_id IN (...)
        DB-->>Graph: edge data
    end
    Graph-->>Action: evidence_graph {nodes: [...], edges: [...]}
    
    Note over Action: Step 5: Calculate summary
    Action->>Action: Count verified/refuted claims
    Action->>Action: Calculate primary_source_ratio
    
    Action-->>MCPServer: materials dict
    MCPServer-->>CursorAI: {claims: [...], fragments: [...], evidence_graph: {...}}
    Note over CursorAI: ✓ 正しいデータを取得
```

## 修正内容

### 1. _collect_claims() の修正

```python
# Before (問題あり)
rows = await db.fetch_all(
    """SELECT c.id, c.claim_text, c.confidence_score, c.source_url, ...
    FROM claims c WHERE c.task_id = ?"""
)
# ★ source_urlカラムが存在しない

# After (O.7修正)
rows = await db.fetch_all(
    """SELECT c.id, c.claim_text, c.confidence_score, 
       c.verification_notes, c.source_fragment_ids, ...
    FROM claims c WHERE c.task_id = ?"""
)
# verification_notesからsource_urlを抽出
if "source_url=" in verification_notes:
    source_url = verification_notes.split("source_url=")[1].split(";")[0]
```

### 2. _collect_fragments() の修正

```python
# Before (問題あり)
rows = await db.fetch_all(
    """SELECT id, text, source_url, title, ...
    FROM fragments WHERE task_id = ?"""
)
# ★ text → text_content, task_idカラム不存在

# After (O.7修正)
rows = await db.fetch_all(
    """SELECT DISTINCT f.id, f.text_content, f.heading_context, f.relevance_reason
    FROM fragments f
    JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
    JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
    WHERE c.task_id = ?"""
)
# relevance_reasonからurl, is_primaryを抽出
```

### 3. _build_evidence_graph() の修正

```python
# Before (問題あり)
fragment_rows = await db.fetch_all(
    "SELECT id, 'fragment' as type, source_url as label FROM fragments WHERE task_id = ?",
)
# ★ fragmentsにtask_idカラム不存在

# After (O.7修正)
fragment_rows = await db.fetch_all(
    """SELECT DISTINCT f.id, 'fragment' as type, f.heading_context as label
    FROM fragments f
    JOIN edges e ON e.source_id = f.id AND e.source_type = 'fragment'
    JOIN claims c ON e.target_id = c.id AND e.target_type = 'claim'
    WHERE c.task_id = ?"""
)
```

## 検証スクリプト

`tests/scripts/debug_get_materials_flow.py`

## 関連ファイル

| ファイル | 行番号 | 役割 |
|----------|--------|------|
| `src/mcp/server.py` | L930-968 | MCPハンドラ |
| `src/research/materials.py` | L18-89 | get_materials_action |
| `src/research/materials.py` | L92-160 | _collect_claims (O.7修正) |
| `src/research/materials.py` | L163-216 | _collect_fragments (O.7修正) |
| `src/research/materials.py` | L219-290 | _build_evidence_graph (O.7修正) |
