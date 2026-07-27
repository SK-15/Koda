from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_identity
from infra.postgres import get_db
from infra import provider_keys_repo
from infra.crypto import encrypt_key

router = APIRouter()

VALID_PROVIDER_KINDS = {"anthropic", "openai", "gemini", "deepseek", "ollama", "openai_compatible"}


class ProviderKeyRequest(BaseModel):
    alias: str
    provider_kind: str
    api_key: str
    base_url: str | None = None

    @field_validator("alias")
    @classmethod
    def alias_not_empty(cls, v):
        if not v.strip():
            raise ValueError("alias must not be empty")
        return v

    @field_validator("provider_kind")
    @classmethod
    def provider_kind_known(cls, v):
        if v not in VALID_PROVIDER_KINDS:
            raise ValueError(f"provider_kind must be one of {sorted(VALID_PROVIDER_KINDS)}")
        return v

    @field_validator("api_key")
    @classmethod
    def api_key_not_empty(cls, v):
        if not v.strip():
            raise ValueError("api_key must not be empty")
        return v

    @model_validator(mode="after")
    def base_url_required_for_custom(self):
        # A plain @field_validator("base_url") wouldn't fire here: pydantic v2
        # skips field validators for values left at their default (None), which
        # is exactly the case an omitted base_url hits. A model validator runs
        # after the whole model is built regardless of which fields were defaulted.
        if self.provider_kind == "openai_compatible" and not self.base_url:
            raise ValueError("base_url is required when provider_kind is 'openai_compatible'")
        return self


@router.post("/provider-keys")
async def create_provider_key(
    body: ProviderKeyRequest,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    encrypted = encrypt_key(body.api_key)
    row = await provider_keys_repo.create_or_update(
        db, user_id, body.alias, body.provider_kind, encrypted, body.base_url,
    )
    return {
        "alias": row.alias,
        "provider_kind": row.provider_kind,
        "base_url": row.base_url,
    }


@router.get("/provider-keys")
async def list_provider_keys(
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    rows = await provider_keys_repo.list_for_user(db, user_id)
    return [
        {
            "alias": r.alias,
            "provider_kind": r.provider_kind,
            "base_url": r.base_url,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.delete("/provider-keys/{alias}")
async def delete_provider_key(
    alias: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    deleted = await provider_keys_repo.delete_by_alias(db, user_id, alias)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider key not found")
    return {"deleted": alias}
