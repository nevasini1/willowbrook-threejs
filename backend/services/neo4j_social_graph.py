"""
Neo4jSocialGraph — Neo4j-backed social graph for agent relationships.

Replaces the flat-dict JSON approach with a true graph database, enabling
multi-hop relationship queries, gossip propagation paths, and rich social
network analysis as specified in AGENTS.md §1.5.

Falls back gracefully if Neo4j is unavailable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    """Mirror of the Relationship dataclass from social_graph.py."""
    agent_a: str
    agent_b: str
    relation_type: str = "acquaintance"
    strength: float = 0.1
    notes: str = ""
    last_interaction: float = 0.0
    interaction_count: int = 0
    shared_memories: list[str] = field(default_factory=list)


class Neo4jSocialGraph:
    """Manages the social graph of agent relationships using Neo4j.

    Provides the same public API as the JSON-backed SocialGraph so it
    can be used as a drop-in replacement.
    """

    MAX_SHARED_MEMORIES = 10

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._database = database or settings.neo4j_database

        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )

        # Verify connectivity and set up schema
        self._driver.verify_connectivity()
        self._setup_schema()
        logger.info("Neo4j social graph connected at %s", self._uri)

    def _setup_schema(self) -> None:
        """Create constraints and indexes for the Agent nodes."""
        with self._driver.session(database=self._database) as session:
            # Unique constraint on Agent.id
            session.run(
                "CREATE CONSTRAINT agent_id_unique IF NOT EXISTS "
                "FOR (a:Agent) REQUIRE a.id IS UNIQUE"
            )

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def add_relationship(
        self,
        a: str,
        b: str,
        relation_type: str = "acquaintance",
        strength: float = 0.1,
        notes: str = "",
    ) -> Relationship:
        """Create or update a relationship between two agents."""
        strength = min(1.0, max(0.0, strength))
        canonical_a, canonical_b = min(a, b), max(a, b)

        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MERGE (a:Agent {id: $a})
                MERGE (b:Agent {id: $b})
                MERGE (a)-[r:RELATES_TO]-(b)
                SET r.relation_type = $relation_type,
                    r.strength = $strength,
                    r.notes = CASE WHEN $notes <> '' THEN $notes ELSE coalesce(r.notes, '') END,
                    r.last_interaction = coalesce(r.last_interaction, $now),
                    r.interaction_count = coalesce(r.interaction_count, 0),
                    r.shared_memories = coalesce(r.shared_memories, []),
                    r.canonical_a = $canonical_a,
                    r.canonical_b = $canonical_b
                RETURN r
                """,
                a=canonical_a,
                b=canonical_b,
                relation_type=relation_type,
                strength=strength,
                notes=notes,
                now=time.time(),
                canonical_a=canonical_a,
                canonical_b=canonical_b,
            )
            record = result.single()
            r = record["r"] if record else {}
            return Relationship(
                agent_a=canonical_a,
                agent_b=canonical_b,
                relation_type=r.get("relation_type", relation_type),
                strength=r.get("strength", strength),
                notes=r.get("notes", notes),
                last_interaction=r.get("last_interaction", 0.0),
                interaction_count=r.get("interaction_count", 0),
                shared_memories=list(r.get("shared_memories", [])),
            )

    def update_interaction(self, a: str, b: str, context: str = "") -> None:
        """Record an interaction between two agents."""
        canonical_a, canonical_b = min(a, b), max(a, b)

        with self._driver.session(database=self._database) as session:
            # Ensure both agents and relationship exist
            session.run(
                """
                MERGE (a:Agent {id: $a})
                MERGE (b:Agent {id: $b})
                MERGE (a)-[r:RELATES_TO]-(b)
                ON CREATE SET
                    r.relation_type = 'acquaintance',
                    r.strength = 0.1,
                    r.notes = '',
                    r.last_interaction = $now,
                    r.interaction_count = 0,
                    r.shared_memories = [],
                    r.canonical_a = $canonical_a,
                    r.canonical_b = $canonical_b
                SET r.interaction_count = r.interaction_count + 1,
                    r.last_interaction = $now,
                    r.strength = CASE
                        WHEN r.strength + 0.05 * (1.0 - r.strength) > 1.0 THEN 1.0
                        ELSE r.strength + 0.05 * (1.0 - r.strength)
                    END,
                    r.relation_type = CASE
                        WHEN r.strength >= 0.7 THEN 'close_friend'
                        WHEN r.strength >= 0.4 THEN 'friend'
                        WHEN r.strength >= 0.2 THEN 'acquaintance'
                        ELSE r.relation_type
                    END
                """,
                a=canonical_a,
                b=canonical_b,
                now=time.time(),
                canonical_a=canonical_a,
                canonical_b=canonical_b,
            )

            # Append shared memory (keep last N)
            if context:
                session.run(
                    """
                    MATCH (a:Agent {id: $a})-[r:RELATES_TO]-(b:Agent {id: $b})
                    SET r.shared_memories = r.shared_memories + [$context]
                    WITH r
                    WHERE size(r.shared_memories) > $max_memories
                    SET r.shared_memories = r.shared_memories[-$max_memories..]
                    """,
                    a=canonical_a,
                    b=canonical_b,
                    context=context[:200],
                    max_memories=self.MAX_SHARED_MEMORIES,
                )

        logger.debug("Updated interaction %s <-> %s", a, b)

    def get_relationships(self, agent_id: str) -> list[Relationship]:
        """Get all relationships for an agent."""
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH (a:Agent {id: $agent_id})-[r:RELATES_TO]-(b:Agent)
                RETURN r, b.id AS other_id
                """,
                agent_id=agent_id,
            )
            rels = []
            for record in result:
                r = record["r"]
                rels.append(Relationship(
                    agent_a=r.get("canonical_a", agent_id),
                    agent_b=r.get("canonical_b", record["other_id"]),
                    relation_type=r.get("relation_type", "acquaintance"),
                    strength=r.get("strength", 0.1),
                    notes=r.get("notes", ""),
                    last_interaction=r.get("last_interaction", 0.0),
                    interaction_count=r.get("interaction_count", 0),
                    shared_memories=list(r.get("shared_memories", [])),
                ))
            return rels

    def get_relationship(self, a: str, b: str) -> Optional[Relationship]:
        """Get the relationship between two specific agents."""
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH (a:Agent {id: $a})-[r:RELATES_TO]-(b:Agent {id: $b})
                RETURN r
                """,
                a=a,
                b=b,
            )
            record = result.single()
            if not record:
                return None
            r = record["r"]
            canonical_a, canonical_b = min(a, b), max(a, b)
            return Relationship(
                agent_a=canonical_a,
                agent_b=canonical_b,
                relation_type=r.get("relation_type", "acquaintance"),
                strength=r.get("strength", 0.1),
                notes=r.get("notes", ""),
                last_interaction=r.get("last_interaction", 0.0),
                interaction_count=r.get("interaction_count", 0),
                shared_memories=list(r.get("shared_memories", [])),
            )

    # ------------------------------------------------------------------
    # Neo4j-exclusive: multi-hop queries
    # ------------------------------------------------------------------

    def get_friends_of_friends(self, agent_id: str) -> list[str]:
        """Query 2-hop relationships (friends of friends).

        This is the kind of query that the flat-dict approach cannot do.
        """
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH (a:Agent {id: $agent_id})-[:RELATES_TO]-(:Agent)-[:RELATES_TO]-(fof:Agent)
                WHERE fof.id <> $agent_id
                  AND NOT (a)-[:RELATES_TO]-(fof)
                RETURN DISTINCT fof.id AS fof_id
                """,
                agent_id=agent_id,
            )
            return [record["fof_id"] for record in result]

    def get_gossip_path(self, from_agent: str, to_agent: str) -> list[str]:
        """Find the shortest social path between two agents.

        Models how information (gossip, rumors) might propagate.
        """
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH path = shortestPath(
                    (a:Agent {id: $from})-[:RELATES_TO*]-(b:Agent {id: $to})
                )
                RETURN [n IN nodes(path) | n.id] AS path
                """,
                **{"from": from_agent, "to": to_agent},
            )
            record = result.single()
            return record["path"] if record else []

    def get_social_clusters(self) -> list[list[str]]:
        """Identify tightly-connected groups of agents."""
        with self._driver.session(database=self._database) as session:
            result = session.run(
                """
                MATCH (a:Agent)-[r:RELATES_TO]-(b:Agent)
                WHERE r.strength >= 0.4
                RETURN a.id AS agent, collect(DISTINCT b.id) AS friends
                """
            )
            # Simple clustering: group agents who share friends
            clusters: list[set[str]] = []
            for record in result:
                agent = record["agent"]
                friends = set(record["friends"])
                friends.add(agent)
                # Merge with existing clusters that overlap
                merged = False
                for cluster in clusters:
                    if cluster & friends:
                        cluster |= friends
                        merged = True
                        break
                if not merged:
                    clusters.append(friends)
            return [sorted(c) for c in clusters]

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def format_for_prompt(self, agent_id: str) -> str:
        """Format relationships as prompt context for an agent."""
        rels = self.get_relationships(agent_id)
        if not rels:
            return ""

        lines = ["\n[RELATIONSHIPS] People you know:"]
        for rel in rels:
            other = rel.agent_b if rel.agent_a == agent_id else rel.agent_a
            strength_desc = "barely know" if rel.strength < 0.2 else \
                           "somewhat know" if rel.strength < 0.4 else \
                           "know well" if rel.strength < 0.7 else \
                           "are close with"
            line = f"  - {other} ({rel.relation_type}): You {strength_desc} them."
            if rel.notes:
                line += f" {rel.notes}"
            if rel.shared_memories:
                line += f" Last interaction: {rel.shared_memories[-1]}"
            lines.append(line)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def persist(self) -> None:
        """No-op — Neo4j is always persisted. Kept for API compatibility."""
        pass

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        self._driver.close()
        logger.info("Neo4j social graph connection closed.")
