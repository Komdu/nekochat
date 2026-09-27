from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://nekochat:nekochat@db:5432/nekochat"
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080
    avatars_dir: str = "app/avatars"

    # ---- NATS transport (Phase 1) ----
    nats_enabled: bool = True   # NATS_ENABLED=false — NATS-мост выключен, всё работает как раньше (/ws)
    nats_url: str = "nats://localhost:4222"  # внутренний вход (nats-server в том же контейнере)
    nats_ws_user: str = "nekochat"
    nats_ws_pass: str = "change-me-in-production-please"
    nats_ping_interval_s: int = 10  # клиенты шлют {"type":"ping"} раз в N сек
    nats_silence_s: int = 45        # нет сообщений от клиента > N сек -> offline (half-open guard)

    class Config:
        env_file = ".env"


settings = Settings()
