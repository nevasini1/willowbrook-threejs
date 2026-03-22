"""
Temporal Client helper.

Provides a cached async connection to the Temporal server.
All configuration is passed as arguments — the package does NOT import
any app-specific config modules.
"""

from __future__ import annotations

from typing import Optional

from temporalio.client import Client

_client: Optional[Client] = None
_host: str = "localhost:7233"
_namespace: str = "default"


def configure(*, host: str = "localhost:7233", namespace: str = "default") -> None:
    """Set connection parameters *before* the first ``get_client()`` call.

    Call this once at application startup (e.g. in your FastAPI lifespan
    or before ``run_worker``).
    """
    global _host, _namespace
    _host = host
    _namespace = namespace


async def get_client() -> Client:
    """Return a cached Temporal Client, connecting on first call."""
    global _client
    if _client is None:
        _client = await Client.connect(_host, namespace=_namespace)
    return _client


async def close_client() -> None:
    """Reset the cached Temporal Client (call on shutdown)."""
    global _client
    _client = None
