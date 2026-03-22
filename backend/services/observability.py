"""
Observability — Langfuse integration for tracing agent actions.

Provides decorators and helpers to capture traces for every LLM call,
tool invocation, and agent lifecycle event.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional

from core.config import settings

logger = logging.getLogger(__name__)

_langfuse_client: Optional[Any] = None


def init_langfuse() -> None:
    """Initialize the Langfuse client singleton if enabled."""
    global _langfuse_client
    if not settings.langfuse_enabled:
        logger.info("Langfuse observability disabled.")
        return

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
    except ImportError:
        logger.warning("langfuse package not installed — observability disabled.")
    except Exception as e:
        logger.warning("Failed to initialize Langfuse: %s", e)


def get_langfuse() -> Optional[Any]:
    """Return the Langfuse client or None if not available."""
    return _langfuse_client


def flush_langfuse() -> None:
    """Flush pending events on shutdown."""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            logger.info("Langfuse flushed.")
        except Exception as e:
            logger.warning("Langfuse flush error: %s", e)


def trace_agent_action(name: str) -> Callable:
    """Async decorator that wraps a function with a Langfuse trace.

    Captures agent_id (first positional arg after self), prompt input,
    output, latency, and errors.

    Usage:
        @trace_agent_action("chat")
        async def chat(self, agent_id: str, message: str) -> str:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = _langfuse_client
            if client is None:
                return await func(*args, **kwargs)

            # Extract agent_id from first arg after self
            agent_id = args[1] if len(args) > 1 else kwargs.get("agent_id", "unknown")

            trace = client.trace(
                name=name,
                metadata={"agent_id": agent_id},
            )
            span = trace.span(
                name=f"{name}_execution",
                input={"agent_id": agent_id, "args": str(args[2:]), "kwargs": {k: str(v) for k, v in kwargs.items()}},
            )

            start = time.time()
            try:
                result = await func(*args, **kwargs)
                latency = time.time() - start
                span.end(
                    output={"result": str(result)[:2000]},
                    metadata={"latency_ms": round(latency * 1000)},
                )
                return result
            except Exception as e:
                latency = time.time() - start
                span.end(
                    output={"error": str(e)},
                    level="ERROR",
                    metadata={"latency_ms": round(latency * 1000)},
                )
                raise

        return wrapper

    return decorator
