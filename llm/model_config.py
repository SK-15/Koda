import os
import re
import yaml
from pathlib import Path


def _expand_env(value: str) -> str:
    def replacer(match):
        var = match.group(1)
        if ":-" in var:
            name, default = var.split(":-", 1)
            return os.getenv(name, default)
        return os.getenv(var, "")
    return re.sub(r"\$\{([^}]+)\}", replacer, value)


def _expand_dict(obj):
    if isinstance(obj, dict):
        return {k: _expand_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_dict(i) for i in obj]
    if isinstance(obj, str):
        return _expand_env(obj)
    return obj


def load_model_config() -> dict:
    config_path = Path(__file__).parent / "models.yaml"
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return _expand_dict(raw)


def get_litellm_params(model_string: str, config: dict) -> dict:
    if "/" not in model_string:
        raise ValueError(f"Model must be 'provider/model', got: {model_string}")

    provider, model = model_string.split("/", 1)
    provider_config = config.get("providers", {}).get(provider)

    if not provider_config:
        raise ValueError(f"Provider '{provider}' not in models.yaml")

    params = {"model": model_string}

    if provider == "ollama":
        params["api_base"] = provider_config.get("base_url", "http://localhost:11434")
    elif provider == "openai":
        params["api_key"] = provider_config.get("api_key", "")
    elif provider == "anthropic":
        params["api_key"] = provider_config.get("api_key", "")
    elif provider == "gemini":
        params["api_key"] = provider_config.get("api_key", "")
    elif provider == "deepseek":
        params["api_key"] = provider_config.get("api_key", "")
        params["api_base"] = "https://api.deepseek.com/v1"
    elif provider == "kimi":
        params["api_key"] = provider_config.get("api_key", "")
        params["api_base"] = provider_config.get("base_url", "https://api.moonshot.ai/v1")

    return params


def get_default_model(config: dict) -> str:
    return config.get("default_model", "anthropic/claude-sonnet-4-5")


def get_fallback_model(config: dict) -> str:
    return config.get("fallback_model", "")

# Now rewrite llm/router.py:

