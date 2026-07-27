# Bring-Your-Own-Key (BYOK) Provider Keys — Design Spec

**Date:** 2026-07-27
**Status:** Approved
**Execution:** Default project pairing rule applies — user writes koda
source, Claude coaches (points to files/lines, reviews). No override
requested for this task, unlike the `web_search` tool spec.

## Goal

Today every LLM call in koda is billed to whichever operator-held API key
sits in `llm/models.yaml` (`${ANTHROPIC_KEY}`, `${OPENAI_KEY}`, etc. — one
key per provider, shared across every user). Model *choice* is already
per-request (`model: str | None` on the chat/run request body,
`agent_node.py:51` passes it straight to `get_llm`), but the credential
behind it isn't.

Let a koda user configure their own API key — for a built-in provider
(anthropic/openai/gemini/deepseek/ollama) or for an arbitrary
OpenAI-compatible endpoint (OpenRouter, Groq, Together, a self-hosted
vLLM, etc.) — so their usage bills to their own account instead of the
operator's, without losing the zero-config path for providers the
operator already supports.

## Decision

Approach: a new per-user table of named provider "aliases", each holding
an encrypted key and (for custom endpoints) a base URL. The existing
`"provider/model"` string convention becomes `"alias/model"` — a
superset, since every built-in provider name already works as its own
alias with zero rows in the new table.

### Data model

New table in `infra/postgres.py`, alongside the existing `Base` models:

```python
import uuid
from sqlalchemy import UniqueConstraint

class UserProviderKey(Base):
    __tablename__ = "user_provider_keys"

    id                = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id           = Column(String, nullable=False, index=True)
    alias             = Column(String, nullable=False)
    provider_kind     = Column(String, nullable=False)  # anthropic|openai|gemini|deepseek|ollama|openai_compatible
    api_key_encrypted = Column(Text, nullable=False)
    base_url          = Column(String, nullable=True)   # required when provider_kind == openai_compatible
    created_at        = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "alias", name="uq_user_provider_alias"),)
```

`provider_kind` drives which LangChain client class gets built; `alias`
is what shows up on the left of the `/` in a `model` string. A user can
set `alias="anthropic"` to override their own key for the built-in
provider, or `alias="openrouter"` with `provider_kind="openai_compatible"`
to add an endpoint that doesn't exist in `models.yaml` at all.

### Encryption

New `infra/crypto.py`, mirroring the existing `_secret()` pattern in
`infra/auth.py`:

```python
import os
from cryptography.fernet import Fernet

def _fernet() -> Fernet:
    secret = os.getenv("KEY_ENCRYPTION_SECRET")
    if not secret:
        raise RuntimeError("KEY_ENCRYPTION_SECRET not set. Add it to .env")
    return Fernet(secret.encode())

def encrypt_key(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()

def decrypt_key(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
```

`KEY_ENCRYPTION_SECRET` must be a Fernet-compatible base64 32-byte key
(`Fernet.generate_key()`), documented in `.env.example` under a new
`# Key encryption` section. Plaintext keys exist only in memory, for the
duration of building an LLM client — never logged, never returned from
any API response.

### Key resolution

`llm/router.py` changes:

- `get_llm(model=None, enabled_tools=None, user_id=None)` — new
  `user_id` param, forwarded to `_build_base_llm`.
- `_build_base_llm(model=None, user_id=None)`:
  1. Split `model` into `alias, model_name` exactly as today.
  2. If `user_id` is set, call a new `llm/user_keys.py:resolve_user_key(user_id, alias, db_session)`
     that looks up `(user_id, alias)` in `user_provider_keys`.
  3. **Found:**
     - `provider_kind` is one of the 5 built-in kinds → build that
       provider's LangChain client exactly as today, but with
       `api_key=decrypt_key(row.api_key_encrypted)` instead of the
       `models.yaml` value.
     - `provider_kind == "openai_compatible"` → `ChatOpenAI(model=model_name, api_key=decrypt_key(row.api_key_encrypted), base_url=row.base_url, streaming=True)`.
  4. **Not found:** fall back to exactly today's path —
     `get_litellm_params(model, config)` against `models.yaml`. If
     `alias` isn't a recognized built-in provider there either, raise
     `ValueError(f"No key configured for '{alias}'. Add one via POST /provider-keys or use a built-in provider.")`
     (same exception type `_build_base_llm` already raises for unknown
     providers, so no new error-handling shape is introduced).
- `agent_node.py:51` changes `get_llm(model=state.get("model"), enabled_tools=state.get("enabled_tools"))`
  to also pass `user_id=state["user_id"]` (already present in state,
  `chat_runner.py:37`).
- The `ValueError` from step 4 is caught in `agent_node` (new
  try/except around the `get_llm`/`ainvoke` call) and turned into an
  `AIMessage(content=str(e))` response, the same short-circuit shape
  `agent_node` already uses for max-iterations and budget-limit stops
  (`agent_node.py:37-47`) — the graph doesn't crash on a bad alias.

### API routes

New `api/routes/provider_keys.py`, registered in `api/main.py` alongside
the other routers, gated by the existing `get_identity` dependency
(`api/deps.py`) exactly like `projects.py`/`chats.py`:

- `POST /provider-keys`
  Body: `{alias: str, provider_kind: str, api_key: str, base_url: str | None}`.
  Validates `provider_kind` is one of the 6 known kinds; if
  `openai_compatible`, `base_url` is required (422 otherwise). Encrypts
  `api_key`, upserts by `(user_id, alias)`. Response echoes
  `{alias, provider_kind, base_url}` — never the key.
- `GET /provider-keys`
  Returns the caller's rows as `[{alias, provider_kind, base_url, created_at}]` — key always omitted.
- `DELETE /provider-keys/{alias}`
  Deletes the caller's row for that alias. 404 if it doesn't exist.

### Config

- New dependency: `cryptography>=42.0.0` in `pyproject.toml` (already
  present transitively via `pyjwt`'s extras, per a check against the
  current `.venv` — this makes it an explicit direct dependency instead
  of an implicit one).
- New env var: `KEY_ENCRYPTION_SECRET`, added to `.env.example` under a
  `# Key encryption` section, alongside a one-line comment on how to
  generate one (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

## Error handling

- `openai_compatible` without `base_url` on `POST /provider-keys` → 422,
  Pydantic validation.
- Decrypt failure (rotated/corrupted `KEY_ENCRYPTION_SECRET`) → caught in
  `resolve_user_key`, surfaced as a 500 with a generic
  "key store misconfigured" message — never the raw
  `cryptography.fernet.InvalidToken` exception or any key material.
- Unknown alias at chat time (no user row, not a built-in provider name)
  → handled by the `agent_node` try/except described above; the user
  sees a plain-text explanation in the chat instead of a broken run.
- `DELETE` on a nonexistent alias → 404, matching existing route
  conventions (e.g. `projects.py`).

## Testing

- `infra/crypto.py`: round-trip `encrypt_key`/`decrypt_key`; missing
  `KEY_ENCRYPTION_SECRET` raises `RuntimeError`.
- `llm/user_keys.py`: `resolve_user_key` returns `None` when no row
  exists; returns the row when one does; a row belonging to a different
  `user_id` is never returned for the same alias (cross-user isolation).
- `llm/router.py`: `_build_base_llm` unit tests — user key present for a
  built-in alias → provider client built with the decrypted key, not the
  env one; user key absent → falls back to `models.yaml`; `openai_compatible`
  row → `ChatOpenAI` called with `base_url` set; unknown alias with no
  row anywhere → `ValueError` with the documented message.
- `agent_node.py`: unknown-alias `ValueError` from `get_llm` is caught
  and turned into an `AIMessage`, graph doesn't raise past `agent_node`.
- `api/routes/provider_keys.py`: create/list/delete round trip; response
  bodies never contain `api_key`/`api_key_encrypted`; `openai_compatible`
  without `base_url` → 422; duplicate `(user_id, alias)` POST upserts
  rather than erroring; a second user's `GET` never returns the first
  user's rows.

## Files touched

| File | Change |
|---|---|
| `infra/postgres.py` | add `UserProviderKey` model |
| `infra/crypto.py` | new — Fernet encrypt/decrypt helpers |
| `llm/user_keys.py` | new — `resolve_user_key(user_id, alias, db_session)` |
| `llm/router.py` | `get_llm`/`_build_base_llm` gain `user_id` param, user-key-first resolution, `openai_compatible` client branch |
| `agent/nodes/agent_node.py` | pass `state["user_id"]` into `get_llm`; catch unknown-alias `ValueError`, return `AIMessage` |
| `api/routes/provider_keys.py` | new — POST/GET/DELETE routes |
| `api/main.py` | register the new router |
| `pyproject.toml`, `requirements.txt` | add `cryptography` as a direct dependency |
| `.env.example` | add `KEY_ENCRYPTION_SECRET` section |
| `tests/test_koda.py` or new `tests/test_provider_keys.py` | route + resolution + crypto + router tests per Testing section |

## Out of scope

- Key rotation UX (listing/replacing an old key while keeping history) —
  `POST` upserts, no versioning.
- Rate limiting or spend caps per user-supplied key — koda's existing
  per-thread `budget_limit_usd` still applies regardless of whose key is
  used; the operator has no visibility into what a user's own key costs
  them externally.
- Any frontend/UI for managing keys — this repo has no frontend; the
  three routes are the complete surface for now.
- Validating a key actually works at `POST` time (e.g. a test call to
  the provider) — invalid keys fail at first chat use, not at
  registration.
- Migrating `models.yaml`'s operator-held keys into this table — the two
  systems coexist; `models.yaml` remains the zero-config fallback.
