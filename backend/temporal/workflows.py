"""
Temporal Workflows — deterministic orchestration logic.

Workflows coordinate activities and survive server crashes.  They MUST NOT
perform I/O directly; all side-effects are delegated to activities.

This module has *no* app-specific imports — it only references DTOs and
activity stubs defined within the ``temporal`` package itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import List

from temporalio import workflow
from temporalio.common import RetryPolicy

# Activities are imported inside a pass-through block so the workflow
# sandbox doesn't try to import their transitive dependencies.
with workflow.unsafe.imports_passed_through():
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
    from temporal.activities import (
        call_llm,
        generate_daily_plan,
        retrieve_memories,
        update_world_state,
    )

# ---------------------------------------------------------------------------
# Shared retry policy
# ---------------------------------------------------------------------------

DEFAULT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)

# ---------------------------------------------------------------------------
# Data-transfer objects for workflow I/O
# ---------------------------------------------------------------------------


@dataclass
class AgentTickInput:
    """Input for a single agent tick."""
    agent_id: str
    agent_name: str
    current_location_id: str
    current_action: str
    observations: str = ""


@dataclass
class AgentTickResult:
    """Output of a single agent tick."""
    agent_id: str
    new_action: str
    new_location_id: str
    new_x: int
    new_y: int
    llm_reasoning: str = ""


@dataclass
class AgentLifecycleInput:
    """Input for the per-agent lifecycle workflow."""
    agent_id: str
    agent_name: str
    persona: str
    current_location_id: str
    current_action: str
    day_number: int = 1


@dataclass
class SimulationInput:
    """Input for the world simulation workflow."""
    tick_interval_seconds: int = 10
    max_ticks_before_continue_as_new: int = 100
    agents: List[AgentInfo] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.agents is None:
            self.agents = []


@dataclass
class AgentInfo:
    """Minimal agent info for the simulation workflow."""
    agent_id: str
    agent_name: str
    persona: str
    current_location_id: str
    current_action: str


# ---------------------------------------------------------------------------
# 1. AgentTickWorkflow — single simulation tick for one agent
# ---------------------------------------------------------------------------


@workflow.defn(name="AgentTickWorkflow")
class AgentTickWorkflow:
    """Execute one simulation tick for a single agent.

    Steps:
      1. Retrieve relevant memories for the current context.
      2. Call LLM to decide the next action.
      3. Apply the action to the world state.
    """

    @workflow.run
    async def run(self, input: AgentTickInput) -> AgentTickResult:
        workflow.logger.info(
            "AgentTick started for %s (%s)", input.agent_id, input.agent_name
        )

        # --- Step 1: Retrieve memories ---
        context = (
            f"Agent {input.agent_name} is at {input.current_location_id}, "
            f"currently: {input.current_action}. "
            f"Observations: {input.observations}"
        )

        memory_result: MemoryResult = await workflow.execute_activity(
            retrieve_memories,
            MemoryQuery(agent_id=input.agent_id, context=context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY,
        )

        # --- Step 2: Ask LLM to decide ---
        memories_text = "\n".join(memory_result.memories)
        decision_prompt = (
            f"You are {input.agent_name}.\n"
            f"You are currently at: {input.current_location_id}\n"
            f"You are doing: {input.current_action}\n"
            f"Your observations: {input.observations}\n\n"
            f"Your relevant memories:\n{memories_text}\n\n"
            "Based on the above, decide your next action. "
            "Respond in this exact JSON format:\n"
            '{"action": "<what you will do next>", '
            '"location": "<where you will go (location_id)>", '
            '"x": <grid_x>, "y": <grid_y>}\n'
            "Respond ONLY with the JSON."
        )

        llm_response: LLMResponse = await workflow.execute_activity(
            call_llm,
            LLMRequest(prompt=decision_prompt),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY,
        )

        # Parse the LLM response — best-effort JSON extraction
        import json

        action_desc = input.current_action
        location_id = input.current_location_id
        new_x, new_y = 0, 0

        try:
            parsed = json.loads(llm_response.text)
            action_desc = parsed.get("action", action_desc)
            location_id = parsed.get("location", location_id)
            new_x = int(parsed.get("x", 0))
            new_y = int(parsed.get("y", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            workflow.logger.warning(
                "Could not parse LLM response as JSON, using raw text: %s",
                llm_response.text[:200],
            )
            action_desc = llm_response.text[:200]

        # --- Step 3: Update world state ---
        state_update: AgentStateUpdate = await workflow.execute_activity(
            update_world_state,
            AgentAction(
                agent_id=input.agent_id,
                action_description=action_desc,
                target_location_id=location_id,
                target_x=new_x,
                target_y=new_y,
            ),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=DEFAULT_RETRY,
        )

        return AgentTickResult(
            agent_id=input.agent_id,
            new_action=state_update.new_action,
            new_location_id=state_update.new_location_id,
            new_x=state_update.new_x,
            new_y=state_update.new_y,
            llm_reasoning=llm_response.text[:500],
        )


# ---------------------------------------------------------------------------
# 2. AgentLifecycleWorkflow — long-running per-agent workflow
# ---------------------------------------------------------------------------


@workflow.defn(name="AgentLifecycleWorkflow")
class AgentLifecycleWorkflow:
    """Manage a single agent's day: plan → tick loop → reflect.

    Uses Continue-As-New to keep event history bounded.
    """

    @workflow.run
    async def run(self, input: AgentLifecycleInput) -> str:
        workflow.logger.info(
            "AgentLifecycle started for %s day=%d",
            input.agent_id,
            input.day_number,
        )

        # --- Generate daily plan ---
        plan: DailyPlan = await workflow.execute_activity(
            generate_daily_plan,
            DailyPlanRequest(
                agent_id=input.agent_id,
                agent_name=input.agent_name,
                persona=input.persona,
                previous_day_summary=input.current_action,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY,
        )

        workflow.logger.info(
            "Daily plan for %s: %s", input.agent_id, plan.plan_steps
        )

        # --- Execute ticks for each plan step ---
        current_action = input.current_action
        current_location = input.current_location_id

        for step in plan.plan_steps:
            tick_result: AgentTickResult = await workflow.execute_child_workflow(
                AgentTickWorkflow.run,
                AgentTickInput(
                    agent_id=input.agent_id,
                    agent_name=input.agent_name,
                    current_location_id=current_location,
                    current_action=current_action,
                    observations=f"Plan step: {step}",
                ),
                id=f"agent-tick-{input.agent_id}-{uuid.uuid4().hex[:8]}",
            )
            current_action = tick_result.new_action
            current_location = tick_result.new_location_id

            # Small delay between ticks
            await workflow.sleep(timedelta(seconds=2))

        # --- Continue-As-New for next day ---
        workflow.continue_as_new(
            AgentLifecycleInput(
                agent_id=input.agent_id,
                agent_name=input.agent_name,
                persona=input.persona,
                current_location_id=current_location,
                current_action=current_action,
                day_number=input.day_number + 1,
            )
        )

        # Unreachable — continue_as_new raises internally
        return "continued"


# ---------------------------------------------------------------------------
# 3. WorldSimulationWorkflow — top-level orchestrator
# ---------------------------------------------------------------------------


@workflow.defn(name="WorldSimulationWorkflow")
class WorldSimulationWorkflow:
    """Orchestrate the entire world simulation.

    Fans out AgentTickWorkflow executions for all registered agents on
    each tick, collects results, and continues-as-new periodically to
    keep event history bounded.
    """

    def __init__(self) -> None:
        self._running: bool = True
        self._agents: List[AgentInfo] = []
        self._tick_count: int = 0

    # -- Signals -------------------------------------------------------

    @workflow.signal
    async def stop_simulation(self) -> None:
        """Signal to gracefully stop the simulation loop."""
        workflow.logger.info("Stop signal received")
        self._running = False

    @workflow.signal
    async def add_agent(self, agent: AgentInfo) -> None:
        """Signal to register a new agent mid-simulation."""
        workflow.logger.info("Adding agent %s", agent.agent_id)
        self._agents.append(agent)

    @workflow.signal
    async def agent_command(self, command: str) -> None:
        """Signal to inject an 'inner voice' command to an agent.

        Format: '<agent_id>:<command_text>'
        """
        workflow.logger.info("Agent command received: %s", command[:100])
        # TODO: route command to the appropriate agent's tick input.

    # -- Queries -------------------------------------------------------

    @workflow.query
    def get_status(self) -> dict:
        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "agent_count": len(self._agents),
            "agents": [a.agent_id for a in self._agents],
        }

    # -- Main loop -----------------------------------------------------

    @workflow.run
    async def run(self, input: SimulationInput) -> str:
        # Restore agents from continue-as-new (if any)
        if input.agents:
            for agent in input.agents:
                if agent.agent_id not in {a.agent_id for a in self._agents}:
                    self._agents.append(agent)

        workflow.logger.info(
            "WorldSimulation started: tick_interval=%ds, max_ticks=%d, restored_agents=%d",
            input.tick_interval_seconds,
            input.max_ticks_before_continue_as_new,
            len(self._agents),
        )

        while self._running and self._tick_count < input.max_ticks_before_continue_as_new:
            if not self._agents:
                await workflow.wait_condition(
                    lambda: len(self._agents) > 0 or not self._running
                )
                if not self._running:
                    break

            self._tick_count += 1
            workflow.logger.info(
                "Tick %d — processing %d agents",
                self._tick_count,
                len(self._agents),
            )

            # Fan out agent ticks in parallel
            tick_handles = []
            for agent in self._agents:
                handle = await workflow.start_child_workflow(
                    AgentTickWorkflow.run,
                    AgentTickInput(
                        agent_id=agent.agent_id,
                        agent_name=agent.agent_name,
                        current_location_id=agent.current_location_id,
                        current_action=agent.current_action,
                    ),
                    id=f"tick-{self._tick_count}-{agent.agent_id}-{uuid.uuid4().hex[:8]}",
                )
                tick_handles.append((agent, handle))

            # Collect results and update local agent state
            for agent, handle in tick_handles:
                try:
                    result: AgentTickResult = await handle
                    agent.current_action = result.new_action
                    agent.current_location_id = result.new_location_id
                except Exception as e:
                    workflow.logger.error(
                        "Tick failed for agent %s: %s", agent.agent_id, str(e)
                    )

            # Wait for the next tick interval
            await workflow.sleep(timedelta(seconds=input.tick_interval_seconds))

        # If we hit max ticks, continue-as-new to keep history bounded
        if self._running and self._tick_count >= input.max_ticks_before_continue_as_new:
            workflow.logger.info(
                "Continuing-as-new after %d ticks with %d agents",
                self._tick_count,
                len(self._agents),
            )
            workflow.continue_as_new(SimulationInput(
                tick_interval_seconds=input.tick_interval_seconds,
                max_ticks_before_continue_as_new=input.max_ticks_before_continue_as_new,
                agents=list(self._agents),
            ))

        return f"Simulation stopped after {self._tick_count} ticks"
