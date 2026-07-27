import pytest


class TestCrypto:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

        from infra.crypto import encrypt_key, decrypt_key
        encrypted = encrypt_key("sk-super-secret")
        assert encrypted != "sk-super-secret"
        assert decrypt_key(encrypted) == "sk-super-secret"

    def test_encrypt_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("KEY_ENCRYPTION_SECRET", raising=False)

        from infra.crypto import encrypt_key
        with pytest.raises(RuntimeError):
            encrypt_key("sk-super-secret")


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeSession:
    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results or [])
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def execute(self, *_args, **_kwargs):
        return self._execute_results.pop(0)


class TestProviderKeysRepo:
    @pytest.mark.asyncio
    async def test_get_by_alias_none_when_not_found(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.get_by_alias(session, "user-1", "anthropic")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_alias_returns_row(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="enc")
        session = _FakeSession(execute_results=[_FakeResult(row)])
        result = await provider_keys_repo.get_by_alias(session, "user-1", "anthropic")
        assert result is row

    @pytest.mark.asyncio
    async def test_create_or_update_creates_new_row(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.create_or_update(
            session, "user-1", "anthropic", "anthropic", "enc-key", None,
        )
        assert result.user_id == "user-1"
        assert result.alias == "anthropic"
        assert result.provider_kind == "anthropic"
        assert result.api_key_encrypted == "enc-key"
        assert result.id is not None
        assert session.added == [result]
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_create_or_update_updates_existing_row(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        existing = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="old-enc", base_url=None,
        )
        session = _FakeSession(execute_results=[_FakeResult(existing)])
        result = await provider_keys_repo.create_or_update(
            session, "user-1", "anthropic", "anthropic", "new-enc", None,
        )
        assert result is existing
        assert result.api_key_encrypted == "new-enc"
        assert session.added == []
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_list_for_user_returns_rows(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        rows = [
            UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="e1"),
            UserProviderKey(id="id-2", user_id="user-1", alias="openrouter", provider_kind="openai_compatible", api_key_encrypted="e2", base_url="https://openrouter.ai/api/v1"),
        ]
        session = _FakeSession(execute_results=[_FakeResult(rows)])
        result = await provider_keys_repo.list_for_user(session, "user-1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_delete_by_alias_returns_false_when_missing(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.delete_by_alias(session, "user-1", "anthropic")
        assert result is False
        assert session.deleted == []

    @pytest.mark.asyncio
    async def test_delete_by_alias_deletes_and_returns_true(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="e1")
        session = _FakeSession(execute_results=[_FakeResult(row)])
        result = await provider_keys_repo.delete_by_alias(session, "user-1", "anthropic")
        assert result is True
        assert session.deleted == [row]
        assert session.committed is True


class TestResolveUserKey:
    @pytest.mark.asyncio
    async def test_returns_none_when_user_id_is_none(self):
        from llm.user_keys import resolve_user_key
        result = await resolve_user_key(None, "anthropic")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_row_from_repo(self, monkeypatch):
        import llm.user_keys as uk
        from infra.postgres import UserProviderKey
        from unittest.mock import AsyncMock

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="enc")

        class _FakeSessionCtx:
            async def __aenter__(self):
                return "fake-session"

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(uk, "get_session_factory", lambda: (lambda: _FakeSessionCtx()))
        monkeypatch.setattr(uk.provider_keys_repo, "get_by_alias", AsyncMock(return_value=row))

        result = await uk.resolve_user_key("user-1", "anthropic")
        assert result is row


class TestBuildBaseLlmWithUserKeys:
    @pytest.mark.asyncio
    async def test_uses_user_key_when_present(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="enc-key", base_url=None,
        )

        async def fake_resolve(user_id, alias):
            assert user_id == "user-1"
            assert alias == "anthropic"
            return row

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", lambda token: "decrypted-" + token)

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")
        assert captured["api_key"] == "decrypted-enc-key"

    @pytest.mark.asyncio
    async def test_falls_back_to_env_key_when_no_user_row(self, monkeypatch):
        import llm.router as router

        async def fake_resolve(user_id, alias):
            return None

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        # _get_config() memoizes into a module-global on first call, so real
        # env-var expansion is order-dependent across the test session —
        # patch the config directly instead of monkeypatch.setenv.
        monkeypatch.setattr(router, "_get_config", lambda: {
            "providers": {"anthropic": {"api_key": "env-key-value"}},
            "default_model": "anthropic/claude-sonnet-4-5",
        })

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")
        assert captured["api_key"] == "env-key-value"

    @pytest.mark.asyncio
    async def test_openai_compatible_user_row_passes_base_url(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="openrouter",
            provider_kind="openai_compatible", api_key_encrypted="enc-key",
            base_url="https://openrouter.ai/api/v1",
        )

        async def fake_resolve(user_id, alias):
            return row

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", lambda token: "decrypted-" + token)

        captured = {}

        class FakeChatOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_openai
        monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)

        result = await router._build_base_llm("openrouter/mixtral-8x7b", user_id="user-1")
        assert captured["api_key"] == "decrypted-enc-key"
        assert captured["base_url"] == "https://openrouter.ai/api/v1"

    @pytest.mark.asyncio
    async def test_unknown_alias_with_no_user_row_raises_documented_message(self, monkeypatch):
        import llm.router as router

        async def fake_resolve(user_id, alias):
            return None

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)

        with pytest.raises(ValueError, match="No key configured for 'openrouter'"):
            await router._build_base_llm("openrouter/mixtral-8x7b", user_id="user-1")

    @pytest.mark.asyncio
    async def test_decrypt_failure_raises_generic_value_error(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="corrupted-token", base_url=None,
        )

        async def fake_resolve(user_id, alias):
            return row

        def fake_decrypt(token):
            raise ValueError("Fernet token is invalid")  # simulates cryptography.fernet.InvalidToken

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", fake_decrypt)

        with pytest.raises(ValueError, match="Key store misconfigured"):
            await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")

    @pytest.mark.asyncio
    async def test_no_user_id_falls_back_to_env_key(self, monkeypatch):
        # resolve_user_key itself guards on falsy user_id (Task 4's
        # test_returns_none_when_user_id_is_none covers that directly).
        # This test just confirms _build_base_llm's fallback path still
        # works end-to-end when user_id is None.
        import llm.router as router

        monkeypatch.setattr(router, "_get_config", lambda: {
            "providers": {"anthropic": {"api_key": "env-key-value"}},
            "default_model": "anthropic/claude-sonnet-4-5",
        })

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id=None)
        assert captured["api_key"] == "env-key-value"


class TestProviderKeyRequestValidation:
    def test_rejects_unknown_provider_kind(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="x", provider_kind="not-a-real-kind", api_key="sk-1")

    def test_rejects_empty_alias(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="  ", provider_kind="anthropic", api_key="sk-1")

    def test_rejects_empty_api_key(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="x", provider_kind="anthropic", api_key="  ")

    def test_openai_compatible_requires_base_url(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="openrouter", provider_kind="openai_compatible", api_key="sk-1")

    def test_openai_compatible_with_base_url_is_valid(self):
        from api.routes.provider_keys import ProviderKeyRequest

        req = ProviderKeyRequest(
            alias="openrouter", provider_kind="openai_compatible",
            api_key="sk-1", base_url="https://openrouter.ai/api/v1",
        )
        assert req.base_url == "https://openrouter.ai/api/v1"

    def test_built_in_kind_does_not_require_base_url(self):
        from api.routes.provider_keys import ProviderKeyRequest

        req = ProviderKeyRequest(alias="anthropic", provider_kind="anthropic", api_key="sk-1")
        assert req.base_url is None


class TestProviderKeyRoutes:
    @pytest.mark.asyncio
    async def test_create_encrypts_and_never_echoes_key(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import create_provider_key, ProviderKeyRequest
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module, "encrypt_key", lambda plaintext: "encrypted-" + plaintext)

        captured = {}

        async def fake_create_or_update(db, user_id, alias, provider_kind, api_key_encrypted, base_url):
            captured["api_key_encrypted"] = api_key_encrypted
            row = type("Row", (), {})()
            row.alias = alias
            row.provider_kind = provider_kind
            row.base_url = base_url
            return row

        monkeypatch.setattr(pk_module.provider_keys_repo, "create_or_update", fake_create_or_update)

        body = ProviderKeyRequest(alias="anthropic", provider_kind="anthropic", api_key="sk-plaintext")
        result = await create_provider_key(body, identity=("user-1", "user-1"), db=AsyncMock())

        assert result == {"alias": "anthropic", "provider_kind": "anthropic", "base_url": None}
        assert captured["api_key_encrypted"] == "encrypted-sk-plaintext"
        assert "api_key" not in result
        assert "sk-plaintext" not in str(result)

    @pytest.mark.asyncio
    async def test_list_never_includes_key(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import list_provider_keys
        import api.routes.provider_keys as pk_module

        row = type("Row", (), {})()
        row.alias = "anthropic"
        row.provider_kind = "anthropic"
        row.base_url = None
        row.created_at = "2026-07-27T00:00:00"

        monkeypatch.setattr(pk_module.provider_keys_repo, "list_for_user", AsyncMock(return_value=[row]))

        result = await list_provider_keys(identity=("user-1", "user-1"), db=AsyncMock())

        assert result == [{
            "alias": "anthropic", "provider_kind": "anthropic",
            "base_url": None, "created_at": "2026-07-27T00:00:00",
        }]

    @pytest.mark.asyncio
    async def test_delete_missing_alias_raises_404(self, monkeypatch):
        from unittest.mock import AsyncMock
        from fastapi import HTTPException
        from api.routes.provider_keys import delete_provider_key
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module.provider_keys_repo, "delete_by_alias", AsyncMock(return_value=False))

        with pytest.raises(HTTPException) as exc_info:
            await delete_provider_key("nonexistent", identity=("user-1", "user-1"), db=AsyncMock())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_existing_alias_succeeds(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import delete_provider_key
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module.provider_keys_repo, "delete_by_alias", AsyncMock(return_value=True))

        result = await delete_provider_key("anthropic", identity=("user-1", "user-1"), db=AsyncMock())
        assert result == {"deleted": "anthropic"}
