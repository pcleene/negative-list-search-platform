from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB Atlas
    mongodb_url: str = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    tls_cert_path: str = "<local-path>"
    db_name: str = "mb_negative_list"

    # Voyage AI
    voyage_api_key: str = "<voyage-key>"
    voyage_model: str = "voyage-4-large"
    voyage_dimensions: int = 1024
    voyage_endpoint: str = "https://api.voyageai.com/v1/embeddings"

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
