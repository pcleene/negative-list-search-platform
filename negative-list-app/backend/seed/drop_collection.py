"""Drop the negative_list collection. Usage: python -m backend.seed.drop_collection"""

import asyncio
from pymongo import AsyncMongoClient

MONGO_URI = (
    "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    "?authSource=%24external&authMechanism=MONGODB-X509&appName=testCluster"
)
TLS_CERT_PATH = "<local-path>"
DB_NAME = "mb_negative_list"


async def main():
    client = AsyncMongoClient(MONGO_URI, tls=True, tlsCertificateKeyFile=TLS_CERT_PATH)
    await client.admin.command("ping")
    print("Connected to Atlas.")

    db = client[DB_NAME]
    count = await db["negative_list"].count_documents({})
    print(f"Current document count: {count}")

    await db["negative_list"].drop()
    print("Collection 'negative_list' dropped.")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
