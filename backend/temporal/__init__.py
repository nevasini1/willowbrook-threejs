"""
Temporal agent-orchestration package.

This package is a **self-contained, reusable** module for durable agent
orchestration.  It depends only on ``temporalio`` and defines abstract
provider protocols that the host application must implement.

Quick start::

    # 1. Implement the provider protocols
    from temporal import LLMProvider, MemoryProvider, StateProvider

    class MyLLM(LLMProvider):
        async def call(self, request): ...

    # 2. Register providers
    from temporal import register_llm_provider, register_memory_provider, register_state_provider
    register_llm_provider(MyLLM())
    register_memory_provider(MyMemory())
    register_state_provider(MyState())

    # 3. Configure the client connection
    from temporal.client import configure
    configure(host="localhost:7233", namespace="default")

    # 4. Start the worker
    from temporal.worker import run_worker
    await run_worker(task_queue="my-queue")
"""

# -- Provider protocols (the public contract) ----------------------------
from temporal._types import (
    AgentAction,
    AgentStateUpdate,
    DailyPlan,
    DailyPlanRequest,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    MemoryProvider,
    MemoryQuery,
    MemoryResult,
    StateProvider,
)

# -- Registry helpers (public API) ----------------------------------------
from temporal._registry import (
    register_llm_provider,
    register_memory_provider,
    register_state_provider,
)

# -- Workflow DTOs (needed by API layer to start workflows) ----------------
from temporal.workflows import (
    AgentInfo,
    AgentLifecycleInput,
    AgentTickInput,
    AgentTickResult,
    SimulationInput,
    WorldSimulationWorkflow,
    AgentLifecycleWorkflow,
    AgentTickWorkflow,
)

__all__ = [
    # Protocols
    "LLMProvider",
    "MemoryProvider",
    "StateProvider",
    # DTOs
    "LLMRequest",
    "LLMResponse",
    "MemoryQuery",
    "MemoryResult",
    "AgentAction",
    "AgentStateUpdate",
    "DailyPlanRequest",
    "DailyPlan",
    "AgentTickInput",
    "AgentTickResult",
    "AgentLifecycleInput",
    "SimulationInput",
    "AgentInfo",
    # Workflows
    "WorldSimulationWorkflow",
    "AgentLifecycleWorkflow",
    "AgentTickWorkflow",
    # Registration
    "register_llm_provider",
    "register_memory_provider",
    "register_state_provider",
]
