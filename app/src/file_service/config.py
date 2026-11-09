"""Runtime configuration, loaded once from environment variables (12-factor)."""
from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FS_", env_file=".env", extra="ignore")

    env: str = "local"                     # local | dev | prod
    log_level: str = "INFO"

    # --- Auth (passwords are scrypt-hashed; only opaque session hashes are stored) ---
    session_cookie_name: str = "fs_session"
    session_ttl_seconds: int = Field(default=43_200, ge=300, le=604_800)
    local_username: str | None = None
    local_password: str | None = None
    local_customer_id: str | None = None

    @model_validator(mode="after")
    def validate_local_account(self) -> Settings:
        self.local_username = self.local_username or None
        self.local_password = self.local_password or None
        self.local_customer_id = self.local_customer_id or None
        if self.local_username:
            self.local_username = self.local_username.strip().lower()
        local_account = (self.local_username, self.local_password, self.local_customer_id)
        if any(local_account) and not all(local_account):
            raise ValueError("FS_LOCAL_USERNAME, FS_LOCAL_PASSWORD, and FS_LOCAL_CUSTOMER_ID must be set together")
        if all(local_account) and (self.env == "prod" or self.metadata_backend != "memory"):
            raise ValueError("FS_LOCAL_* account settings are only allowed outside prod with memory metadata")
        if self.local_password is not None and len(self.local_password) < 12:
            raise ValueError("FS_LOCAL_PASSWORD must be at least 12 characters")
        if self.local_username and not re.fullmatch(r"[a-z0-9][a-z0-9._@+-]{2,127}", self.local_username):
            raise ValueError("FS_LOCAL_USERNAME must be 3-128 letters, digits, dot, underscore, @, +, or -")
        return self

    # --- Backends ---
    storage_backend: str = "local"         # local | gcs
    storage_bucket: str = "customer-files"
    local_storage_root: str = "./.data/files"
    metadata_backend: str = "memory"       # memory | postgres
    database_url: str | None = None        # postgresql://... (from Secret Manager via CSI / env)
    db_pool_min: int = 5
    db_pool_max: int = 20

    # --- Behaviour ---
    signed_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    stream_max_bytes: int = 1 * 1024 * 1024   # stream files <= 1 MiB inline, redirect larger ones
    metadata_cache_ttl_seconds: int = 30
    metadata_cache_size: int = 50_000
    backend_timeout_seconds: float = 0.25     # keep total well inside the 300 ms latency SLO


@lru_cache
def get_settings() -> Settings:
    return Settings()
