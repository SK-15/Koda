from infra.postgres import get_session_factory
from infra import provider_keys_repo


async def resolve_user_key(user_id: str | None, alias: str):
    if not user_id:
        return None
    async with get_session_factory()() as session:
        return await provider_keys_repo.get_by_alias(session, user_id, alias)
