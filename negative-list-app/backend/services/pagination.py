"""
Cursor-based pagination for Atlas Search using searchSequenceToken.

Follows the pattern from the PensionFund reference implementation.
Semantic (vector) search does NOT support cursor pagination.
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from pymongo.asynchronous.collection import AsyncCollection


def _serialize_doc(doc: dict) -> dict:
    """Recursively convert ObjectId and datetime for JSON serialization."""
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            _serialize_doc(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _serialize_doc(item)
    return doc

# ── Facet definitions for negative_list ──────────────────────────

NEGATIVE_LIST_FACETS = {
    "entityTypeFacet": {
        "type": "string",
        "path": "entityType",
        "numBuckets": 5,
    },
    "riskScoreFacet": {
        "type": "number",
        "path": "riskScore",
        "boundaries": [0, 0.3, 0.5, 0.7, 0.9, 1.0],
    },
    "reasonCodeFacet": {
        "type": "string",
        "path": "negativeReasonCodes",
        "numBuckets": 15,
    },
    "watchlistSourceFacet": {
        "type": "string",
        "path": "watchlistSourceNames",
        "numBuckets": 15,
    },
    "branchFacet": {
        "type": "string",
        "path": "relationship.branch",
        "numBuckets": 20,
    },
    "tierFacet": {
        "type": "string",
        "path": "relationship.tier",
        "numBuckets": 10,
    },
}

NEGATIVE_LIST_FACET_MAPPING = {
    "reasonCodeFacet": {
        "label": "Negative Reason",
        "key": "negativeReasonCodes",
        "filterParam": "reason_code",
    },
    "watchlistSourceFacet": {
        "label": "Watchlist Source",
        "key": "watchlistSourceNames",
        "filterParam": "watchlist_source",
    },
    "entityTypeFacet": {
        "label": "Entity Type",
        "key": "entityType",
        "filterParam": "entity_type",
    },
    "branchFacet": {
        "label": "Branch",
        "key": "relationship.branch",
        "filterParam": "branch",
    },
    "tierFacet": {
        "label": "Tier",
        "key": "relationship.tier",
        "filterParam": "tier",
    },
    "riskScoreFacet": {
        "label": "Risk Score Range",
        "key": "riskScore",
        "filterParam": "risk_range",
    },
}

# Reverse map: filterParam -> MongoDB field path
FILTER_PARAM_TO_PATH: dict[str, str] = {
    v["filterParam"]: v["key"] for v in NEGATIVE_LIST_FACET_MAPPING.values()
}


# ── Filter building ──────────────────────────────────────────────

def build_filter_clauses(filters: dict[str, list[str]]) -> list[dict]:
    """Convert frontend filter dict into Atlas Search compound filter clauses."""
    clauses: list[dict] = []
    for param, values in filters.items():
        if not values:
            continue
        path = FILTER_PARAM_TO_PATH.get(param)
        if not path:
            continue

        # For risk_range, use numeric range filter
        if param == "risk_range":
            range_clauses = []
            for val in values:
                parts = val.split("-")
                if len(parts) == 2:
                    try:
                        low, high = float(parts[0]), float(parts[1])
                        range_clauses.append(
                            {"range": {"path": path, "gte": low, "lt": high}}
                        )
                    except ValueError:
                        continue
            if range_clauses:
                if len(range_clauses) == 1:
                    clauses.append(range_clauses[0])
                else:
                    clauses.append({"compound": {"should": range_clauses, "minimumShouldMatch": 1}})
            continue

        # For string facets: single value → equals, multiple → compound/should
        if len(values) == 1:
            clauses.append({"equals": {"path": path, "value": values[0]}})
        else:
            or_clauses = [{"equals": {"path": path, "value": v}} for v in values]
            clauses.append(
                {"compound": {"should": or_clauses, "minimumShouldMatch": 1}}
            )

    return clauses


# ── Pipeline building ────────────────────────────────────────────

def build_search_pipeline(
    compound: dict,
    *,
    limit: int = 20,
    cursor: str | None = None,
    direction: str = "next",
    use_facets: bool = True,
) -> list[dict]:
    """Build the Atlas Search aggregation pipeline with pagination + facets.

    When facets are enabled, the ``facet`` collector becomes the top-level
    operator in ``$search`` (Atlas Search requires this). Cursor-based
    pagination (searchAfter/searchBefore) is not supported with the facet
    collector, so we fall back to offset-based pagination in that case.
    """

    if use_facets:
        # facet collector: compound goes inside facet.operator
        search_cmd: dict = {
            "index": "negative_list_fuzzy",
            "facet": {
                "operator": {"compound": compound},
                "facets": NEGATIVE_LIST_FACETS,
            },
        }

        pipeline = [
            {"$search": search_cmd},
            {"$addFields": {"score": {"$meta": "searchScore"}}},
            {"$limit": limit + 1},
            {
                "$facet": {
                    "results": [{"$limit": limit + 1}],
                    "metadata": [{"$replaceWith": "$$SEARCH_META"}, {"$limit": 1}],
                }
            },
        ]
    else:
        # No facets: use compound directly with cursor pagination support
        search_cmd = {
            "index": "negative_list_fuzzy",
            "compound": compound,
            "sort": {"score": {"$meta": "searchScore"}, "_id": 1},
            "count": {"type": "lowerBound"},
        }

        if cursor:
            if direction == "next":
                search_cmd["searchAfter"] = cursor
            else:
                search_cmd["searchBefore"] = cursor

        pipeline = [
            {"$search": search_cmd},
            {
                "$addFields": {
                    "paginationToken": {"$meta": "searchSequenceToken"},
                    "score": {"$meta": "searchScore"},
                }
            },
            {"$limit": limit + 1},
            {
                "$facet": {
                    "results": [{"$limit": limit + 1}],
                    "metadata": [{"$replaceWith": "$$SEARCH_META"}, {"$limit": 1}],
                }
            },
        ]

    return pipeline


# ── Execution ────────────────────────────────────────────────────

async def execute_paginated_search(
    collection: AsyncCollection,
    pipeline: list[dict],
    limit: int,
) -> dict:
    """Run the pipeline and parse results + pagination + facets."""

    raw = None
    async for doc in await collection.aggregate(pipeline):
        raw = doc

    if not raw:
        return {
            "results": [],
            "pagination": {
                "limit": limit,
                "hasMore": False,
                "cursor": None,
                "totalCount": 0,
                "currentPageSize": 0,
            },
            "facets": [],
        }

    all_results = raw.get("results", [])
    metadata_list = raw.get("metadata", [])
    metadata = metadata_list[0] if metadata_list else {}

    has_more = len(all_results) > limit
    results = all_results[:limit]

    # Serialize results and extract cursors
    first_cursor = None
    last_cursor = None
    for i, doc in enumerate(results):
        token = doc.pop("paginationToken", None)
        if i == 0:
            first_cursor = token
        last_cursor = token
        # Remove embedding field if present
        doc.pop("embedding", None)
        _serialize_doc(doc)

    # Total count from metadata
    total_count = 0
    count_info = metadata.get("count", {})
    if isinstance(count_info, dict):
        total_count = count_info.get("lowerBound", 0)

    # Parse facets
    facets = parse_facets(metadata.get("facet", {}))

    return {
        "results": results,
        "pagination": {
            "limit": limit,
            "hasMore": has_more,
            "cursor": last_cursor if has_more else None,
            "totalCount": total_count,
            "currentPageSize": len(results),
        },
        "facets": facets,
    }


# ── Facet parsing ────────────────────────────────────────────────

def parse_facets(raw_facets: dict) -> list[dict]:
    """Transform Atlas Search facet output into a frontend-friendly list."""
    parsed: list[dict] = []

    for facet_key, mapping in NEGATIVE_LIST_FACET_MAPPING.items():
        facet_data = raw_facets.get(facet_key, {})
        buckets_raw = facet_data.get("buckets", [])

        buckets = []
        for b in buckets_raw:
            value = b.get("_id")
            count = b.get("count", 0)
            if value is not None and count > 0:
                buckets.append({"value": str(value), "count": count})

        if buckets:
            parsed.append(
                {
                    "field": mapping["filterParam"],
                    "label": mapping["label"],
                    "buckets": buckets,
                }
            )

    return parsed
