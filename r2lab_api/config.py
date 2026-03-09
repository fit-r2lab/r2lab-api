from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://r2lab:r2lab@localhost:5432/r2lab"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    smtp_host: str = "localhost"
    smtp_port: int = 25
    mail_from: str = "noreply@r2lab.inria.fr"
    base_url: str = "https://r2lab.inria.fr"

    model_config = {"env_prefix": "R2LAB_", "env_file": ".env"}


settings = Settings()
