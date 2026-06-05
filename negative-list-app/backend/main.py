from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import connect, disconnect
from backend.routers.negative_list import router as negative_list_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect(
        uri=settings.mongodb_url,
        db_name=settings.db_name,
        tls_cert_path=settings.tls_cert_path,
    )
    yield
    await disconnect()


app = FastAPI(
    title="MB Negative List Search",
    description="MongoDB Atlas EDC — Fuzzy + Semantic negative list screening for MB",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(negative_list_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
    )
