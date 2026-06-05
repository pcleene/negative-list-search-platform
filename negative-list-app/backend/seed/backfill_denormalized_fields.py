"""
Backfill denormalized flat arrays for Atlas Search faceting.

Adds two top-level fields to every document:
  - negativeReasonCodes:  [str]  — extracted from negativeReasons[].code
  - watchlistSourceNames: [str]  — extracted from watchlistSources[].source

Then drops and recreates the Atlas Search fuzzy index with the new field mappings.

Usage:
    python3 -m backend.seed.backfill_denormalized_fields
"""

import asyncio

from pymongo import AsyncMongoClient

from backend.config import settings
from backend.services.negative_list_service import NEGATIVE_LIST_FUZZY_INDEX

COLLECTION = "negative_list"


async def backfill():
    kwargs: dict = {}
    if settings.tls_cert_path:
        kwargs["tls"] = True
        kwargs["tlsCertificateKeyFile"] = settings.tls_cert_path

    client = AsyncMongoClient(settings.mongodb_url, **kwargs)
    await client.admin.command("ping")
    db = client[settings.db_name]
    collection = db[COLLECTION]
    print(f"Connected to {settings.db_name}")

    # ── Step 1: Backfill denormalized fields ─────────────────────
    print("\nBackfilling negativeReasonCodes and watchlistSourceNames...")
    result = await collection.update_many(
        {},
        [
            {
                "$set": {
                    "negativeReasonCodes": {
                        "$map": {
                            "input": {"$ifNull": ["$negativeReasons", []]},
                            "as": "r",
                            "in": "$$r.code",
                        }
                    },
                    "watchlistSourceNames": {
                        "$setUnion": [
                            {
                                "$map": {
                                    "input": {"$ifNull": ["$watchlistSources", []]},
                                    "as": "s",
                                    "in": "$$s.source",
                                }
                            }
                        ]
                    },
                }
            }
        ],
    )
    print(f"  Updated {result.modified_count} documents")

    # ── Step 2: Verify ───────────────────────────────────────────
    sample = await collection.find_one(
        {}, {"negativeReasonCodes": 1, "watchlistSourceNames": 1, "entityId": 1}
    )
    if sample:
        print(f"\n  Sample ({sample.get('entityId')}):")
        print(f"    negativeReasonCodes:  {sample.get('negativeReasonCodes')}")
        print(f"    watchlistSourceNames: {sample.get('watchlistSourceNames')}")

    # ── Step 3: Rebuild fuzzy index ──────────────────────────────
    print("\nDropping existing fuzzy index...")
    try:
        await db.command({"dropSearchIndex": COLLECTION, "name": "negative_list_fuzzy"})
        print("  Dropped.")
    except Exception as e:
        print(f"  Could not drop (may not exist): {e}")

    print("Creating fuzzy index with new field mappings...")
    try:
        await db.command(
            {
                "createSearchIndexes": COLLECTION,
                "indexes": [NEGATIVE_LIST_FUZZY_INDEX],
            }
        )
        print("  Index created (building in background).")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nDone! Check Atlas UI for index build status.")
    await client.close()


if __name__ == "__main__":
    asyncio.run(backfill())
