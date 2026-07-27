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
