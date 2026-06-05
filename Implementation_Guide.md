# MB Negative List — Implementation Guide

**MongoDB Atlas as a Unified Search Platform**
Prepared by Paul Cleenewerck, Regional Solutions Architect — MongoDB

---

## The Core Idea

Everything lives in **one database, one collection, one document per entity**. MongoDB Atlas provides full-text search, semantic vector search, pagination, faceting, and flexible schema enrichment — all on the same data, with no ETL pipelines between systems and no schema migrations when requirements change.

This guide walks through the implementation step by step, with real code.

---

## Step 1 — Connect to MongoDB Atlas

We use PyMongo's native async client (Motor is deprecated). Authentication is via X.509 TLS certificate — the same pattern used across all MB demo environments.

```python
from pymongo import AsyncMongoClient

MONGODB_URI = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
TLS_CERT_PATH = "/path/to/X509-cert.pem"
DB_NAME = "mb_negative_list"

_client: AsyncMongoClient | None = None
_db = None

async def connect():
    global _client, _db
    _client = AsyncMongoClient(
        MONGODB_URI,
        tls=True,
        tlsCertificateKeyFile=TLS_CERT_PATH,
    )
    await _client.admin.command("ping")  # verify connection
    _db = _client[DB_NAME]
    print("Connected to MongoDB Atlas")

def get_db():
    assert _db is not None, "Call connect() first"
    return _db
```

One connection. One database. Everything that follows operates on a single collection called `negative_list`.

---

## Step 2 — The Document Model

Each document in `negative_list` is a complete profile: identity, banking relationship, negative/blacklist reasons, watchlist sources, audit trail, and an AI embedding vector — all in one place.

```json
{
  "entityId": "MB-NEG-000001",
  "entityType": "person",

  "fullName": "Maria Cristina Dela Cruz Santos",
  "aliases": ["Ma. Cristina D. Santos", "MC Santos"],
  "dateOfBirth": "1985-07-15T00:00:00Z",

  "identifiers": {
    "nationalId": "1234-5678-9012",
    "tin": "123-456-789-000",
    "sssNo": "12-3456789-0",
    "passportNo": "P1234567A"
  },

  "accounts": [
    {
      "type": "savings",
      "number": "1234-5678-90",
      "productName": "MB Save-Up",
      "status": "closed",
      "branch": "Makati Main",
      "lastBalance": 1250.00
    },
    {
      "type": "credit_card",
      "number": "****4821",
      "productName": "MB Gold Mastercard",
      "status": "cancelled",
      "creditLimit": 200000.00,
      "outstandingBalance": 125000.00
    }
  ],

  "loans": [
    {
      "type": "personal",
      "loanId": "PL-2021-00456",
      "productName": "MB Personal Loan",
      "principalAmount": 500000.00,
      "outstandingBalance": 450000.00,
      "status": "defaulted",
      "missedPayments": 6
    }
  ],

  "relationship": {
    "customerId": "MB-CUS-000001",
    "since": "2018-06-15T00:00:00Z",
    "tier": "gold",
    "branch": "Makati Main",
    "relationshipManager": "Juan D. Reyes",
    "status": "blacklisted"
  },

  "negativeReasons": [
    {
      "code": "LOAN_DEFAULT",
      "description": "Defaulted on personal loan",
      "amount": 450000.00,
      "currency": "PHP",
      "dateRecorded": "2023-11-20T00:00:00Z",
      "productType": "Personal Loan",
      "status": "unresolved"
    },
    {
      "code": "CC_CANCELLED",
      "description": "Credit card cancelled — non-payment",
      "amount": 125000.00,
      "currency": "PHP",
      "dateRecorded": "2024-02-10T00:00:00Z",
      "productType": "Credit Card",
      "status": "unresolved"
    }
  ],

  "riskTags": ["loan_default", "cc_nonpayment", "repeat_offender"],
  "riskScore": 0.87,

  "watchlistSources": [
    { "source": "MB Internal", "category": "Loan Default", "isActive": true },
    { "source": "AMLC", "category": "Suspicious Transaction", "isActive": true }
  ],

  "auditTrail": [
    {
      "action": "added_to_negative_list",
      "performedBy": "SYSTEM_CDC",
      "timestamp": "2023-11-20T08:30:00Z",
      "notes": "Auto-ingested from mainframe batch"
    }
  ],

  "embedding": [0.0123, -0.0456, ...],

  "isActive": true,
  "sourceSystem": "IBM_MAINFRAME_DB2"
}
```

Why this matters: a branch officer searching "Maria Santos" gets identity, banking, blacklist reasons, outstanding balances, and audit history in **one query, one round-trip, one document**. No joins. No cross-table lookups. No stored procedures.

---

## Step 3 — Custom Filipino Name Analyzer

Filipino names have specific patterns that break exact matching. We build a custom Atlas Search analyzer that handles them at index time.

```python
FILIPINO_NAME_ANALYZER = {
    "name": "filipino_name_analyzer",
    "charFilters": [
        {
            "type": "mapping",
            "mappings": {
                # Surname particles — strip to space so core tokens match
                # "Dela Cruz" ≈ "De la Cruz" ≈ "Cruz"
                " dela ": " ", " Dela ": " ", " DELA ": " ",
                " de la ": " ", " De La ": " ", " DE LA ": " ", " De la ": " ",
                " de los ": " ", " De Los ": " ", " DE LOS ": " ",
                " del ": " ", " Del ": " ", " DEL ": " ",
                " delos ": " ", " Delos ": " ", " DELOS ": " ",
                " de ": " ", " De ": " ", " DE ": " ",

                # "Ma." → "Maria" — universal Filipino abbreviation
                "Ma. ": "Maria ", "ma. ": "maria ", "MA. ": "MARIA ",

                # Generational suffixes — noise for matching
                " Jr.": "", " jr.": "", " JR.": "",
                " Sr.": "", " sr.": "", " SR.": "",
                " III": "", " II": "", " IV": "",
            },
        }
    ],
    "tokenizer": {"type": "standard"},
    "tokenFilters": [{"type": "lowercase"}],
}
```

The charFilter mappings need three casings (lower, Title, UPPER) because they run **before** the lowercase token filter. Atlas Search doesn't offer a lowercase charFilter — only a lowercase token filter, which fires after tokenization.

Deliberately not expanded: "Jo." (ambiguous — Jo is a standalone name), "Sto."/"Sta." (place prefixes, not person names). We let fuzzy matching handle those.

---

## Step 4 — Atlas Search Index (Full-Text Fuzzy)

This index enables fuzzy text matching on names, aliases, and ID fields. Created on the `negative_list` collection.

```python
NEGATIVE_LIST_FUZZY_INDEX = {
    "name": "negative_list_fuzzy",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "fullName": [
                    {
                        "type": "string",
                        "analyzer": "filipino_name_analyzer",
                        "searchAnalyzer": "filipino_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "filipino_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 20,
                    },
                ],
                "aliases": [
                    {
                        "type": "string",
                        "analyzer": "filipino_name_analyzer",
                        "searchAnalyzer": "filipino_name_analyzer",
                    },
                    {
                        "type": "autocomplete",
                        "analyzer": "filipino_name_analyzer",
                        "tokenization": "edgeGram",
                        "minGrams": 2,
                        "maxGrams": 20,
                    },
                ],
                "identifiers.nationalId": [
                    {"type": "string"},
                    {"type": "autocomplete", "tokenization": "edgeGram",
                     "minGrams": 3, "maxGrams": 20}
                ],
                "identifiers.tin": [
                    {"type": "string"},
                    {"type": "autocomplete", "tokenization": "edgeGram",
                     "minGrams": 3, "maxGrams": 20}
                ],
                "dateOfBirth": {"type": "date"},
                "negativeReasons.code": {"type": "stringFacet"},
                "watchlistSources.source": {"type": "stringFacet"},
                "riskScore": {"type": "number"},
                "isActive": {"type": "boolean"},
            },
        },
        "analyzers": [FILIPINO_NAME_ANALYZER],
    },
}
```

Note the `stringFacet` type on `negativeReasons.code` and `watchlistSources.source`. This is what enables faceted search in Step 7.

---

## Step 5 — Atlas Vector Search Index (Semantic)

Same collection, second index. This one operates on the `embedding` field — a 1024-dimensional vector generated by Voyage AI.

```json
{
  "name": "negative_list_vector",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1024,
        "similarity": "cosine"
      },
      { "type": "filter", "path": "isActive" },
      { "type": "filter", "path": "entityType" }
    ]
  }
}
```

Two indexes, one collection. No data duplication. No sync jobs.

---

## Step 6 — Fuzzy Search Query

The core search query uses `$search` with a `compound` clause. It searches `fullName` (boosted 3x), `aliases` (boosted 2x), and optionally identifiers (boosted 5x). Fuzzy matching allows up to 2 character edits (Levenshtein distance).

```python
async def search_fuzzy(
    name: str,
    national_id: str | None = None,
    dob: str | None = None,
    max_edits: int = 2,
    limit: int = 10,
) -> list[dict]:
    db = get_db()

    should_clauses = [
        {
            "text": {
                "query": name,
                "path": "fullName",
                "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                "score": {"boost": {"value": 3}},
            }
        },
        {
            "text": {
                "query": name,
                "path": "aliases",
                "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                "score": {"boost": {"value": 2}},
            }
        },
    ]

    if national_id:
        should_clauses.append({
            "text": {
                "query": national_id,
                "path": "identifiers.nationalId",
                "score": {"boost": {"value": 5}},
            }
        })

    compound = {
        "should": should_clauses,
        "minimumShouldMatch": 1,
    }

    if dob:
        compound["filter"] = [
            {"equals": {"path": "dateOfBirth", "value": datetime.fromisoformat(dob)}}
        ]

    pipeline = [
        {"$search": {"index": "negative_list_fuzzy", "compound": compound}},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
        {"$limit": limit},
        {"$project": {"embedding": 0}},
    ]

    results = []
    async for doc in db.negative_list.aggregate(pipeline):
        results.append(doc)
    return results
```

This handles:

- "Ma. Cristina" matching "Maria Cristina" (analyzer expansion)
- "Dela Cruz" matching "De la Cruz" (particle stripping)
- "Crsitina" matching "Cristina" (fuzzy edit distance)
- National ID lookup with 5x score boost (exact identifiers trump name similarity)
- Optional date-of-birth filtering (hard filter, not fuzzy)

---

## Step 7 — Faceted Search (Same Query)

Atlas Search supports faceting within the same `$search` stage. This lets us return both results and breakdown counts in a single aggregation.

```python
async def search_with_facets(
    name: str,
    max_edits: int = 2,
    limit: int = 10,
) -> dict:
    db = get_db()

    pipeline = [
        {
            "$searchMeta": {
                "index": "negative_list_fuzzy",
                "facet": {
                    "operator": {
                        "compound": {
                            "should": [
                                {
                                    "text": {
                                        "query": name,
                                        "path": "fullName",
                                        "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                                    }
                                },
                                {
                                    "text": {
                                        "query": name,
                                        "path": "aliases",
                                        "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                                    }
                                },
                            ],
                            "minimumShouldMatch": 1,
                        }
                    },
                    "facets": {
                        "byReason": {
                            "type": "string",
                            "path": "negativeReasons.code",
                        },
                        "bySource": {
                            "type": "string",
                            "path": "watchlistSources.source",
                        },
                    },
                },
            }
        }
    ]

    async for doc in db.negative_list.aggregate(pipeline):
        return doc

    return {}
```

The response looks like:

```json
{
  "count": { "lowerBound": 47 },
  "facet": {
    "byReason": {
      "buckets": [
        { "_id": "LOAN_DEFAULT", "count": 28 },
        { "_id": "CC_CANCELLED", "count": 12 },
        { "_id": "FRAUD_CONFIRMED", "count": 5 },
        { "_id": "AML_FLAG", "count": 2 }
      ]
    },
    "bySource": {
      "buckets": [
        { "_id": "MB Internal", "count": 35 },
        { "_id": "AMLC", "count": 8 },
        { "_id": "BSP", "count": 4 }
      ]
    }
  }
}
```

One query. Results + facet breakdowns. No separate aggregation pipeline, no application-side counting.

---

## Step 8 — Semantic Search Query

When the user toggles to semantic mode, we generate an embedding from the query text using Voyage AI, then run `$vectorSearch` on the same collection.

```python
import httpx

VOYAGE_API_KEY = "<voyage-key>"

async def generate_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {VOYAGE_API_KEY}"},
            json={
                "input": [text],
                "model": "voyage-4-large",
                "input_type": "query",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def search_semantic(query: str, limit: int = 10) -> list[dict]:
    db = get_db()
    query_embedding = await generate_embedding(query)

    pipeline = [
        {
            "$vectorSearch": {
                "index": "negative_list_vector",
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": limit * 10,
                "limit": limit,
                "filter": {"isActive": True},
            }
        },
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = []
    async for doc in db.negative_list.aggregate(pipeline):
        results.append(doc)
    return results
```

This is on the **same collection** as the fuzzy search. Same documents. Same indexes coexist. The only difference is which `$search` operator the aggregation pipeline uses.

---

## Step 9 — Pagination with Atlas Search

Atlas Search supports cursor-based pagination using `$skip` and `$limit` in the aggregation pipeline, and also `searchAfter` for deep pagination.

For standard pagination (works well up to ~10,000 results):

```python
async def search_paginated(
    name: str,
    page: int = 1,
    page_size: int = 20,
    max_edits: int = 2,
) -> dict:
    db = get_db()
    skip = (page - 1) * page_size

    pipeline = [
        {
            "$search": {
                "index": "negative_list_fuzzy",
                "compound": {
                    "should": [
                        {
                            "text": {
                                "query": name,
                                "path": "fullName",
                                "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                            }
                        }
                    ],
                    "minimumShouldMatch": 1,
                },
                "count": {"type": "total"},
            }
        },
        {"$addFields": {"score": {"$meta": "searchScore"}}},
        {"$skip": skip},
        {"$limit": page_size},
        {"$project": {"embedding": 0}},
    ]

    # Get total count via $searchMeta in parallel
    count_pipeline = [
        {
            "$searchMeta": {
                "index": "negative_list_fuzzy",
                "count": {
                    "type": "total",
                },
                "compound": {
                    "should": [
                        {
                            "text": {
                                "query": name,
                                "path": "fullName",
                                "fuzzy": {"maxEdits": max_edits, "prefixLength": 1},
                            }
                        }
                    ],
                    "minimumShouldMatch": 1,
                },
            }
        }
    ]

    results = []
    async for doc in db.negative_list.aggregate(pipeline):
        results.append(doc)

    total = 0
    async for meta in db.negative_list.aggregate(count_pipeline):
        total = meta.get("count", {}).get("total", 0)

    return {
        "results": results,
        "page": page,
        "pageSize": page_size,
        "totalResults": total,
        "totalPages": (total + page_size - 1) // page_size,
    }
```

---

## Step 10 — Embedding Generation for Ingestion

When a new entry is added to the negative list (via CDC from mainframe or manual entry), we generate an embedding that captures the full profile — not just the name, but the banking relationship, negative reasons, and risk context.

```python
def serialize_for_embedding(doc: dict) -> str:
    """Convert a negative list document into text for Voyage AI."""
    parts = [
        f"Name: {doc.get('fullName', '')}",
        f"Aliases: {', '.join(doc.get('aliases', []))}",
        f"Entity Type: {doc.get('entityType', '')}",
    ]

    rel = doc.get("relationship", {})
    if rel:
        parts.append(
            f"Customer: {rel.get('segment', '')} segment, "
            f"{rel.get('tier', '')} tier, branch {rel.get('branch', '')}"
        )

    for acct in doc.get("accounts", []):
        parts.append(
            f"Account: {acct.get('type', '')} — "
            f"{acct.get('productName', '')} — status {acct.get('status', '')}"
        )

    for loan in doc.get("loans", []):
        parts.append(
            f"Loan: {loan.get('productName', '')} — "
            f"PHP {loan.get('outstandingBalance', 0):,.2f} outstanding — "
            f"{loan.get('missedPayments', 0)} missed payments"
        )

    for reason in doc.get("negativeReasons", []):
        parts.append(
            f"Negative: {reason.get('description', '')} — "
            f"PHP {reason.get('amount', 0):,.2f} — {reason.get('status', '')}"
        )

    for src in doc.get("watchlistSources", []):
        parts.append(f"Watchlist: {src.get('source', '')} — {src.get('category', '')}")

    tags = doc.get("riskTags", [])
    if tags:
        parts.append(f"Risk tags: {', '.join(tags)}")

    return " | ".join(parts)


async def backfill_embeddings():
    """Generate embeddings for all entries that don't have one yet."""
    db = get_db()
    cursor = db.negative_list.find(
        {"embedding": {"$exists": False}},
        {"embedding": 0},
    )

    count = 0
    async for doc in cursor:
        text = serialize_for_embedding(doc)
        embedding = await generate_embedding(text)
        await db.negative_list.update_one(
            {"_id": doc["_id"]},
            {"$set": {"embedding": embedding}},
        )
        count += 1

    return {"embeddingsGenerated": count}
```

---

## Step 11 — Enriching the Document (No Migration Required)

This is where MongoDB's flexible document model shines. When MB wants to add new fields to the negative list — device fingerprints, AFASA attributes, behavioral signals — it's just an `$set` operation. No schema migration. No downtime. No ALTER TABLE.

```python
# Adding device fingerprints to an existing entry
await db.negative_list.update_one(
    {"entityId": "MB-NEG-000001"},
    {
        "$set": {
            "deviceFingerprints": [
                {
                    "deviceId": "fp-abc123",
                    "type": "mobile",
                    "os": "iOS 17.2",
                    "lastSeenAt": datetime.now(timezone.utc),
                    "trustScore": 0.3,
                }
            ]
        }
    },
)

# Adding AFASA-specific attributes
await db.negative_list.update_one(
    {"entityId": "MB-NEG-000001"},
    {
        "$set": {
            "afasa": {
                "riskCategory": "high",
                "assessmentDate": datetime.now(timezone.utc),
                "assessedBy": "COMPLIANCE_TEAM",
                "findings": "Multiple indicators of structured transactions",
            }
        }
    },
)

# Adding a new watchlist source — just push to the array
await db.negative_list.update_one(
    {"entityId": "MB-NEG-000001"},
    {
        "$push": {
            "watchlistSources": {
                "source": "BAP",
                "category": "Industry Blacklist",
                "addedAt": datetime.now(timezone.utc),
                "isActive": True,
            }
        },
        "$push": {
            "auditTrail": {
                "action": "watchlist_added",
                "performedBy": "COMPLIANCE_TEAM",
                "timestamp": datetime.now(timezone.utc),
                "notes": "Added to BAP industry blacklist",
            }
        },
    },
)
```

The document grows as the business needs grow. Old documents without the new fields continue to work. New documents include them. The search indexes pick up new searchable fields when you add them to the index definition — also with zero downtime.

---

## Step 12 — The FastAPI Endpoints

Tying it all together into a clean API:

```python
from fastapi import FastAPI, Query
from enum import Enum

app = FastAPI(title="MB Negative List Search")

class SearchMode(str, Enum):
    fuzzy = "fuzzy"
    semantic = "semantic"

@app.get("/api/negative-list/search")
async def search(
    q: str,
    mode: SearchMode = SearchMode.fuzzy,
    max_edits: int = Query(2, ge=0, le=2),
    limit: int = Query(10, ge=1, le=50),
    dob: str | None = None,
    national_id: str | None = None,
    page: int = Query(1, ge=1),
):
    start = time.perf_counter()

    if mode == SearchMode.fuzzy:
        results = await search_fuzzy(q, national_id, dob, max_edits, limit)
        pipeline_used = "Atlas Search — $search with compound fuzzy"
    else:
        results = await search_semantic(q, limit)
        pipeline_used = "Atlas Vector Search — $vectorSearch with cosine similarity"

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    return {
        "_meta": {
            "searchMode": mode,
            "pipeline": pipeline_used,
            "executionTimeMs": elapsed_ms,
            "resultsCount": len(results),
        },
        "results": results,
    }

@app.get("/api/negative-list/profile/{entity_id}")
async def get_profile(entity_id: str):
    start = time.perf_counter()
    db = get_db()

    doc = await db.negative_list.find_one(
        {"entityId": entity_id},
        {"embedding": 0},
    )

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

    return {
        "_meta": {
            "query": {"entityId": entity_id},
            "executionTimeMs": elapsed_ms,
        },
        "profile": doc,
    }
```

Every response includes `_meta` with the query details and execution time — so the client can see exactly what ran and how fast.

---

## What This Proves to MB

| Capability | How MongoDB Delivers It |
|---|---|
| **Fuzzy name matching** | Atlas Search with custom Filipino name analyzer — handles "Ma. Cristina Dela Cruz" ≈ "Maria Cristina De la Cruz" |
| **Semantic matching** | Atlas Vector Search with Voyage AI embeddings — conceptual similarity, not just characters |
| **Sub-20ms performance** | Replaces seconds-per-query mainframe bottleneck |
| **Zero MIPS** | All search traffic offloaded to Atlas — mainframe stays on the ledger |
| **Faceted search** | `$searchMeta` with `facet` operator — breakdown by reason code, watchlist source, in the same query |
| **Pagination** | `$skip`/`$limit` in the aggregation pipeline, with `count.type: "total"` for total results |
| **Flexible schema** | Add fields anytime with `$set` — no migration, no downtime, no ALTER TABLE |
| **Single view** | One document = identity + banking + blacklist + audit trail — one query returns everything |
| **Audit trail** | `$push` to append to the `auditTrail` array — immutable history inside the document |
| **Compliance-ready** | Similarity scores and reason codes give regulators a clear, explainable defense |

---

## Architecture Summary

```
IBM Mainframe (DB2)          MongoDB Atlas (EDC)           Consumers
┌──────────────────┐   CDC   ┌───────────────────────┐     ┌──────────────┐
│                  │ ──────> │  negative_list         │     │ Branches     │
│  System of       │  batch  │  ┌─────────────────┐   │ API │ Mobile       │
│  Record          │         │  │ Atlas Search     │   │ ──> │ Internal     │
│                  │         │  │ (fuzzy index)    │   │     │ Compliance   │
│  DB2 tables      │         │  ├─────────────────┤   │     └──────────────┘
│  (negative list) │         │  │ Vector Search    │   │
│                  │         │  │ (semantic index) │   │
└──────────────────┘         │  └─────────────────┘   │
                             │  One collection.        │
                             │  Two indexes.            │
                             │  Flexible documents.     │
                             └───────────────────────────┘
```

Mainframe stays as the system of record. MongoDB Atlas is the Enterprise Data Cache (EDC) that handles all interactive search. All channels call the API on top of Atlas, not DB2.
