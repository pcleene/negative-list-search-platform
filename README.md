# Negative-List Screening — MongoDB Atlas as a Unified Search Platform

> **Sanctions / negative-list screening where full-text search, semantic vector search, pagination, and faceting all run on a single Atlas collection — no ETL between systems.**
> Sanitized public version of a real-world prototype — client names, credentials, and internal endpoints removed; all configuration is environment-driven (`.env.example`). Authored by [Paul Cleenewerck](https://github.com/pcleene).

## Context

Financial institutions screen customers and counterparties against negative lists and watchlists. Traditionally this means a search engine *plus* a vector database *plus* the system of record, glued together with pipelines. This project shows the whole capability on **one database, one collection, one document per entity** — Atlas provides fuzzy full-text search, semantic vector search, pagination, faceting, and flexible enrichment on the same data.

## Architecture

```mermaid
flowchart LR
    UI[SvelteKit screening UI] --> API[FastAPI - async PyMongo]
    API --> ATLAS[(MongoDB Atlas<br/>negative_list collection)]
    subgraph One collection, many capabilities
      ATLAS --> FTS[Atlas Search<br/>fuzzy + analyzers]
      ATLAS --> VEC[Vector Search<br/>semantic similarity]
      ATLAS --> FACET[faceting + pagination]
    end
    FTS --> API
    VEC --> API
    FACET --> API
```

## What this demonstrates

- **Single source of truth** — each entity is one rich document (identity, aliases, accounts, watchlist reasons, audit trail, and an embedding vector), eliminating cross-system sync.
- **Fuzzy name matching** — Atlas Search with custom analyzers handles aliases, transliterations, and typos — the realities of name screening.
- **Hybrid retrieval** — combine keyword search with semantic vector similarity to catch near-matches that exact search misses.
- **Production access pattern** — native async PyMongo (`AsyncMongoClient`) with **X.509 certificate** authentication.
- **Search UX** — pagination and faceting served directly from the same collection.

## Tech stack

FastAPI (async PyMongo) · SvelteKit · MongoDB Atlas Search · Atlas Vector Search · X.509 TLS auth

## Quick start

```bash
cp .env.example .env            # add your Atlas URI + X.509 cert path
cd negative-list-app/backend && pip install -r requirements.txt && uvicorn main:app --reload
cd negative-list-app/frontend && npm install && npm run dev
```

See `Implementation_Guide.md` for a step-by-step build with real code (connection, document model, search indexes, vector search).

## Author

[Paul Cleenewerck](https://github.com/pcleene) — MongoDB-focused solution architecture and hands-on prototyping.

## License

See `LICENSE`. If no license file is present, contact the author before reuse.
