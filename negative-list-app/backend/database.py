from pymongo import AsyncMongoClient

_client: AsyncMongoClient | None = None
_db = None


async def connect(uri: str, db_name: str, tls_cert_path: str | None = None):
    global _client, _db
    kwargs: dict = {}
    if tls_cert_path:
        kwargs["tls"] = True
        kwargs["tlsCertificateKeyFile"] = tls_cert_path
    _client = AsyncMongoClient(uri, **kwargs)
    await _client.admin.command("ping")
    _db = _client[db_name]


async def disconnect():
    global _client
    if _client:
        _client.close()
        _client = None


def get_db():
    assert _db is not None, "DB not initialised — call connect() first"
    return _db
