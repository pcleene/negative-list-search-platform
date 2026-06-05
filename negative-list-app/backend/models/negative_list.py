from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    fuzzy = "fuzzy"
    semantic = "semantic"


class SearchRequest(BaseModel):
    """POST /search request body — supports filters, cursor pagination, facets."""

    query: str
    mode: SearchMode = SearchMode.fuzzy
    filters: dict[str, list[str]] = {}
    dob: str | None = None
    national_id: str | None = None
    max_edits: int = Field(2, ge=0, le=2)
    limit: int = Field(20, ge=1, le=50)
    cursor: str | None = None
    direction: str = "next"
    use_facets: bool = True


class EntriesFilter(BaseModel):
    reason: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    branch: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)
    skip: int = Field(0, ge=0)
