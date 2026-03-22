"""
Abstract provider protocols for the Temporal agent-orchestration package.

Consumers implement these protocols and register them before starting the
worker.  The activities invoke the registered providers — they never import
app-specific code directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Serialisable data-transfer objects (shared across activities & workflows)
# ---------------------------------------------------------------------------


@dataclass
class LLMRequest:
    """Payload sent to the LLM provider."""
    prompt: str
    model_name: str = "default"
    temperature: float = 0.7
    max_tokens: int = 1024
    extra: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """Payload returned from the LLM provider."""
    text: str
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class MemoryQuery:
    """Input for memory retrieval."""
    agent_id: str
    context: str
    top_k: int = 10


@dataclass
class MemoryResult:
    """Output of memory retrieval."""
    agent_id: str
    memories: List[str]


@dataclass
class AgentAction:
    """An action an agent has decided to take."""
    agent_id: str
    action_description: str
    target_location_id: Optional[str] = None
    target_x: Optional[int] = None
    target_y: Optional[int] = None


@dataclass
class AgentStateUpdate:
    """Result of applying an agent action to the world."""
    agent_id: str
    new_action: str
    new_location_id: str
    new_x: int
    new_y: int


@dataclass
class DailyPlanRequest:
    """Input for daily-plan generation."""
    agent_id: str
    agent_name: str
    persona: str
    previous_day_summary: str


@dataclass
class DailyPlan:
    """A generated daily plan."""
    agent_id: str
    plan_steps: List[str]


# ---------------------------------------------------------------------------
# Provider protocols — the contracts that app-specific code must satisfy
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Anything that can handle an LLM request."""

    async def call(self, request: LLMRequest) -> LLMResponse:
        """Execute an LLM request and return the response."""
        ...


@runtime_checkable
class MemoryProvider(Protocol):
    """Anything that can retrieve agent memories."""

    async def retrieve(self, query: MemoryQuery) -> MemoryResult:
        """Retrieve memories relevant to the query."""
        ...


@runtime_checkable
class StateProvider(Protocol):
    """Anything that can apply an agent action to the world state."""

    async def apply_action(self, action: AgentAction) -> AgentStateUpdate:
        """Apply an agent action and return the resulting state."""
        ...
