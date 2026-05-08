from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://trackhub:trackhub@localhost:5432/trackhub"
    jwt_secret_key: str = "change_me_to_a_long_random_secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    upload_dir: str = "uploads/tracks"
    max_audio_size_mb: int = 50

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
