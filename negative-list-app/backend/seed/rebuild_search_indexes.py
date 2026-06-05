"""
Drop and recreate Atlas Search + Vector indexes for the negative_list collection.

Usage:
    python -m backend.seed.rebuild_search_indexes
"""

import asyncio
import sys

from pymongo import AsyncMongoClient

from backend.config import settings
from backend.services.negative_list_service import (
    NEGATIVE_LIST_FUZZY_INDEX,
    NEGATIVE_LIST_VECTOR_INDEX,
)

COLLECTION = "negative_list"


async def rebuild():
    kwargs: dict = {}
    if settings.tls_cert_path:
        kwargs["tls"] = True
        kwargs["tlsCertificateKeyFile"] = settings.tls_cert_path

    client = AsyncMongoClient(settings.mongodb_url, **kwargs)
    await client.admin.command("ping")
    db = client[settings.db_name]
    print(f"Connected to {settings.db_name}")

    # ── Drop existing indexes ───────────────────────────────────
    for idx_name in ["negative_list_fuzzy", "negative_list_vector"]:
        try:
            await db.command({"dropSearchIndex": COLLECTION, "name": idx_name})
            print(f"  Dropped index: {idx_name}")
        except Exception as e:
            print(f"  Could not drop {idx_name} (may not exist): {e}")

    # ── Recreate indexes ────────────────────────────────────────
    try:
        await db.command(
            {
                "createSearchIndexes": COLLECTION,
                "indexes": [NEGATIVE_LIST_FUZZY_INDEX],
            }
        )
        print("  Created fuzzy index")
    except Exception as e:
        print(f"  Error creating fuzzy index: {e}")

    try:
        await db.command(
            {
                "createSearchIndexes": COLLECTION,
                "indexes": [NEGATIVE_LIST_VECTOR_INDEX],
            }
        )
        print("  Created vector index")
    except Exception as e:
        print(f"  Error creating vector index: {e}")

    print("\nIndexes submitted. They build asynchronously — check Atlas UI for status.")
    client.close()


if __name__ == "__main__":
    asyncio.run(rebuild())
