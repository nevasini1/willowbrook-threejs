"""
Temporal Activities — side-effectful units of work that can fail and be retried.

Activities call through registered *providers* (see ``_registry.py``)
rather than importing app-specific code.  This makes the package
reusable with any LLM, memory store, or state executor.
"""

from __future__ import annotations

import json

from temporalio import activity

from temporal._registry import get_registry
from temporal._types import (
    AgentAction,
    AgentStateUpdate,
    DailyPlan,
    DailyPlanRequest,
    LLMRequest,
    LLMResponse,
    MemoryQuery,
    MemoryResult,
)

# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@activity.defn(name="call_llm")
async def call_llm(request: LLMRequest) -> LLMResponse:
    """Call the registered LLM provider and return the response.

    Temporal will automatically retry on transient failures according to
    the retry policy set by the calling workflow.
    """
    provider = get_registry().require_llm()

    activity.logger.info(
        "call_llm: model=%s prompt_len=%d", request.model_name, len(request.prompt)
    )

    return await provider.call(request)


@activity.defn(name="retrieve_memories")
async def retrieve_memories(query: MemoryQuery) -> MemoryResult:
    """Retrieve relevant memories via the registered memory provider."""
    provider = get_registry().require_memory()

    activity.logger.info(
        "retrieve_memories: agent=%s context_len=%d top_k=%d",
        query.agent_id,
        len(query.context),
        query.top_k,
    )

    return await provider.retrieve(query)


@activity.defn(name="update_world_state")
async def update_world_state(action: AgentAction) -> AgentStateUpdate:
    """Apply an agent action via the registered state provider."""
    provider = get_registry().require_state()

    activity.logger.info(
        "update_world_state: agent=%s action=%s",
        action.agent_id,
        action.action_description,
    )

    return await provider.apply_action(action)


@activity.defn(name="generate_daily_plan")
async def generate_daily_plan(request: DailyPlanRequest) -> DailyPlan:
    """Generate a daily plan for an agent using the LLM provider."""
    provider = get_registry().require_llm()

    activity.logger.info(
        "generate_daily_plan: agent=%s (%s)", request.agent_id, request.agent_name
    )

    prompt = (
        f"You are {request.agent_name}. {request.persona}\n\n"
        f"Summary of yesterday: {request.previous_day_summary}\n\n"
        "Generate a detailed daily plan with 5-8 steps for today. "
        "Return the plan as a JSON array of strings, each string being one step.\n"
        'Example: ["Wake up and stretch", "Make breakfast", ...]\n'
        "Respond ONLY with the JSON array."
    )

    llm_response = await provider.call(
        LLMRequest(prompt=prompt, temperature=0.8, max_tokens=512)
    )

    text = llm_response.text or "[]"

    # Try to parse as JSON array; fall back to splitting by newline.
    try:
        steps = json.loads(text)
        if not isinstance(steps, list):
            steps = [str(steps)]
    except json.JSONDecodeError:
        steps = [line.strip("- ") for line in text.strip().splitlines() if line.strip()]

    return DailyPlan(agent_id=request.agent_id, plan_steps=steps)
