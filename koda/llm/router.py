import os
from tools.registry import all_tools
from llm.model_config import load_model_config, get_litellm_params, get_default_model, get_fallback_model


_config = None


def _get_config() -> dict:
    global _config
    if _config is None:
        _config = load_model_config()
    return _config


def _get_tool_schemas() -> list:
    schemas = []
    for tool in all_tools():
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_class.model_json_schema(),
            }
        })
    return schemas


def _build_base_llm(model: str = None):
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_ollama import ChatOllama

    config = _get_config()
    model = model or get_default_model(config)

    if "/" not in model:
        raise ValueError(f"Model must be 'provider/model', got: {model}")

    provider, model_name = model.split("/", 1)
    params = get_litellm_params(model, config)

    if provider == "anthropic":
        llm = ChatAnthropic(model=model_name, api_key=params.get("api_key"), max_tokens=4096)
    elif provider == "openai":
        llm = ChatOpenAI(model=model_name, api_key=params.get("api_key"))
    elif provider == "gemini":
        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=params.get("api_key"))
    elif provider == "ollama":
        llm = ChatOllama(model=model_name, base_url=params.get("api_base", "http://localhost:11434"))
    elif provider == "deepseek":
        llm = ChatOpenAI(model=model_name, api_key=params.get("api_key"), base_url=params.get("api_base"))
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    return llm


def get_llm(model: str = None):
    return _build_base_llm(model).bind_tools(_get_tool_schemas())


def get_planner_llm(model: str = None):
    from agent.plan_schema import Plan
    return _build_base_llm(model).with_structured_output(Plan)