"""
WorldTools — Agno Toolkit giving agents the ability to interact with the world.

Each agent gets its own WorldTools instance bound to its agent_id and a
shared WorldState reference.  The toolkit exposes five tools:

  move_to_location   — walk to a different location
  talk_to_agent      — say something to another agent at the same location
  interact_with_object — interact with a nearby object
  observe_surroundings — see what's around
  update_action      — change the agent's visible status
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

from agno.tools import Toolkit

from core.config import settings
from models.state import AgentState, EnvironmentNode, NodeType, WorldState

if TYPE_CHECKING:
    from services.memory_store import MemoryStore
    from services.social_graph import SocialGraph

logger = logging.getLogger(__name__)


class WorldTools(Toolkit):
    """Per-agent toolkit for world interaction."""

    def __init__(
        self,
        agent_id: str,
        world_state: WorldState,
        memory_store: Optional[MemoryStore] = None,
        social_graph: Optional[SocialGraph] = None,
    ):
        super().__init__(name="world_tools")
        self.agent_id = agent_id
        self.world_state = world_state
        self.memory_store = memory_store
        self.social_graph = social_graph

        self.register(self.move_to_location)
        self.register(self.talk_to_agent)
        self.register(self.interact_with_object)
        self.register(self.observe_surroundings)
        self.register(self.update_action)

    # ------------------------------------------------------------------
    # Helper methods (not exposed as tools)
    # ------------------------------------------------------------------

    def _find_agent(self, agent_id: str) -> Optional[AgentState]:
        """Find an agent by id in the world state."""
        for agent in self.world_state.agents:
            if agent.id == agent_id:
                return agent
        return None

    def _find_node(self, node_id: str, root: Optional[EnvironmentNode] = None) -> Optional[EnvironmentNode]:
        """Recursively find an EnvironmentNode by id."""
        if root is None:
            root = self.world_state.environment_root
        if root.id == node_id:
            return root
        for child in root.children:
            found = self._find_node(node_id, child)
            if found:
                return found
        return None

    def _get_parent_node(self, node_id: str, root: Optional[EnvironmentNode] = None) -> Optional[EnvironmentNode]:
        """Find the parent of a node."""
        if root is None:
            root = self.world_state.environment_root
        for child in root.children:
            if child.id == node_id:
                return root
            found = self._get_parent_node(node_id, child)
            if found:
                return found
        return None

    def _record(self, text: str, category: str) -> None:
        """Record an observation/action as a memory if a memory store is available."""
        if self.memory_store is not None:
            self.memory_store.add_memory(
                self.agent_id, text, metadata={"category": category}
            )

    def _get_agents_at_location(self, location_id: str) -> list[AgentState]:
        """Return all agents currently at a location."""
        return [a for a in self.world_state.agents if a.location_id == location_id]

    def _describe_node(self, node: EnvironmentNode, indent: int = 0) -> str:
        """Build a human-readable description of a node and its children."""
        prefix = "  " * indent
        lines = [f"{prefix}- {node.name} ({node.node_type.value}): {node.description}"]
        for child in node.children:
            lines.append(self._describe_node(child, indent + 1))
        return "\n".join(lines)

    def _collect_valid_locations(self) -> list[tuple[str, str]]:
        """Return (id, name) pairs for every walkable, non-object node in the world."""
        results: list[tuple[str, str]] = []

        def _gather(node: EnvironmentNode) -> None:
            if node.node_type not in (NodeType.OBJECT,) and node.walkable:
                results.append((node.id, node.name))
            for child in node.children:
                _gather(child)

        _gather(self.world_state.environment_root)
        return results

    def _log_location_event(self, location_id: str, event: str) -> None:
        """Append an event to location_events, capping per config."""
        if location_id not in self.world_state.location_events:
            self.world_state.location_events[location_id] = []
        self.world_state.location_events[location_id].append({
            "agent_id": self.agent_id,
            "event": event,
            "timestamp": time.time(),
        })
        max_events = settings.event_log_max_per_location
        self.world_state.location_events[location_id] = \
            self.world_state.location_events[location_id][-max_events:]

    def _find_walkable_position(self, node: EnvironmentNode) -> tuple[int, int]:
        """Find a walkable tile position within a node's bounds.

        Avoids tiles occupied by non-walkable child objects.
        Prefers tiles near the center of the node (more likely to be
        walkable on the visual tilemap).
        """
        import random

        # Collect blocked tiles from non-walkable children
        blocked: set[tuple[int, int]] = set()
        for child in node.children:
            if not child.walkable:
                for dx in range(child.w):
                    for dy in range(child.h):
                        blocked.add((child.x + dx, child.y + dy))

        # Collect all open tiles
        open_tiles = [
            (node.x + dx, node.y + dy)
            for dy in range(node.h)
            for dx in range(node.w)
            if (node.x + dx, node.y + dy) not in blocked
        ]

        if open_tiles:
            # Prefer tiles near the center of the node
            cx = node.x + node.w / 2
            cy = node.y + node.h / 2
            open_tiles.sort(key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
            inner_count = max(1, len(open_tiles) * 3 // 5)
            return random.choice(open_tiles[:inner_count])

        # Fallback: center of node
        return (node.x + node.w // 2, node.y + node.h // 2)

    @staticmethod
    def _quick_sentiment(text: str) -> float:
        """Keyword-based sentiment scoring from -1.0 to 1.0. No LLM call."""
        positive = {
            "love", "like", "great", "happy", "wonderful", "amazing", "good",
            "friend", "thanks", "thank", "enjoy", "glad", "nice", "kind",
            "welcome", "beautiful", "helpful", "appreciate", "excited", "joy",
        }
        negative = {
            "hate", "dislike", "angry", "bad", "terrible", "awful", "annoying",
            "stupid", "ugly", "enemy", "rude", "mean", "horrible", "disgusting",
            "furious", "sad", "upset", "disappointed", "frustrating", "worst",
        }
        words = text.lower().split()
        pos_count = sum(1 for w in words if w.strip(".,!?\"'") in positive)
        neg_count = sum(1 for w in words if w.strip(".,!?\"'") in negative)
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return (pos_count - neg_count) / total

    # ------------------------------------------------------------------
    # Tools (registered in __init__)
    # ------------------------------------------------------------------

    def move_to_location(self, location_id: str) -> str:
        """Move to a different location in the world.

        Args:
            location_id: The id of the location to move to (e.g. 'town_square', 'park_area').

        Returns:
            A message describing the result of the move.
        """
        agent = self._find_agent(self.agent_id)
        if not agent:
            return f"Error: agent '{self.agent_id}' not found."

        target = self._find_node(location_id)

        valid_locations = self._collect_valid_locations()
        valid_ids = {loc_id for loc_id, _ in valid_locations}
        valid_hint = (
            "Valid locations you can move to: "
            + ", ".join(f"{name} ({loc_id})" for loc_id, name in valid_locations)
        )

        if not target:
            return (
                f"Error: location '{location_id}' does not exist. "
                f"{valid_hint}"
            )

        if not target.walkable or location_id not in valid_ids:
            return (
                f"You can't go to '{target.name}' — it is not reachable. "
                f"{valid_hint}"
            )

        old_location = agent.location_id

        # Find an open tile within the target node — avoid non-walkable children.
        blocked: set[tuple[int, int]] = set()
        for child in target.children:
            if not child.walkable:
                for cx in range(child.x, child.x + child.w):
                    for cy in range(child.y, child.y + child.h):
                        blocked.add((cx, cy))

        open_tiles = [
            (tx, ty)
            for tx in range(target.x, target.x + target.w)
            for ty in range(target.y, target.y + target.h)
            if (tx, ty) not in blocked
        ]

        if open_tiles:
            import random
            # Prefer tiles near the center of the zone (more likely walkable
            # on the visual tilemap where edges tend to have walls/structures).
            cx = target.x + target.w / 2
            cy = target.y + target.h / 2
            open_tiles.sort(key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
            # Pick randomly from the inner ~60% of tiles (closest to center)
            inner_count = max(1, len(open_tiles) * 3 // 5)
            dest_x, dest_y = random.choice(open_tiles[:inner_count])
        else:
            # Fallback: center of the target zone
            dest_x, dest_y = target.x + target.w // 2, target.y + target.h // 2

        agent.location_id = location_id
        agent.x = dest_x
        agent.y = dest_y
        agent.current_action = f"Walking to {target.name}"

        logger.info("%s moved from %s to %s", self.agent_id, old_location, location_id)
        result = f"You moved to {target.name}. {target.description}"
        self._record(f"Moved from {old_location} to {target.name}. {target.description}", "movement")
        self._log_location_event(location_id, f"{agent.name} arrived at {target.name}")
        return result

    def talk_to_agent(self, target_agent_id: str, message: str) -> str:
        """Say something to another agent. Both agents must be in the same location.

        Args:
            target_agent_id: The id of the agent to talk to (e.g. 'agent_maya').
            message: What you want to say.

        Returns:
            A message describing the interaction result.
        """
        me = self._find_agent(self.agent_id)
        if not me:
            return f"Error: agent '{self.agent_id}' not found."

        target = self._find_agent(target_agent_id)
        if not target:
            return f"There is no one called '{target_agent_id}' in this world."

        if me.location_id != target.location_id:
            return f"{target.name} is not here. They are somewhere else in town."

        me.current_action = f"Talking to {target.name}"
        logger.info("%s says to %s: %s", self.agent_id, target_agent_id, message)
        result = f"You said to {target.name}: \"{message}\". They heard you."
        self._record(f"Said to {target.name}: \"{message}\"", "conversation")

        # Create pending message for the target agent
        if target_agent_id not in self.world_state.pending_messages:
            self.world_state.pending_messages[target_agent_id] = []
        self.world_state.pending_messages[target_agent_id].append({
            "from_agent": self.agent_id,
            "from_name": me.name,
            "message": message,
            "timestamp": time.time(),
        })

        # Log location event
        self._log_location_event(
            me.location_id,
            f"{me.name} said to {target.name}: \"{message[:80]}\"",
        )

        # Compute sentiment and update social graph
        sentiment = self._quick_sentiment(message)
        if self.social_graph is not None:
            self.social_graph.update_interaction(
                self.agent_id, target_agent_id,
                context=f"{self.agent_id} said to {target.name}: \"{message[:100]}\"",
                sentiment=sentiment,
            )

        return result

    def interact_with_object(self, object_id: str, action: str) -> str:
        """Interact with an object in your current location.

        Args:
            object_id: The id of the object (e.g. 'kitchen_stove', 'fountain_01').
            action: What you want to do with the object (e.g. 'turn on', 'sit down', 'examine').

        Returns:
            A narrative description of the interaction result.
        """
        me = self._find_agent(self.agent_id)
        if not me:
            return f"Error: agent '{self.agent_id}' not found."

        obj = self._find_node(object_id)
        if not obj:
            return f"There is no object called '{object_id}' nearby."

        # Check the object is in the agent's current location subtree
        location_node = self._find_node(me.location_id)
        if not location_node:
            return "Error: your current location could not be found."

        def _contains(parent: EnvironmentNode, target_id: str) -> bool:
            if parent.id == target_id:
                return True
            return any(_contains(c, target_id) for c in parent.children)

        # Also check parent — the agent might be in a room inside a building
        parent = self._get_parent_node(me.location_id)
        in_location = _contains(location_node, object_id)
        in_parent = parent is not None and _contains(parent, object_id)

        if not in_location and not in_parent:
            return f"The {obj.name} is not in your current location."

        me.current_action = f"{action.capitalize()} the {obj.name}"
        logger.info("%s interacts with %s: %s", self.agent_id, object_id, action)
        result = f"You {action} the {obj.name}. {obj.description}"
        self._record(f"Interacted with {obj.name}: {action}. {obj.description}", "interaction")
        self._log_location_event(me.location_id, f"{me.name} {action} the {obj.name}")
        return result

    def observe_surroundings(self) -> str:
        """Look around and observe your current surroundings.

        Returns:
            A description of the current location, nearby objects, agents, and adjacent areas.
        """
        me = self._find_agent(self.agent_id)
        if not me:
            return f"Error: agent '{self.agent_id}' not found."

        location = self._find_node(me.location_id)
        if not location:
            return "You can't see anything — your location is unknown."

        lines: list[str] = []
        lines.append(f"You are at: {location.name}")
        lines.append(f"Description: {location.description}")

        # Objects in this location
        objects = [c for c in location.children if c.node_type == NodeType.OBJECT]
        if objects:
            lines.append("\nObjects here:")
            for obj in objects:
                lines.append(f"  - {obj.name} ({obj.id}): {obj.description}")

        # Other agents at this location
        others = [a for a in self._get_agents_at_location(me.location_id) if a.id != self.agent_id]
        if others:
            lines.append("\nPeople here:")
            for other in others:
                lines.append(f"  - {other.name} ({other.id}): {other.current_action}")

        # Sibling locations (adjacent areas)
        parent = self._get_parent_node(me.location_id)
        if parent:
            siblings = [c for c in parent.children if c.id != me.location_id and c.walkable]
            if siblings:
                lines.append("\nNearby locations you can go to:")
                for sib in siblings:
                    lines.append(f"  - {sib.name} ({sib.id})")

        # Recent events at this location by other agents
        loc_events = self.world_state.location_events.get(me.location_id, [])
        other_events = [e for e in loc_events if e.get("agent_id") != self.agent_id]
        if other_events:
            lines.append("\nRecent activity here:")
            for evt in other_events[-4:]:
                lines.append(f"  - {evt['event']}")

        observation = "\n".join(lines)
        self._record(observation, "observation")
        return observation

    def update_action(self, action_description: str) -> str:
        """Update your visible action status that other agents and players can see.

        Args:
            action_description: A short description of what you are doing now (e.g. 'Reading a book', 'Cooking dinner').

        Returns:
            Confirmation of the status update.
        """
        me = self._find_agent(self.agent_id)
        if not me:
            return f"Error: agent '{self.agent_id}' not found."

        me.current_action = action_description
        logger.info("%s updated action: %s", self.agent_id, action_description)
        result = f"Your status is now: {action_description}"
        self._record(f"Updated action: {action_description}", "action_update")
        return result
