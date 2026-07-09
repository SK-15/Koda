import logging
import os

from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Whether Langfuse credentials are present in the environment."""
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )


def build_trace_config(user_id: str, session_id: str, org_id: str) -> dict:
    """Callbacks + metadata to splat into a graph invocation config.

    Returns {} when Langfuse isn't configured (e.g. local dev without keys),
    so callers can unconditionally merge this in without guarding.
    """
    if not is_configured():
        return {}

    try:
        handler = CallbackHandler()
    except Exception:
        logger.warning("Langfuse CallbackHandler construction failed; disabling tracing for this run", exc_info=True)
        return {}

    return {
        "callbacks": [handler],
        "metadata": {
            "langfuse_user_id": user_id,
            "langfuse_session_id": session_id,
            "org_id": org_id,
        },
    }
