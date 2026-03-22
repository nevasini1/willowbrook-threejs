"""
SocialGraph — tracks relationships between agents.

Relationships are created/updated when agents interact (talk_to_agent),
and relationship context is injected into agent prompts.
Persists to JSON on disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    agent_a: str
    agent_b: str
    relation_type: str = "acquaintance"
    strength: float = 0.1
    notes: str = ""
    last_interaction: float = 0.0
    interaction_count: int = 0
    shared_memories: list[str] = field(default_factory=list)
    sentiment_history: list[float] = field(default_factory=list)
    version: int = 0


class SocialGraph:
    """Manages the social graph of agent relationships."""

    MAX_SHARED_MEMORIES = 10

    def __init__(self, persist_dir: Optional[str] = None):
        self._persist_dir = Path(persist_dir or settings.social_graph_persist_dir)
        self._relationships: dict[tuple[str, str], Relationship] = {}
        self._lock = asyncio.Lock()
        self._pair_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._load()

    @staticmethod
    def _canonical_key(a: str, b: str) -> tuple[str, str]:
        """Return a sorted canonical key for a pair of agents."""
        return (min(a, b), max(a, b))

    def _get_pair_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        """Get or create a per-relationship-pair asyncio lock."""
        if key not in self._pair_locks:
            self._pair_locks[key] = asyncio.Lock()
        return self._pair_locks[key]

    def add_relationship(
        self,
        a: str,
        b: str,
        relation_type: str = "acquaintance",
        strength: float = 0.1,
        notes: str = "",
    ) -> Relationship:
        """Create or update a relationship between two agents."""
        key = self._canonical_key(a, b)
        neg_min = settings.relationship_negative_min
        if key in self._relationships:
            rel = self._relationships[key]
            rel.relation_type = relation_type
            rel.strength = min(1.0, max(neg_min, strength))
            if notes:
                rel.notes = notes
            return rel

        rel = Relationship(
            agent_a=key[0],
            agent_b=key[1],
            relation_type=relation_type,
            strength=min(1.0, max(neg_min, strength)),
            notes=notes,
            last_interaction=time.time(),
        )
        self._relationships[key] = rel
        return rel

    def _apply_interaction(
        self, rel: Relationship, context: str, sentiment: float, now: float
    ) -> None:
        """Apply an interaction update to a relationship (must be called under lock or single-threaded)."""
        neg_min = settings.relationship_negative_min

        # Reject stale updates: if this interaction's timestamp is older than
        # the last recorded interaction, skip the strength update but still
        # record context/sentiment for completeness.
        is_stale = now < rel.last_interaction

        rel.interaction_count += 1
        rel.version += 1

        # Track sentiment history (last 10)
        rel.sentiment_history.append(sentiment)
        rel.sentiment_history = rel.sentiment_history[-10:]

        if not is_stale:
            rel.last_interaction = now

            # Sentiment-aware strength update
            if sentiment >= 0:
                # Positive: builds friendship with diminishing returns
                delta = 0.05 * (1.0 - rel.strength) * (1.0 + sentiment)
            else:
                # Negative: creates rivalry, scales with existing strength magnitude
                delta = 0.05 * sentiment * (1.0 + abs(rel.strength))

            rel.strength = min(1.0, max(neg_min, rel.strength + delta))

            # Map strength to relation types
            self._classify_relationship(rel)
        else:
            logger.debug(
                "Stale interaction %s <-> %s (event_time=%.3f < last=%.3f), "
                "recording context only",
                rel.agent_a, rel.agent_b, now, rel.last_interaction,
            )

        if context:
            rel.shared_memories.append(context[:200])
            rel.shared_memories = rel.shared_memories[-self.MAX_SHARED_MEMORIES:]

    @staticmethod
    def _classify_relationship(rel: Relationship) -> None:
        """Set relation_type based on current strength."""
        if rel.strength >= 0.7:
            rel.relation_type = "close_friend"
        elif rel.strength >= 0.4:
            rel.relation_type = "friend"
        elif rel.strength >= 0.0:
            rel.relation_type = "acquaintance"
        elif rel.strength >= -0.5:
            rel.relation_type = "rival"
        else:
            rel.relation_type = "enemy"

    def update_interaction(self, a: str, b: str, context: str = "", sentiment: float = 0.0) -> None:
        """Record an interaction between two agents (sync, for use from tool calls)."""
        key = self._canonical_key(a, b)
        if key not in self._relationships:
            self.add_relationship(a, b)

        rel = self._relationships[key]
        now = time.time()
        self._apply_interaction(rel, context, sentiment, now)

        logger.debug(
            "Updated interaction %s <-> %s (count=%d, strength=%.2f, sentiment=%.2f, v=%d)",
            a, b, rel.interaction_count, rel.strength, sentiment, rel.version,
        )

    async def update_interaction_async(
        self, a: str, b: str, context: str = "", sentiment: float = 0.0
    ) -> None:
        """Record an interaction with per-pair locking for concurrent safety."""
        key = self._canonical_key(a, b)
        pair_lock = self._get_pair_lock(key)

        async with pair_lock:
            if key not in self._relationships:
                self.add_relationship(a, b)

            rel = self._relationships[key]
            now = time.time()
            self._apply_interaction(rel, context, sentiment, now)

        logger.debug(
            "Updated interaction (async) %s <-> %s (count=%d, strength=%.2f, sentiment=%.2f, v=%d)",
            a, b, rel.interaction_count, rel.strength, sentiment, rel.version,
        )

    def get_relationships(self, agent_id: str) -> list[Relationship]:
        """Get all relationships for an agent."""
        return [
            rel for key, rel in self._relationships.items()
            if agent_id in key
        ]

    def get_relationship(self, a: str, b: str) -> Optional[Relationship]:
        """Get the relationship between two specific agents."""
        key = self._canonical_key(a, b)
        return self._relationships.get(key)

    def decay_relationships(self, elapsed_days: float) -> None:
        """Decay all relationships toward 0.0 (neutral).

        Only affects relationships where last interaction was > 1 day ago.
        Positive strengths decrease, negative strengths increase (both toward zero).
        """
        decay_rate = settings.relationship_decay_rate_per_day
        now = time.time()
        one_day = 86400.0

        for rel in self._relationships.values():
            time_since = now - rel.last_interaction
            if time_since < one_day:
                continue

            decay_amount = decay_rate * elapsed_days
            if rel.strength > 0:
                rel.strength = max(0.0, rel.strength - decay_amount)
            elif rel.strength < 0:
                rel.strength = min(0.0, rel.strength + decay_amount)

            self._classify_relationship(rel)

    def format_for_prompt(self, agent_id: str) -> str:
        """Format relationships as prompt context for an agent."""
        rels = self.get_relationships(agent_id)
        if not rels:
            return ""

        lines = ["\n[RELATIONSHIPS] People you know:"]
        for rel in rels:
            other = rel.agent_b if rel.agent_a == agent_id else rel.agent_a
            if rel.strength >= 0.7:
                strength_desc = "are close with"
            elif rel.strength >= 0.4:
                strength_desc = "know well"
            elif rel.strength >= 0.2:
                strength_desc = "somewhat know"
            elif rel.strength >= 0.0:
                strength_desc = "barely know"
            elif rel.strength >= -0.5:
                strength_desc = "have tension with"
            else:
                strength_desc = "strongly dislike"

            line = f"  - {other} ({rel.relation_type}): You {strength_desc} them."
            if rel.notes:
                line += f" {rel.notes}"
            if rel.shared_memories:
                line += f" Last interaction: {rel.shared_memories[-1]}"
            lines.append(line)

        return "\n".join(lines)

    def persist(self) -> None:
        """Save the social graph to disk."""
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._persist_dir / "relationships.json"

        data = []
        for rel in self._relationships.values():
            data.append(asdict(rel))

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Social graph persisted (%d relationships)", len(data))

    def _load(self) -> None:
        """Load the social graph from disk."""
        filepath = self._persist_dir / "relationships.json"
        if not filepath.exists():
            return

        try:
            with open(filepath) as f:
                data = json.load(f)

            for item in data:
                rel = Relationship(**item)
                key = self._canonical_key(rel.agent_a, rel.agent_b)
                self._relationships[key] = rel

            logger.info("Loaded social graph (%d relationships)", len(self._relationships))
        except Exception as e:
            logger.warning("Failed to load social graph: %s", e)


# ---------------------------------------------------------------------------
# Factory — auto-select Neo4j or fallback to JSON
# ---------------------------------------------------------------------------


def create_social_graph() -> SocialGraph:
    """Create the best available social graph backend.

    Attempts to connect to Neo4j. If unavailable, falls back to the
    JSON-backed SocialGraph with a warning.
    """
    try:
        from services.neo4j_social_graph import Neo4jSocialGraph

        graph = Neo4jSocialGraph()
        logger.info("Using Neo4j-backed social graph.")
        return graph  # type: ignore[return-value]
    except ImportError:
        logger.warning(
            "neo4j package not installed — falling back to JSON social graph."
        )
    except Exception as e:
        logger.warning(
            "Could not connect to Neo4j (%s) — falling back to JSON social graph.", e
        )

    return SocialGraph()

