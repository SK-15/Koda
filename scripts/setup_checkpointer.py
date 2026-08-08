"""One-time setup for the LangGraph Postgres checkpointer's tables.

Usage:
    uv run python -m scripts.setup_checkpointer
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from infra.postgres import _get_psycopg_dsn  # noqa: E402


async def main() -> None:
    async with AsyncPostgresSaver.from_conn_string(_get_psycopg_dsn()) as checkpointer:
        await checkpointer.setup()
    print("Checkpointer tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
