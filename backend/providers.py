"""
App-specific implementations of the Temporal provider protocols.

These classes wire up the abstract ``temporal`` package to this project's
concrete dependencies (Gemini LLM, placeholder memory store, in-memory
world state).

To swap to a different LLM, memory store, or state backend, simply write
new classes that satisfy the same protocols and register them instead.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

import google.generativeai as genai

from core.config import settings
from models.state import WorldState
from temporal import (
    AgentAction,
    AgentStateUpdate,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    MemoryProvider,
    MemoryQuery,
    MemoryResult,
    StateProvider,
)

if TYPE_CHECKING:
    from services.memory_store import MemoryStore


# ---------------------------------------------------------------------------
# LLM Provider — Gemini
# ---------------------------------------------------------------------------


class GeminiLLMProvider:
    """LLM provider backed by the Google Gemini API."""

    def __init__(self, api_key: str | None = None, default_model: str = "gemini-2.5-flash"):
        self._api_key = api_key or settings.gemini_api_key
        self._default_model = default_model
        if self._api_key:
            genai.configure(api_key=self._api_key)

    async def call(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        model_name = request.model_name if request.model_name != "default" else self._default_model
        model = genai.GenerativeModel(model_name)

        response = model.generate_content(
            request.prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=request.temperature,
                max_output_tokens=request.max_tokens,
            ),
        )

        text = response.text if response.text else ""

        return LLMResponse(text=text, model_name=model_name)


# ---------------------------------------------------------------------------
# Memory Provider — placeholder
# ---------------------------------------------------------------------------


class PlaceholderMemoryProvider:
    """Stub memory provider — used when no MemoryStore is available."""

    async def retrieve(self, query: MemoryQuery) -> MemoryResult:
        return MemoryResult(
            agent_id=query.agent_id,
            memories=[
                f"[placeholder] No memory store connected for agent {query.agent_id}."
            ],
        )


class LlamaIndexMemoryProvider:
    """Memory provider backed by the LlamaIndex MemoryStore."""

    def __init__(self, memory_store: MemoryStore):
        self._store = memory_store

    async def retrieve(self, query: MemoryQuery) -> MemoryResult:
        results = self._store.retrieve(
            agent_id=query.agent_id,
            query=query.context,
            top_k=query.top_k,
        )
        memories = [text for text, _score in results]
        if not memories:
            memories = [f"No relevant memories found for agent {query.agent_id}."]
        return MemoryResult(agent_id=query.agent_id, memories=memories)


# ---------------------------------------------------------------------------
# State Provider — shared world state
# ---------------------------------------------------------------------------


class SharedWorldStateProvider:
    """State provider that mutates the real WorldState in-place.

    This ensures that both the REST API endpoints and Temporal workflow
    activities operate on the same world state object.
    """

    def __init__(self, world_state: WorldState):
        self._world_state = world_state

    async def apply_action(self, action: AgentAction) -> AgentStateUpdate:
        # Find the agent in the shared world state and mutate in-place
        for agent in self._world_state.agents:
            if agent.id == action.agent_id:
                agent.current_action = action.action_description
                if action.target_location_id:
                    agent.location_id = action.target_location_id
                if action.target_x is not None:
                    agent.x = action.target_x
                if action.target_y is not None:
                    agent.y = action.target_y
                return AgentStateUpdate(
                    agent_id=action.agent_id,
                    new_action=agent.current_action,
                    new_location_id=agent.location_id,
                    new_x=agent.x,
                    new_y=agent.y,
                )

        # Agent not found — return a passthrough result
        return AgentStateUpdate(
            agent_id=action.agent_id,
            new_action=action.action_description,
            new_location_id=action.target_location_id or "town_square",
            new_x=action.target_x or 0,
            new_y=action.target_y or 0,
        )


# ---------------------------------------------------------------------------
# Bootstrap helper — called once at startup
# ---------------------------------------------------------------------------


def bootstrap_providers(
    memory_store: Optional[MemoryStore] = None,
    world_state: Optional[WorldState] = None,
) -> None:
    """Register the default providers for this application.

    Call this **before** starting the Temporal worker or connecting
    the FastAPI Temporal client.
    """
    from temporal import (
        register_llm_provider,
        register_memory_provider,
        register_state_provider,
    )

    register_llm_provider(GeminiLLMProvider())

    if memory_store is not None:
        register_memory_provider(LlamaIndexMemoryProvider(memory_store))
    else:
        register_memory_provider(PlaceholderMemoryProvider())

    if world_state is not None:
        register_state_provider(SharedWorldStateProvider(world_state))
    else:
        # Fallback: passthrough for testing without a world state
        register_state_provider(SharedWorldStateProvider(WorldState(
            environment_root={"id": "world", "name": "World", "description": "Empty world", "node_type": "world"},
            agents=[],
        )))

