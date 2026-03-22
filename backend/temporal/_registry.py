"""
Provider registry — global store for pluggable backend implementations.

Register providers **before** starting the Temporal worker.  Activities
look up providers from this registry at call time, so they never import
app-specific code directly.
"""

from __future__ import annotations

from typing import Optional

from temporal._types import LLMProvider, MemoryProvider, StateProvider


class _Registry:
    """Holds the currently registered providers."""

    def __init__(self) -> None:
        self.llm: Optional[LLMProvider] = None
        self.memory: Optional[MemoryProvider] = None
        self.state: Optional[StateProvider] = None

    # -- convenience helpers -------------------------------------------

    def require_llm(self) -> LLMProvider:
        if self.llm is None:
            raise RuntimeError(
                "No LLMProvider registered. "
                "Call temporal.registry.register_llm_provider() before starting the worker."
            )
        return self.llm

    def require_memory(self) -> MemoryProvider:
        if self.memory is None:
            raise RuntimeError(
                "No MemoryProvider registered. "
                "Call temporal.registry.register_memory_provider() before starting the worker."
            )
        return self.memory

    def require_state(self) -> StateProvider:
        if self.state is None:
            raise RuntimeError(
                "No StateProvider registered. "
                "Call temporal.registry.register_state_provider() before starting the worker."
            )
        return self.state


# Module-level singleton
_registry = _Registry()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_llm_provider(provider: LLMProvider) -> None:
    """Register the LLM provider that activities will use."""
    _registry.llm = provider


def register_memory_provider(provider: MemoryProvider) -> None:
    """Register the memory-retrieval provider that activities will use."""
    _registry.memory = provider


def register_state_provider(provider: StateProvider) -> None:
    """Register the state-update provider that activities will use."""
    _registry.state = provider


def get_registry() -> _Registry:
    """Return the global registry (for internal use by activities)."""
    return _registry
