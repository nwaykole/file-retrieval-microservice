"""Provision an account interactively; public self-registration is intentionally disabled."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys

import asyncpg

from .auth import hash_password

_USERNAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@+-]{2,127}$")


async def _create_user(dsn: str, username: str, customer_id: str, password: str) -> None:
    conn = await asyncpg.connect(dsn, command_timeout=10)
    try:
        await conn.execute(
            "INSERT INTO users (username, customer_id, password_hash) VALUES ($1, $2, $3)",
            username, customer_id, hash_password(password))
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a file-service user account")
    parser.add_argument("--username", required=True)
    parser.add_argument("--customer-id", required=True)
    args = parser.parse_args()

    username = args.username.strip().lower()
    customer_id = args.customer_id.strip()
    dsn = os.getenv("FS_DATABASE_URL")
    if not _USERNAME.fullmatch(username):
        parser.error("username must be 3-128 characters: letters, digits, dot, underscore, @, +, or -")
    if not customer_id:
        parser.error("customer-id must not be empty")
    if not dsn:
        parser.error("set FS_DATABASE_URL to an authorized PostgreSQL connection string")

    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        parser.error("password must be at least 12 characters")
    if password != confirmation:
        parser.error("passwords do not match")
    try:
        asyncio.run(_create_user(dsn, username, customer_id, password))
    except asyncpg.UniqueViolationError:
        parser.error(f"username {username!r} already exists")
    print(f"Created user {username!r} for customer {customer_id!r}.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"Could not create user: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
