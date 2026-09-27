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

    # ---- бинарные каналы (медиа/файлы) ----
    # Отдельные сокеты с приоритетными очередями: файл на 50 МБ не может
    # задержать голос или обычное сообщение. см. app/ws_media.py
    media_socket_enabled: bool = True     # /ws/media — аудио+видео бинарными фреймами
    transfer_socket_enabled: bool = True  # /ws/transfer — файловые чанки
    media_max_frame: int = 262144         # 256 КБ — потолок payload одного фрейма
    media_queue_voice: int = 400          # ~8 c аудио (20 мс/кадр) — держим подряд
    media_queue_video: int = 60           # видео: 1-2 c, дальше рвём (лучше лаг, чем потеря голоса)
    media_queue_ctrl: int = 200
    media_queue_file: int = 24            # файлы дропаем первыми — они одноразовые
    transfer_max_files_per_user: int = 1
    transfer_max_per_room: int = 3
    room_members_cache_s: int = 30        # кэш участников комнаты для медиа-релея

    class Config:
        env_file = ".env"


settings = Settings()
