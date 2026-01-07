# Academic citation graph integration (paper_id contract)

This sequence diagram captures the cross-module integration between:

- Research pipeline (academic ingestion)
- Citation graph deferred job
- Evidence graph persistence (`edges.relation='cites'`)
- Citation chasing view (`v_reference_candidates`)

```mermaid
sequenceDiagram
  participant MCP as MCPClient
  participant JS as JobScheduler
  participant PL as ResearchPipeline
  participant AAP as AcademicSearchProvider
  participant DB as SQLiteDB
  participant CG as CitationGraphJob
  participant EG as EvidenceGraph

  MCP->>JS: queue_targets(kind=query/doi/url)
  JS->>PL: search_action / ingest_doi_action / ingest_url_action

  alt Academic(S2/OpenAlex/DOI)
    PL->>AAP: search()/get_paper_by_doi()
    AAP-->>PL: Paper(id=s2:... or openalex:..., doi, ...)
    PL->>DB: INSERT pages(paper_metadata=AcademicPageMetadata)
    Note over PL,DB: paper_metadata.paper_id = Paper.id (required)
    PL->>DB: INSERT fragments(abstract)
    PL->>CG: enqueue_citation_graph_job(paper_ids=[Paper.id...])
    CG->>DB: SELECT pages WHERE json_extract(paper_metadata,'$.paper_id') = paper_id
    CG->>AAP: get_citation_graph(paper_id)
    CG->>EG: add_academic_page_with_citations(..., paper_metadata.paper_id)
    EG->>DB: INSERT edges(relation=cites)
  else Web
    PL->>DB: fetch/extract
    PL->>DB: INSERT pages(html_path != null)
    PL->>EG: add_citation(source_page->target_page)
    EG->>DB: INSERT edges(relation=cites)
  end

  MCP->>DB: query_view(v_reference_candidates, task_id)
```


