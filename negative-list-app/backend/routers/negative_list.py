import time

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.database import get_db
from backend.models.negative_list import SearchMode, SearchRequest
from backend.services.negative_list_service import (
    NegativeListService,
    make_response,
)

router = APIRouter(prefix="/api/negative-list", tags=["negative-list"])


def get_service() -> NegativeListService:
    return NegativeListService(get_db())


# ── POST search (primary — supports filters, pagination, facets) ─

@router.post("/search")
async def search_post(
    body: SearchRequest,
    svc: NegativeListService = Depends(get_service),
):
    """Main search endpoint with pagination, facets, and filters."""
    start = time.perf_counter()

    if body.mode == SearchMode.fuzzy:
        result, pipeline = await svc.search_fuzzy_paginated(
            name=body.query,
            dob=body.dob,
            national_id=body.national_id,
            max_edits=body.max_edits,
            limit=body.limit,
            filters=body.filters,
            cursor=body.cursor,
            direction=body.direction,
            use_facets=body.use_facets,
        )
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return {
            "_meta": {
                "executionTimeMs": elapsed,
                "collection": "negative_list",
                "pipeline": pipeline,
                "index": "negative_list_fuzzy",
                "searchMode": "fuzzy",
                "resultsCount": result["pagination"]["currentPageSize"],
            },
            "results": result["results"],
            "pagination": result["pagination"],
            "facets": result["facets"],
        }
    else:
        # Semantic — no pagination or facets
        results, pipeline = await svc.search_semantic(
            query=body.query, limit=min(body.limit, 50)
        )
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return {
            "_meta": {
                "executionTimeMs": elapsed,
                "collection": "negative_list",
                "pipeline": pipeline,
                "index": "negative_list_vector",
                "searchMode": "semantic",
                "resultsCount": len(results),
            },
            "results": results,
            "pagination": {
                "limit": body.limit,
                "hasMore": False,
                "cursor": None,
                "totalCount": len(results),
                "currentPageSize": len(results),
            },
            "facets": [],
        }


# ── GET search (backwards-compat, simple) ────────────────────────

@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    mode: SearchMode = SearchMode.fuzzy,
    max_edits: int = Query(2, ge=0, le=2),
    limit: int = Query(10, ge=1, le=50),
    dob: str | None = None,
    national_id: str | None = None,
    svc: NegativeListService = Depends(get_service),
):
    """Legacy GET search endpoint — no pagination or facets."""
    start = time.perf_counter()

    if mode == SearchMode.fuzzy:
        results, pipeline = await svc.search_fuzzy(
            name=q, dob=dob, national_id=national_id,
            max_edits=max_edits, limit=limit,
        )
        return make_response(
            results, pipeline=pipeline,
            index="negative_list_fuzzy", search_mode="fuzzy",
            start_time=start,
        )
    else:
        results, pipeline = await svc.search_semantic(query=q, limit=limit)
        return make_response(
            results, pipeline=pipeline,
            index="negative_list_vector", search_mode="semantic",
            start_time=start,
        )


@router.get("/autocomplete")
async def autocomplete(
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=20),
    svc: NegativeListService = Depends(get_service),
):
    """Type-ahead autocomplete (always fuzzy)."""
    start = time.perf_counter()
    results = await svc.autocomplete(q, limit=limit)
    return make_response(
        results, index="negative_list_fuzzy",
        search_mode="fuzzy_autocomplete", start_time=start,
    )


@router.get("/profile/{entity_id}")
async def get_profile(
    entity_id: str,
    svc: NegativeListService = Depends(get_service),
):
    """Full single-view profile by entityId."""
    start = time.perf_counter()
    profile = await svc.get_profile(entity_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Entity not found")
    return make_response(
        profile, query={"entityId": entity_id}, start_time=start,
    )


@router.get("/stats")
async def get_stats(
    svc: NegativeListService = Depends(get_service),
):
    """Dashboard statistics."""
    start = time.perf_counter()
    stats = await svc.get_stats()
    return make_response(stats, start_time=start)


@router.get("/entries")
async def get_entries(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    reason: str | None = None,
    source: str | None = None,
    status: str | None = None,
    branch: str | None = None,
    svc: NegativeListService = Depends(get_service),
):
    """Paginated negative list with optional filters."""
    start = time.perf_counter()
    results, total = await svc.get_entries(
        limit=limit, skip=skip, reason=reason,
        source=source, status=status, branch=branch,
    )
    resp = make_response(results, start_time=start)
    resp["_meta"]["total"] = total
    resp["_meta"]["limit"] = limit
    resp["_meta"]["skip"] = skip
    return resp


@router.get("/by-branch/{branch}")
async def get_by_branch(
    branch: str,
    svc: NegativeListService = Depends(get_service),
):
    """Entries grouped by MB branch."""
    start = time.perf_counter()
    results = await svc.get_by_branch(branch)
    return make_response(results, start_time=start)


@router.get("/by-reason/{code}")
async def get_by_reason(
    code: str,
    svc: NegativeListService = Depends(get_service),
):
    """Entries filtered by negative reason code."""
    start = time.perf_counter()
    results = await svc.get_by_reason(code)
    return make_response(results, start_time=start)


@router.post("/backfill-embeddings")
async def backfill_embeddings(
    svc: NegativeListService = Depends(get_service),
):
    """Generate Voyage AI embeddings for entries missing them."""
    start = time.perf_counter()
    result = await svc.backfill_embeddings()
    return make_response(result, start_time=start)


@router.get("/index-definitions")
async def index_definitions(
    svc: NegativeListService = Depends(get_service),
):
    """Return Atlas Search + Vector index schemas (educational)."""
    start = time.perf_counter()
    definitions = svc.get_index_definitions()
    return make_response(definitions, start_time=start)
