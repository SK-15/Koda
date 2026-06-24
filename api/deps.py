from fastapi import Header


async def get_identity(
    x_org_id: str = Header(default="default"),
    x_user_id: str = Header(default="default"),
) -> tuple[str, str]:
    return x_org_id, x_user_id
