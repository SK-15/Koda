"""Create a koda login (admin-provisioned; there is no public signup).

Usage:
    uv run python -m scripts.create_user <email>
"""
import asyncio
import getpass
import sys

from dotenv import load_dotenv

load_dotenv()

from infra import users_repo  # noqa: E402
from infra.auth import hash_password  # noqa: E402
from infra.postgres import create_tables, get_session_factory  # noqa: E402


async def main(email: str, password: str) -> None:
    await create_tables()
    async with get_session_factory()() as db:
        existing = await users_repo.get_user_by_email(db, email)
        if existing:
            print(f"A user with email {email!r} already exists.")
            sys.exit(1)
        user = await users_repo.create_user(db, email, hash_password(password))
        print(f"Created user {user.email} ({user.user_id})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m scripts.create_user <email>")
        sys.exit(1)

    email_arg = sys.argv[1]
    password_arg = getpass.getpass("Password: ")
    confirm_arg = getpass.getpass("Confirm password: ")
    if password_arg != confirm_arg:
        print("Passwords did not match.")
        sys.exit(1)

    asyncio.run(main(email_arg, password_arg))
