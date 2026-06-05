import json
import time
from datetime import datetime

import httpx
from bson import ObjectId
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from backend.config import settings
from backend.services.pagination import (
    build_filter_clauses,
    build_search_pipeline,
    execute_paginated_search,
)

# ── Atlas Search Index Definitions ────────────────────────────────

FILIPINO_NAME_ANALYZER = {
    "name": "filipino_name_analyzer",
    "charFilters": [
        {
            "type": "mapping",
            "mappings": {
                # Surname particles — three casings each
                " dela ": " ", " Dela ": " ", " DELA ": " ",
                " de la ": " ", " De La ": " ", " DE LA ": " ", " De la ": " ",
                " de los ": " ", " De Los ": " ", " DE LOS ": " ", " De los ": " ",
                " del ": " ", " Del ": " ", " DEL ": " ",
                " delos ": " ", " Delos ": " ", " DELOS ": " ",
                " de ": " ", " De ": " ", " DE ": " ",
                # "Ma." → "Maria"
                "Ma. ": "Maria ", "ma. ": "maria ", "MA. ": "MARIA ",
                # Generational suffixes — strip
                " Jr.": "", " jr.": "", " JR.": "", " JR": "",
                " Sr.": "", " sr.": "", " SR.": "", " SR": "",
                " III": "", " II": "", " IV": "",
            },
        }
    ],
    "tokenizer": {"type": "standard"},
    "tokenFilters": [{"type": "lowercase"}],
}

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
                    {
                        "type": "autocomplete",
                        "tokenization": "edgeGram",
                        "minGrams": 3,
                        "maxGrams": 20,
                    },
                ],
                "identifiers.tin": [
                    {"type": "string"},
                    {
                        "type": "autocomplete",
                        "tokenization": "edgeGram",
                        "minGrams": 3,
                        "maxGrams": 20,
                    },
                ],
                "dateOfBirth": {"type": "date"},
                # Facet / filter fields — stringFacet needed for faceting
                # NOTE: negativeReasonCodes & watchlistSourceNames are
                # denormalized flat string arrays (Atlas Search cannot facet
                # on dotted paths through arrays of embedded documents).
                "entityType": [{"type": "token"}, {"type": "stringFacet"}],
                "isActive": {"type": "boolean"},
                "riskScore": [{"type": "number"}, {"type": "numberFacet"}],
                "riskTags": {"type": "token"},
                "negativeReasonCodes": [{"type": "token"}, {"type": "stringFacet"}],
                "watchlistSourceNames": [{"type": "token"}, {"type": "stringFacet"}],
                "relationship": {
                    "type": "document",
                    "fields": {
                        "branch": [{"type": "token"}, {"type": "stringFacet"}],
                        "tier": [{"type": "token"}, {"type": "stringFacet"}],
                        "segment": [{"type": "token"}, {"type": "stringFacet"}],
                    },
                },
            },
        },
        "analyzers": [FILIPINO_NAME_ANALYZER],
    },
}

NEGATIVE_LIST_VECTOR_INDEX = {
    "name": "negative_list_vector",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "isActive"},
            {"type": "filter", "path": "entityType"},
            {"type": "filter", "path": "riskScore"},
        ]
    },
}


# ── Helpers ───────────────────────────────────────────────────────


def serialize_doc(doc: dict) -> dict:
    """Recursively convert ObjectId and datetime for JSON serialization."""
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            serialize_doc(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    serialize_doc(item)
    return doc


def make_response(
    data: dict | list,
    *,
    query: dict = None,
    pipeline: list = None,
    index: str = None,
    search_mode: str = None,
    collection: str = "negative_list",
    start_time: float,
) -> dict:
    """Wrap API response with query metadata for 'Show Query' feature."""
    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
    meta = {"executionTimeMs": elapsed_ms, "collection": collection}
    if query:
        meta["query"] = query
    if pipeline:
        meta["pipeline"] = pipeline
    if index:
        meta["index"] = index
    if search_mode:
        meta["searchMode"] = search_mode
    if isinstance(data, list):
        meta["resultsCount"] = len(data)
        return {"_meta": meta, "results": data}
    else:
        meta["documentSizeBytes"] = len(json.dumps(data, default=str).encode())
        return {"_meta": meta, "profile": data}


def serialize_for_embedding(doc: dict) -> str:
    """Convert a negative list document into rich text for Voyage AI embedding."""
    parts = [
        f"Name: {doc.get('fullName', '')}",
        f"Aliases: {', '.join(doc.get('aliases', []))}",
        f"Entity Type: {doc.get('entityType', '')}",
    ]

    rel = doc.get("relationship", {})
    if rel:
        parts.append(
            f"Customer: {rel.get('segment', '')} segment, "
            f"{rel.get('tier', '')} tier, "
            f"branch {rel.get('branch', '')}, "
            f"status {rel.get('status', '')}"
        )

    for acct in doc.get("accounts", []):
        parts.append(
            f"Account: {acct.get('type', '')} — {acct.get('productName', '')} — "
            f"status {acct.get('status', '')}"
        )

    for loan in doc.get("loans", []):
        parts.append(
            f"Loan: {loan.get('productName', '')} — "
            f"PHP {loan.get('outstandingBalance', 0):,.2f} outstanding — "
            f"status {loan.get('status', '')} — "
            f"{loan.get('missedPayments', 0)} missed payments"
        )

    for reason in doc.get("negativeReasons", []):
        parts.append(
            f"Negative: {reason.get('description', '')} — "
            f"{reason.get('productType', '')} — "
            f"PHP {reason.get('amount', 0):,.2f} — "
            f"Status: {reason.get('status', '')}"
        )

    for src in doc.get("watchlistSources", []):
        parts.append(f"Watchlist: {src.get('source', '')} — {src.get('category', '')}")

    tags = doc.get("riskTags", [])
    if tags:
        parts.append(f"Risk tags: {', '.join(tags)}")

    addr = doc.get("addresses", [{}])[0] if doc.get("addresses") else {}
    if addr:
        parts.append(f"Location: {addr.get('city', '')}, {addr.get('province', '')}")

    return " | ".join(parts)


# ── Service ───────────────────────────────────────────────────────


class NegativeListService:
    def __init__(self, db: AsyncDatabase):
        self.db = db
        self.negative_list: AsyncCollection = db["negative_list"]
        self.voyage_api_key = settings.voyage_api_key

    # ── Embedding ─────────────────────────────────────────────

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a 1024-dim embedding via Voyage AI."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.voyage_endpoint,
                headers={"Authorization": f"Bearer {self.voyage_api_key}"},
                json={
                    "input": [text],
                    "model": settings.voyage_model,
                    "input_type": "query",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

    # ── Fuzzy Search ──────────────────────────────────────────

    async def search_fuzzy(
        self,
        name: str,
        dob: str | None = None,
        national_id: str | None = None,
        max_edits: int = 2,
        limit: int = 10,
    ) -> tuple[list[dict], list[dict]]:
        """Atlas Search fuzzy matching. Returns (results, pipeline)."""

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
            should_clauses.append(
                {
                    "text": {
                        "query": national_id,
                        "path": "identifiers.nationalId",
                        "score": {"boost": {"value": 5}},
                    }
                }
            )
            should_clauses.append(
                {
                    "text": {
                        "query": national_id,
                        "path": "identifiers.tin",
                        "score": {"boost": {"value": 5}},
                    }
                }
            )

        compound: dict = {
            "should": should_clauses,
            "minimumShouldMatch": 1,
        }

        if dob:
            compound["filter"] = [
                {
                    "equals": {
                        "path": "dateOfBirth",
                        "value": datetime.fromisoformat(dob),
                    }
                }
            ]

        pipeline = [
            {"$search": {"index": "negative_list_fuzzy", "compound": compound}},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {"$project": {"embedding": 0}},
        ]

        results = []
        async for doc in await self.negative_list.aggregate(pipeline):
            results.append(serialize_doc(doc))
        return results, pipeline

    # ── Fuzzy Search with Pagination + Facets ────────────────

    async def search_fuzzy_paginated(
        self,
        name: str,
        *,
        dob: str | None = None,
        national_id: str | None = None,
        max_edits: int = 2,
        limit: int = 20,
        filters: dict[str, list[str]] | None = None,
        cursor: str | None = None,
        direction: str = "next",
        use_facets: bool = True,
    ) -> tuple[dict, list[dict]]:
        """Atlas Search fuzzy matching with cursor pagination and facets.

        Returns (search_result_dict, pipeline_for_display).
        search_result_dict has keys: results, pagination, facets.
        """
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
            should_clauses.append(
                {
                    "text": {
                        "query": national_id,
                        "path": "identifiers.nationalId",
                        "score": {"boost": {"value": 5}},
                    }
                }
            )
            should_clauses.append(
                {
                    "text": {
                        "query": national_id,
                        "path": "identifiers.tin",
                        "score": {"boost": {"value": 5}},
                    }
                }
            )

        compound: dict = {
            "should": should_clauses,
            "minimumShouldMatch": 1,
        }

        # Date of birth filter
        filter_clauses: list[dict] = []
        if dob:
            filter_clauses.append(
                {
                    "equals": {
                        "path": "dateOfBirth",
                        "value": datetime.fromisoformat(dob),
                    }
                }
            )

        # Facet-based filters
        if filters:
            filter_clauses.extend(build_filter_clauses(filters))

        if filter_clauses:
            compound["filter"] = filter_clauses

        pipeline = build_search_pipeline(
            compound,
            limit=limit,
            cursor=cursor,
            direction=direction,
            use_facets=use_facets,
        )

        result = await execute_paginated_search(
            self.negative_list, pipeline, limit
        )

        if use_facets:
            display_pipeline = [
                {"$search": {
                    "index": "negative_list_fuzzy",
                    "facet": {
                        "operator": {"compound": compound},
                        "facets": "{...6 facet definitions...}",
                    },
                }},
                {"$addFields": {"score": {"$meta": "searchScore"}}},
                {"$limit": limit},
                {"$project": {"embedding": 0}},
            ]
        else:
            display_pipeline = [
                {"$search": {
                    "index": "negative_list_fuzzy",
                    "compound": compound,
                }},
                {"$addFields": {"score": {"$meta": "searchScore"}}},
                {"$limit": limit},
                {"$project": {"embedding": 0}},
            ]

        return result, display_pipeline

    # ── Semantic Search ───────────────────────────────────────

    async def search_semantic(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> tuple[list[dict], list[dict]]:
        """Atlas Vector Search — semantic similarity. Returns (results, pipeline)."""

        query_embedding = await self.generate_embedding(query)

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

        # For the _meta response, strip the queryVector (too large)
        pipeline_display = [
            {
                "$vectorSearch": {
                    "index": "negative_list_vector",
                    "path": "embedding",
                    "queryVector": "[...1024 dimensions...]",
                    "numCandidates": limit * 10,
                    "limit": limit,
                    "filter": {"isActive": True},
                }
            },
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            {"$project": {"embedding": 0}},
        ]

        results = []
        async for doc in await self.negative_list.aggregate(pipeline):
            if doc.get("score", 0) >= min_score:
                results.append(serialize_doc(doc))
        return results, pipeline_display

    # ── Autocomplete ──────────────────────────────────────────

    async def autocomplete(self, query: str, limit: int = 8) -> list[dict]:
        """Type-ahead autocomplete using Atlas Search edgeGram."""
        pipeline = [
            {
                "$search": {
                    "index": "negative_list_fuzzy",
                    "autocomplete": {
                        "query": query,
                        "path": "fullName",
                        "tokenOrder": "any",
                        "fuzzy": {"maxEdits": 1, "prefixLength": 1},
                    },
                }
            },
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit},
            {
                "$project": {
                    "entityId": 1,
                    "fullName": 1,
                    "aliases": 1,
                    "entityType": 1,
                    "riskScore": 1,
                    "negativeReasons.code": 1,
                    "isActive": 1,
                    "score": 1,
                }
            },
        ]

        results = []
        async for doc in await self.negative_list.aggregate(pipeline):
            results.append(serialize_doc(doc))
        return results

    # ── Profile ───────────────────────────────────────────────

    async def get_profile(self, entity_id: str) -> dict | None:
        """Full single-view profile by entityId."""
        doc = await self.negative_list.find_one(
            {"entityId": entity_id}, {"embedding": 0}
        )
        if doc:
            return serialize_doc(doc)
        return None

    # ── Stats ─────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Dashboard statistics."""
        pipeline = [
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "active": [
                        {"$match": {"isActive": True}},
                        {"$count": "count"},
                    ],
                    "resolved": [
                        {"$match": {"isActive": False}},
                        {"$count": "count"},
                    ],
                    "byReason": [
                        {"$unwind": "$negativeReasons"},
                        {
                            "$group": {
                                "_id": "$negativeReasons.code",
                                "count": {"$sum": 1},
                            }
                        },
                        {"$sort": {"count": -1}},
                    ],
                    "bySource": [
                        {"$unwind": "$watchlistSources"},
                        {
                            "$group": {
                                "_id": "$watchlistSources.source",
                                "count": {"$sum": 1},
                            }
                        },
                        {"$sort": {"count": -1}},
                    ],
                    "byBranch": [
                        {
                            "$group": {
                                "_id": "$relationship.branch",
                                "count": {"$sum": 1},
                            }
                        },
                        {"$sort": {"count": -1}},
                        {"$limit": 10},
                    ],
                    "totalExposure": [
                        {"$unwind": "$negativeReasons"},
                        {
                            "$group": {
                                "_id": None,
                                "total": {"$sum": "$negativeReasons.amount"},
                            }
                        },
                    ],
                    "byEntityType": [
                        {
                            "$group": {
                                "_id": "$entityType",
                                "count": {"$sum": 1},
                            }
                        },
                    ],
                }
            }
        ]

        result = None
        async for doc in await self.negative_list.aggregate(pipeline):
            result = doc

        if not result:
            return {}

        return {
            "total": result["total"][0]["count"] if result["total"] else 0,
            "active": result["active"][0]["count"] if result["active"] else 0,
            "resolved": result["resolved"][0]["count"] if result["resolved"] else 0,
            "totalExposure": (
                result["totalExposure"][0]["total"]
                if result["totalExposure"]
                else 0
            ),
            "byReason": [
                {"code": r["_id"], "count": r["count"]}
                for r in result.get("byReason", [])
            ],
            "bySource": [
                {"source": s["_id"], "count": s["count"]}
                for s in result.get("bySource", [])
            ],
            "byBranch": [
                {"branch": b["_id"], "count": b["count"]}
                for b in result.get("byBranch", [])
            ],
            "byEntityType": [
                {"type": e["_id"], "count": e["count"]}
                for e in result.get("byEntityType", [])
            ],
        }

    # ── Entries (paginated) ───────────────────────────────────

    async def get_entries(
        self,
        limit: int = 50,
        skip: int = 0,
        reason: str | None = None,
        source: str | None = None,
        status: str | None = None,
        branch: str | None = None,
    ) -> tuple[list[dict], int]:
        """Paginated negative list with optional filters."""
        match: dict = {}
        if reason:
            match["negativeReasons.code"] = reason
        if source:
            match["watchlistSources.source"] = source
        if status:
            match["isActive"] = status == "active"
        if branch:
            match["relationship.branch"] = branch

        total = await self.negative_list.count_documents(match)
        cursor = (
            self.negative_list.find(match, {"embedding": 0})
            .sort("updatedAt", -1)
            .skip(skip)
            .limit(limit)
        )

        results = []
        async for doc in cursor:
            results.append(serialize_doc(doc))
        return results, total

    # ── By Branch ─────────────────────────────────────────────

    async def get_by_branch(self, branch: str) -> list[dict]:
        """Entries for a specific MB branch."""
        results = []
        async for doc in self.negative_list.find(
            {"relationship.branch": branch}, {"embedding": 0}
        ).sort("updatedAt", -1):
            results.append(serialize_doc(doc))
        return results

    # ── By Reason ─────────────────────────────────────────────

    async def get_by_reason(self, code: str) -> list[dict]:
        """Entries with a specific negative reason code."""
        results = []
        async for doc in self.negative_list.find(
            {"negativeReasons.code": code}, {"embedding": 0}
        ).sort("updatedAt", -1):
            results.append(serialize_doc(doc))
        return results

    # ── Backfill Embeddings ───────────────────────────────────

    async def backfill_embeddings(self) -> dict:
        """Generate embeddings for entries that don't have them."""
        cursor = self.negative_list.find(
            {"$or": [{"embedding": {"$exists": False}}, {"embedding": None}]}
        )
        updated = 0
        errors = 0

        async for doc in cursor:
            try:
                text = serialize_for_embedding(doc)
                embedding = await self.generate_embedding(text)
                await self.negative_list.update_one(
                    {"_id": doc["_id"]}, {"$set": {"embedding": embedding}}
                )
                updated += 1
            except Exception:
                errors += 1

        return {"updated": updated, "errors": errors}

    # ── Index Definitions ─────────────────────────────────────

    def get_index_definitions(self) -> dict:
        """Return index schemas for educational display."""
        return {
            "fuzzyIndex": NEGATIVE_LIST_FUZZY_INDEX,
            "vectorIndex": NEGATIVE_LIST_VECTOR_INDEX,
            "filipinoNameAnalyzer": FILIPINO_NAME_ANALYZER,
        }
