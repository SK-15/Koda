import os
from tools.registry import all_tools
from llm.model_config import load_model_config, get_litellm_params, get_default_model, get_fallback_model
from llm.user_keys import resolve_user_key
from infra.crypto import decrypt_key


_config = None


def _get_config() -> dict:
    global _config
    if _config is None:
        _config = load_model_config()
    return _config


def _get_tool_schemas(enabled_tools: list[str] | None = None) -> list:
    schemas = []
    for tool in all_tools():
        if enabled_tools is not None and tool.name not in enabled_tools:
            continue
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_class.model_json_schema(),
            }
        })
    return schemas


def _build_client(provider_kind: str, model_name: str, api_key: str | None, base_url: str | None = None):
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_ollama import ChatOllama

    # streaming=True lets even ainvoke emit on_chat_model_stream events, which
    # the WS layer forwards as token deltas. ainvoke still returns the full
    # aggregated message, so non-streaming (REST) callers are unaffected.
    if provider_kind == "anthropic":
        return ChatAnthropic(model=model_name, api_key=api_key, max_tokens=4096, streaming=True)
    elif provider_kind == "openai":
        return ChatOpenAI(model=model_name, api_key=api_key, streaming=True)
    elif provider_kind == "gemini":
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    elif provider_kind == "ollama":
        return ChatOllama(model=model_name, base_url=base_url or "http://localhost:11434")
    elif provider_kind == "deepseek":
        return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url or "https://api.deepseek.com/v1", streaming=True)
    elif provider_kind == "openai_compatible":
        return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url, streaming=True)
    else:
        raise ValueError(f"Unsupported provider: {provider_kind}")


async def _build_base_llm(model: str = None, user_id: str = None):
    config = _get_config()
    model = model or get_default_model(config)

    if "/" not in model:
        raise ValueError(f"Model must be 'provider/model', got: {model}")

    alias, model_name = model.split("/", 1)

    user_key_row = await resolve_user_key(user_id, alias)
    if user_key_row is not None:
        try:
            api_key = decrypt_key(user_key_row.api_key_encrypted)
        except Exception:
            # Never leak the raw decrypt exception or key material — a
            # corrupted/rotated KEY_ENCRYPTION_SECRET is an operator problem,
            # not something the end user can act on.
            raise ValueError("Key store misconfigured — could not decrypt provider key. Contact the operator.")
        return _build_client(user_key_row.provider_kind, model_name, api_key, user_key_row.base_url)

    provider_config = config.get("providers", {}).get(alias)
    if provider_config is None:
        raise ValueError(
            f"No key configured for '{alias}'. Add one via POST /provider-keys or use a built-in provider."
        )

    params = get_litellm_params(model, config)
    return _build_client(alias, model_name, params.get("api_key"), params.get("api_base"))


async def get_llm(model: str = None, enabled_tools: list[str] | None = None, user_id: str = None):
    """Build the LLM bound to a session-scoped tool set.

    enabled_tools=None binds all registered tools (default / local runs).
    A capability-negotiated session passes the client-advertised subset; an
    empty list binds no tools, yielding a pure-chat agent.
    """
    schemas = _get_tool_schemas(enabled_tools)
    llm = await _build_base_llm(model, user_id)
    if not schemas:
        return llm
    return llm.bind_tools(schemas)


async def get_planner_llm(model: str = None):
    from agent.plan_schema import Plan
    llm = await _build_base_llm(model)
    return llm.with_structured_output(Plan)
