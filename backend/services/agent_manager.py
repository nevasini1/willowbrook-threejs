"""
AgentManager — central orchestrator for Agno-powered world agents.

Handles agent lifecycle: creation, chat, inner-voice commands,
autonomous ticks (plan-aware), reflection, social graph, and
agent-to-agent Team conversations.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Optional

from agno.agent import Agent
from agno.team import Team, TeamMode

from models.state import AgentState, EnvironmentNode, NodeType, WorldState
from services.agno_storage import create_agent
from services.observability import trace_agent_action
from services.planner import Planner
from services.world_tools import WorldTools

if TYPE_CHECKING:
    from services.memory_store import MemoryStore
    from services.reflection import ReflectionEngine
    from services.social_graph import SocialGraph

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages Agno agents and their interaction with the world."""

    def __init__(
        self,
        world_state: WorldState,
        memory_store: Optional[MemoryStore] = None,
        social_graph: Optional[SocialGraph] = None,
        reflection_engine: Optional[ReflectionEngine] = None,
    ):
        self.world_state = world_state
        self.memory_store = memory_store
        self.social_graph = social_graph
        self.reflection_engine = reflection_engine
        self.planner = Planner(memory_store=memory_store)
        self.agents: dict[str, Agent] = {}
        self._agent_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Spawn helpers — guarantee agents land in walkable, open tiles
    # ------------------------------------------------------------------

    def _collect_walkable_spawns(self) -> list[tuple[str, int, int]]:
        """Return a list of (location_id, x, y) tuples for every tile that is
        inside a walkable node *and* not blocked by a non-walkable child.

        Zones, rooms, and the world root are valid location containers.
        Object nodes are never used as spawn locations.  Buildings are
        skipped at the top level (they are not walkable themselves), but
        their walkable room children are included via recursion.
        """

        def _gather(node: EnvironmentNode) -> list[tuple[str, int, int]]:
            results: list[tuple[str, int, int]] = []

            # Only zones, rooms, and the world root can host agents.
            is_container = node.node_type in (
                NodeType.WORLD, NodeType.ZONE, NodeType.ROOM
            )

            if is_container and node.walkable:
                # Tiles within this node that are covered by a non-walkable
                # child (wall, object, building exterior, …) are blocked.
                blocked: set[tuple[int, int]] = set()
                for child in node.children:
                    if not child.walkable:
                        for cx in range(child.x, child.x + child.w):
                            for cy in range(child.y, child.y + child.h):
                                blocked.add((cx, cy))

                # Emit every open tile.
                for tx in range(node.x, node.x + node.w):
                    for ty in range(node.y, node.y + node.h):
                        if (tx, ty) not in blocked:
                            results.append((node.id, tx, ty))

            # Always recurse so rooms inside buildings are found.
            for child in node.children:
                results.extend(_gather(child))

            return results

        return _gather(self.world_state.environment_root)

    def _pick_walkable_spawn(
        self,
        spawns: list[tuple[str, int, int]],
        preferred_location_id: Optional[str] = None,
        rng: Optional[random.Random] = None,
        max_retries: int = 50,
    ) -> tuple[str, int, int]:
        """Pick a random walkable spawn point, retrying until a reachable
        tile is found.

        If *preferred_location_id* is given and has open tiles, the
        result is restricted to that location so the agent's intended
        home area is respected.  Falls back to any open tile otherwise.

        Retries up to *max_retries* times to guarantee the chosen tile is
        present in the walkable catalogue.  If the catalogue is exhausted
        without a valid pick, returns the world-root origin as a last resort.
        """
        if rng is None:
            rng = random.Random()

        if not spawns:
            # Absolute fallback — world origin (should never happen).
            root = self.world_state.environment_root
            return (root.id, root.x, root.y)

        # Build the candidate pool (preferred zone first, then all spawns).
        pool: list[tuple[str, int, int]] = []
        if preferred_location_id:
            preferred = [s for s in spawns if s[0] == preferred_location_id]
            pool = preferred if preferred else spawns
        else:
            pool = spawns

        spawn_set: set[tuple[str, int, int]] = set(pool)

        # Retry until we land on a confirmed reachable tile.
        for attempt in range(max_retries):
            candidate = rng.choice(pool)
            if candidate in spawn_set:
                return candidate
            logger.debug(
                "Spawn candidate %s not reachable on attempt %d — retrying.",
                candidate,
                attempt + 1,
            )

        # All retries exhausted — return any tile from the pool.
        logger.warning(
            "_pick_walkable_spawn: gave up after %d retries, using first pool entry.",
            max_retries,
        )
        return pool[0]

    def initialize_agents(self) -> None:
        """Create an Agno agent for every agent in the world state.

        Each agent's starting position is validated against the
        walkability map.  If the seed position lands inside a wall or
        non-walkable structure, a safe walkable tile is chosen instead.
        """
        # Build the walkable-spawn catalogue once for all agents.
        walkable_spawns = self._collect_walkable_spawns()
        walkable_set: set[tuple[str, int, int]] = set(walkable_spawns)

        # Initialize memory indexes if a store is available.
        if self.memory_store is not None:
            agent_ids = [a.id for a in self.world_state.agents]
            self.memory_store.initialize(agent_ids)

        for agent_state in self.world_state.agents:
            # --- Validate / fix spawn location ----------------------------
            # A seed position is valid only when:
            #   1. The location_id belongs to a walkable container.
            #   2. The exact (location_id, x, y) tile is open (not blocked).
            location_valid = any(
                s[0] == agent_state.location_id for s in walkable_spawns
            )
            tile_valid = (
                agent_state.location_id,
                agent_state.x,
                agent_state.y,
            ) in walkable_set

            if not location_valid or not tile_valid:
                rng = random.Random(hash(agent_state.id))
                chosen_loc, chosen_x, chosen_y = self._pick_walkable_spawn(
                    walkable_spawns,
                    # Keep the agent in their preferred zone when possible.
                    preferred_location_id=(
                        agent_state.location_id if location_valid else None
                    ),
                    rng=rng,
                )
                logger.warning(
                    "Agent %s had invalid spawn (%s, %d, %d) — "
                    "relocated to (%s, %d, %d)",
                    agent_state.id,
                    agent_state.location_id,
                    agent_state.x,
                    agent_state.y,
                    chosen_loc,
                    chosen_x,
                    chosen_y,
                )
                agent_state.location_id = chosen_loc
                agent_state.x = chosen_x
                agent_state.y = chosen_y
            else:
                logger.debug(
                    "Agent %s spawn OK at (%s, %d, %d)",
                    agent_state.id,
                    agent_state.location_id,
                    agent_state.x,
                    agent_state.y,
                )

            # --- Create Agno agent ----------------------------------------
            tools = WorldTools(
                agent_id=agent_state.id,
                world_state=self.world_state,
                memory_store=self.memory_store,
                social_graph=self.social_graph,
            )
            agent = create_agent(
                agent_id=agent_state.id,
                name=agent_state.name,
                description=agent_state.description,
                instructions=agent_state.instructions,
                role=agent_state.role,
                tools=[tools],
            )
            self.agents[agent_state.id] = agent
            self._agent_locks[agent_state.id] = asyncio.Lock()
            logger.info("Initialized agent: %s (%s)", agent_state.name, agent_state.id)

        logger.info("All %d agents initialized.", len(self.agents))

    # ------------------------------------------------------------------
    # Mood helpers
    # ------------------------------------------------------------------

    _MOOD_POSITIVE = {
        "love", "like", "great", "happy", "wonderful", "amazing", "good",
        "friend", "thanks", "enjoy", "glad", "nice", "kind", "welcome",
        "beautiful", "helpful", "appreciate", "excited", "joy", "fun",
    }
    _MOOD_NEGATIVE = {
        "hate", "dislike", "angry", "bad", "terrible", "awful", "annoying",
        "stupid", "ugly", "enemy", "rude", "mean", "horrible", "sad",
        "upset", "disappointed", "frustrating", "worst", "lonely", "scared",
    }
    _MOOD_TRANSITIONS = {
        "happy": {"up": "excited", "down": "neutral"},
        "excited": {"up": "excited", "down": "happy"},
        "neutral": {"up": "happy", "down": "sad"},
        "sad": {"up": "neutral", "down": "angry"},
        "angry": {"up": "sad", "down": "angry"},
        "anxious": {"up": "neutral", "down": "sad"},
    }

    def _update_mood(
        self, agent_state: AgentState, response_text: str, pending_messages: list[dict]
    ) -> None:
        """Update agent mood using keyword heuristics + social context.

        Considers:
        1. Keywords in the agent's own response text
        2. Keywords in incoming messages
        3. Relationship context — messages from rivals/enemies amplify negativity,
           messages from close friends amplify positivity
        """
        # Score the agent's own response
        own_words = response_text.lower().split()
        pos = sum(1 for w in own_words if w.strip(".,!?\"'") in self._MOOD_POSITIVE)
        neg = sum(1 for w in own_words if w.strip(".,!?\"'") in self._MOOD_NEGATIVE)

        # Score incoming messages with relationship weighting
        for msg in pending_messages:
            msg_words = msg.get("message", "").lower().split()
            msg_pos = sum(1 for w in msg_words if w.strip(".,!?\"'") in self._MOOD_POSITIVE)
            msg_neg = sum(1 for w in msg_words if w.strip(".,!?\"'") in self._MOOD_NEGATIVE)

            # Weight by relationship: messages from close friends boost positivity,
            # messages from rivals/enemies boost negativity
            weight = 1.0
            if self.social_graph is not None:
                rel = self.social_graph.get_relationship(agent_state.id, msg.get("from_agent", ""))
                if rel is not None:
                    if rel.strength >= 0.4:
                        # Friend/close friend: positive words count more
                        weight = 1.0 + rel.strength  # up to 2.0x
                    elif rel.strength < 0.0:
                        # Rival/enemy: negative words count more
                        weight = 1.0 + abs(rel.strength)  # up to 2.0x

            pos += int(msg_pos * weight)
            neg += int(msg_neg * weight)

        current = agent_state.mood
        transitions = self._MOOD_TRANSITIONS.get(current, {"up": "neutral", "down": "neutral"})

        if pos > neg + 1:
            agent_state.mood = transitions["up"]
        elif neg > pos + 1:
            agent_state.mood = transitions["down"]
        # else: mood stays the same (conservative)

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _build_memory_context(
        self, agent_id: str, situation: str, top_k: int = 5
    ) -> str:
        """Retrieve relevant memories and format them as prompt context."""
        parts: list[str] = []

        if self.memory_store is not None:
            memories = self.memory_store.retrieve(agent_id, situation, top_k=top_k)
            if memories:
                lines = ["\n[MEMORIES] Relevant past experiences:"]
                for text, _score in memories:
                    lines.append(f"  - {text}")
                lines.append("Use these to inform your response if relevant.")
                parts.append("\n".join(lines))

        if self.social_graph is not None:
            social_context = self.social_graph.format_for_prompt(agent_id)
            if social_context:
                parts.append(social_context)

        # Nearby awareness: location events
        agent_state = self._get_agent_state(agent_id)
        if agent_state is not None:
            loc_events = self.world_state.location_events.get(agent_state.location_id, [])
            other_events = [e for e in loc_events if e.get("agent_id") != agent_id]
            if other_events:
                lines = ["\n[NEARBY] Recent activity at your location:"]
                for evt in other_events[-4:]:
                    lines.append(f"  - {evt['event']}")
                parts.append("\n".join(lines))

        return "\n".join(parts)

    def _record_response(self, agent_id: str, text: str, category: str) -> None:
        """Record an agent's response as a memory and trigger reflection check."""
        if self.memory_store is None or not text:
            return

        importance = self.memory_store.add_memory(
            agent_id, text, metadata={"category": category}
        )

        # Accumulate importance for reflection
        if self.reflection_engine is not None:
            self.reflection_engine.accumulate_importance(agent_id, importance)
            if self.reflection_engine.check_threshold(agent_id):
                # Fire-and-forget reflection generation
                asyncio.ensure_future(self._run_reflection(agent_id))

    async def _run_reflection(self, agent_id: str) -> None:
        """Run reflection generation in the background."""
        if self.reflection_engine is None:
            return
        agent_state = self._get_agent_state(agent_id)
        name = agent_state.name if agent_state else agent_id
        try:
            reflections = self.reflection_engine.generate_reflections(agent_id, name)
            logger.info("Generated %d reflections for %s", len(reflections), agent_id)
        except Exception as e:
            logger.warning("Reflection failed for %s: %s", agent_id, e)

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    def _ensure_plan(self, agent_state: AgentState) -> None:
        """Generate a plan if the agent doesn't have one or has exhausted it."""
        needs_plan = (
            agent_state.daily_plan is None
            or agent_state.current_plan_step >= len(agent_state.daily_plan)
        )
        if not needs_plan:
            return

        # Retrieve top-3 reflection memories for planning context
        reflection_context = ""
        if self.memory_store is not None:
            reflections = self.memory_store.retrieve(
                agent_state.id, "my reflections and insights", top_k=3
            )
            if reflections:
                reflection_context = "\n".join(f"  - {text}" for text, _score in reflections)

        # Inject relationship context so the plan accounts for social bonds
        relationship_context = ""
        if self.social_graph is not None:
            relationship_context = self.social_graph.format_for_prompt(agent_state.id)

        steps = self.planner.generate_plan(
            agent_id=agent_state.id,
            name=agent_state.name,
            persona=agent_state.description,
            location=agent_state.location_id,
            reflection_context=reflection_context,
            mood=agent_state.mood,
            relationship_context=relationship_context,
        )
        agent_state.daily_plan = steps
        agent_state.current_plan_step = 0

        # Record the plan as a memory
        plan_text = f"My plan for today: {'; '.join(steps)}"
        if self.memory_store is not None:
            self.memory_store.add_memory(
                agent_state.id, plan_text, metadata={"category": "plan"}
            )
        logger.info("Generated plan for %s: %s", agent_state.id, steps)

    def get_agent_plan(self, agent_id: str) -> Optional[dict]:
        """Return the current plan for an agent."""
        agent_state = self._get_agent_state(agent_id)
        if agent_state is None:
            return None
        return {
            "agent_id": agent_id,
            "daily_plan": agent_state.daily_plan or [],
            "current_step": agent_state.current_plan_step,
            "day_number": agent_state.day_number,
        }

    def regenerate_plan(self, agent_id: str) -> Optional[dict]:
        """Force regenerate a plan for an agent."""
        agent_state = self._get_agent_state(agent_id)
        if agent_state is None:
            return None
        agent_state.daily_plan = None
        self._ensure_plan(agent_state)
        return self.get_agent_plan(agent_id)

    # ------------------------------------------------------------------
    # Chat — user talks to an agent
    # ------------------------------------------------------------------

    @trace_agent_action("chat")
    async def chat(self, agent_id: str, message: str) -> str:
        """Handle a user talking to an agent."""
        agent = self.agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found."

        lock = self._agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[agent_id] = lock

        async with lock:
            agent_state = self._get_agent_state(agent_id)
            name = agent_state.name if agent_state else agent_id

            memory_context = self._build_memory_context(agent_id, message)

            prompt = (
                f"A visitor approaches you and says: \"{message}\"\n"
                f"Respond in character as {name}. "
                "You may use your tools if the conversation requires an action."
                f"{memory_context}"
            )

            result = await agent.arun(prompt)
            content = result.content if result and result.content else "(no response)"
            self._record_response(agent_id, f"Visitor said: \"{message}\". I responded: {content}", "agent_response")
            return content

    # ------------------------------------------------------------------
    # Inner voice — user commands an agent as a guiding voice
    # ------------------------------------------------------------------

    @trace_agent_action("inner_voice")
    async def inner_voice(self, agent_id: str, command: str) -> str:
        """Send an inner-voice directive to an agent."""
        agent = self.agents.get(agent_id)
        if not agent:
            return f"Agent '{agent_id}' not found."

        lock = self._agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[agent_id] = lock

        async with lock:
            memory_context = self._build_memory_context(agent_id, command)

            prompt = (
                f"[INNER VOICE] You feel a strong urge: {command}\n"
                "Act on this urge using the tools available to you. "
                "Narrate what you do briefly."
                f"{memory_context}"
            )

            result = await agent.arun(prompt)
            content = result.content if result and result.content else "(no response)"
            self._record_response(agent_id, f"Inner voice urged: \"{command}\". I did: {content}", "agent_response")
            return content

    # ------------------------------------------------------------------
    # Tick — autonomous decision-making (plan-aware)
    # ------------------------------------------------------------------

    @trace_agent_action("tick_agent")
    async def tick_agent(self, agent_id: str) -> dict:
        """Trigger one autonomous decision cycle for an agent.

        Uses the planning system: ensures a plan exists, includes the
        current step in the prompt, and advances the step when completed.
        Processes pending messages and updates mood.

        Acquires a per-agent lock so that concurrent tick_all calls
        serialize access to each agent's state (preventing race conditions
        when agent A talks to agent B while B is mid-tick).
        """
        lock = self._agent_locks.get(agent_id)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[agent_id] = lock

        async with lock:
            return await self._tick_agent_inner(agent_id)

    async def _tick_agent_inner(self, agent_id: str) -> dict:
        """Inner tick logic, called under the per-agent lock."""
        agent = self.agents.get(agent_id)
        if not agent:
            return {
                "agent_id": agent_id,
                "action": "error",
                "success": False,
                "detail": f"Agent '{agent_id}' not found.",
            }

        agent_state = self._get_agent_state(agent_id)
        location = ""
        if agent_state:
            location = agent_state.location_id
            self._ensure_plan(agent_state)

        # Process pending messages — snapshot and clear atomically
        pending = self.world_state.pending_messages.pop(agent_id, [])
        incoming_block = ""
        if pending:
            # Sort by timestamp so messages are processed in causal order
            pending.sort(key=lambda m: m.get("timestamp", 0))

            lines = ["\n[INCOMING MESSAGES] You received these messages:"]
            for msg in pending:
                lines.append(f"  - {msg['from_name']} said: \"{msg['message']}\"")
                # Record as memory
                if self.memory_store is not None:
                    self.memory_store.add_memory(
                        agent_id,
                        f"{msg['from_name']} said to me: \"{msg['message']}\"",
                        metadata={"category": "conversation_received"},
                    )
                # Update social graph for received message (async-safe)
                if self.social_graph is not None:
                    if hasattr(self.social_graph, "update_interaction_async"):
                        await self.social_graph.update_interaction_async(
                            agent_id, msg["from_agent"],
                            context=f"{msg['from_name']} said: \"{msg['message'][:100]}\"",
                        )
                    else:
                        self.social_graph.update_interaction(
                            agent_id, msg["from_agent"],
                            context=f"{msg['from_name']} said: \"{msg['message'][:100]}\"",
                        )
            lines.append("Consider responding or reacting to these messages.")
            incoming_block = "\n".join(lines)

        # Build plan context
        plan_context = ""
        if agent_state and agent_state.daily_plan:
            step_idx = agent_state.current_plan_step
            if step_idx < len(agent_state.daily_plan):
                current_step = agent_state.daily_plan[step_idx]
                plan_context = (
                    f"\n[PLAN] Your current plan step ({step_idx + 1}/{len(agent_state.daily_plan)}): "
                    f"{current_step}\n"
                    "Follow this plan step, or react to something more urgent if needed. "
                    "If you complete this step, include PLAN_STEP_COMPLETE in your response."
                )

        # Mood context
        mood_context = ""
        if agent_state and agent_state.mood != "neutral":
            mood_context = f"\n[MOOD] Your current mood is: {agent_state.mood}. Let this influence your behavior."

        situation = f"I am at '{location}'. What should I do next?"
        memory_context = self._build_memory_context(agent_id, situation)

        prompt = (
            "It is a new moment in your day. "
            f"You are currently at '{location}'. "
            "Decide what to do next. You can move, talk to someone nearby, "
            "interact with an object, or simply observe your surroundings. "
            "Use exactly one tool to take an action, then briefly narrate what you did."
            f"{mood_context}"
            f"{incoming_block}"
            f"{plan_context}"
            f"{memory_context}"
        )

        try:
            result = await agent.arun(prompt)
            content = result.content if result and result.content else ""
            action = agent_state.current_action if agent_state else "unknown"

            # Advance plan step if completed
            if agent_state and "PLAN_STEP_COMPLETE" in content:
                agent_state.current_plan_step += 1
                content = content.replace("PLAN_STEP_COMPLETE", "").strip()

            # Update mood based on response and received messages
            if agent_state:
                self._update_mood(agent_state, content, pending)

            self._record_response(agent_id, f"Tick at {location}: {content}", "agent_response")
            return {
                "agent_id": agent_id,
                "action": action,
                "success": True,
                "detail": content,
            }
        except Exception as e:
            logger.exception("Tick failed for %s", agent_id)
            return {
                "agent_id": agent_id,
                "action": "error",
                "success": False,
                "detail": str(e),
            }

    async def tick_all(self) -> list[dict]:
        """Tick all agents sequentially, then follow up on new messages.

        Sequential ticking ensures that messages sent by agent A during
        its tick are available in ``pending_messages`` when agent B ticks
        next.  After the first pass, any agent that received new messages
        during this cycle gets a follow-up tick so conversations resolve
        within a single tick cycle.
        """
        results: list[dict] = []

        # First pass — tick every agent in order
        for aid in self.agents:
            result = await self.tick_agent(aid)
            results.append(result)

        # Second pass — re-tick agents that received messages during this cycle
        agents_with_messages = [
            aid for aid in self.agents
            if self.world_state.pending_messages.get(aid)
        ]
        for aid in agents_with_messages:
            result = await self.tick_agent(aid)
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Team — agent-to-agent conversation
    # ------------------------------------------------------------------

    def create_conversation_team(self, agent_ids: list[str]) -> Optional[Team]:
        """Create an Agno Team in coordinate mode for multi-agent conversation."""
        members = [self.agents[aid] for aid in agent_ids if aid in self.agents]
        if len(members) < 2:
            return None

        team = Team(
            name="conversation",
            mode=TeamMode.coordinate,
            members=members,
            instructions=[
                "You are coordinating a conversation between the team members.",
                "Each member should respond in character.",
                "Keep the conversation natural and brief.",
            ],
        )
        return team

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_agent_state(self, agent_id: str) -> Optional[AgentState]:
        for agent in self.world_state.agents:
            if agent.id == agent_id:
                return agent
        return None
