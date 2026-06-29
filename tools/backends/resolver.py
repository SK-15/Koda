from tools.backends.base import WorkspaceBackend
from tools.backends.local import LocalFsBackend


def resolve_backend(state: dict, config: dict | None = None) -> WorkspaceBackend:
    """Pick the workspace backend for the current run.

    A live backend (e.g. ClientProxyBackend bound to a socket) is passed in via
    config["configurable"]["backend"] by the caller that owns the connection.
    With no backend supplied, we fall back to LocalFsBackend so existing
    REST / background runs behave exactly as before.
    """
    if config:
        configurable = config.get("configurable") or {}
        backend = configurable.get("backend")
        if isinstance(backend, WorkspaceBackend):
            return backend
    return LocalFsBackend()
