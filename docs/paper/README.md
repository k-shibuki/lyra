## Papers in this repository

This repository currently contains **two active papers** under `docs/paper/`.

### 1) Lyra system paper (JOSS target)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18222598.svg)](https://doi.org/10.5281/zenodo.18222598)

- **Directory**: `docs/paper/lyra-system/`
- **Focus**: Lyra itself (local-first MCP server, evidence graph, NLI, architecture)
- **Target venue**: JOSS (planned submission around May 2026; not yet meeting submission criteria)
- **Entry point**: `paper.md`
- **Latest PDF (preprint)**: `preprint_20260112.pdf`

### 2) Experience Report (IEEE Software target)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18244548.svg)](https://doi.org/10.5281/zenodo.18244548)

- **Directory**: `docs/paper/experience-report/`
- **Focus**: Natural-language-first development governance (control plane vs data plane), ADRs/rules/commands/gates, zero human code inspection
- **Target venue**: IEEE Software (Experience Report)
- **Entry point**: `paper.md`
- **Latest PDF (preprint)**: `preprint_20260114.pdf`

### Notes

- These papers are intentionally separated because they target different venues and make different claims:
  - The **system paper** describes what Lyra is and how it works.
  - The **experience report** describes how Lyra was built under a constrained human capability model (cannot inspect implementation code).
