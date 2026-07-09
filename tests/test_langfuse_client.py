import os
import pytest


class TestIsConfigured:
    def test_false_when_keys_missing(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import is_configured
        assert is_configured() is False

    def test_false_when_only_public_key_set(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import is_configured
        assert is_configured() is False

    def test_true_when_both_keys_set(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        from infra.langfuse_client import is_configured
        assert is_configured() is True


class TestBuildTraceConfig:
    def test_empty_dict_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        from infra.langfuse_client import build_trace_config
        assert build_trace_config("u1", "s1", "o1") == {}

    def test_callbacks_and_metadata_when_configured(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        import infra.langfuse_client as lc

        class DummyHandler:
            pass

        monkeypatch.setattr(lc, "CallbackHandler", DummyHandler)

        result = lc.build_trace_config("u1", "s1", "o1")

        assert len(result["callbacks"]) == 1
        assert isinstance(result["callbacks"][0], DummyHandler)
        assert result["metadata"] == {
            "langfuse_user_id": "u1",
            "langfuse_session_id": "s1",
            "org_id": "o1",
        }
