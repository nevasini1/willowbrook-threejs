"""
MemoryStore — LlamaIndex-backed semantic memory for agents.

Each agent gets its own VectorStoreIndex so memories are isolated.
Embeddings are generated via Google's text-embedding-004 model.
Indexes persist to disk as JSON (SimpleVectorStore) and reload on restart.

Retrieval uses a composite score: alpha * relevance + beta * recency + gamma * importance.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Optional

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import TextNode
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding

from core.config import settings

logger = logging.getLogger(__name__)

# Shared embedding model instance (stateless, safe to share)
_embed_model: Optional[GoogleGenAIEmbedding] = None


def _get_embed_model() -> GoogleGenAIEmbedding:
    global _embed_model
    if _embed_model is None:
        _embed_model = GoogleGenAIEmbedding(
            model_name="models/gemini-embedding-001",
            api_key=settings.gemini_api_key,
        )
    return _embed_model


class AgentMemoryIndex:
    """Wraps a single agent's VectorStoreIndex with importance scoring."""

    def __init__(self, agent_id: str, persist_dir: Path):
        self.agent_id = agent_id
        self.persist_dir = persist_dir
        self._insert_count = 0
        self.last_importance: int = 5

        embed_model = _get_embed_model()

        if (persist_dir / "docstore.json").exists():
            logger.info("Loading existing memory index for %s", agent_id)
            storage_context = StorageContext.from_defaults(persist_dir=str(persist_dir))
            self.index = load_index_from_storage(
                storage_context, embed_model=embed_model
            )
        else:
            logger.info("Creating new memory index for %s", agent_id)
            persist_dir.mkdir(parents=True, exist_ok=True)
            self.index = VectorStoreIndex([], embed_model=embed_model)

    def _rate_importance_sync(self, text: str) -> int:
        """Ask Gemini to rate memory importance 1-10.

        1 = mundane (eating breakfast, routine greetings)
        10 = extraordinary (fire, death, major life event)
        """
        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model=settings.memory_importance_model,
                contents=(
                    "On a scale of 1 to 10, where 1 is mundane (e.g., eating breakfast) "
                    "and 10 is extraordinary (e.g., a fire in town, a death, a major life change), "
                    "rate the importance of the following memory. "
                    "Respond with ONLY a single integer.\n\n"
                    f"Memory: {text}"
                ),
                config={
                    "max_output_tokens": 4,
                    "temperature": 0.0,
                },
            )
            score = int(response.text.strip())
            return max(1, min(10, score))
        except Exception as e:
            logger.warning("Importance rating failed: %s — defaulting to 5", e)
            return 5

    def add_memory(self, text: str, metadata: Optional[dict] = None) -> int:
        """Insert a memory into this agent's index. Returns importance score."""
        importance = self._rate_importance_sync(text)
        self.last_importance = importance

        node_metadata = {
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "importance": importance,
        }
        if metadata:
            node_metadata.update(metadata)

        node = TextNode(text=text, metadata=node_metadata)
        self.index.insert_nodes([node])
        self._insert_count += 1
        return importance

    def retrieve(self, query: str, top_k: int = 5) -> list[tuple[str, float, dict]]:
        """Return top-K memories re-ranked by composite score.

        Fetches top_k*3 candidates from vector search, then re-ranks using:
            composite = alpha * relevance + beta * recency + gamma * importance

        Returns list of (text, composite_score, metadata) tuples.
        """
        alpha = settings.memory_relevance_weight
        beta = settings.memory_recency_weight
        gamma = settings.memory_importance_weight
        half_life_seconds = settings.memory_recency_half_life_hours * 3600.0

        candidates_k = top_k * 3
        retriever = self.index.as_retriever(similarity_top_k=candidates_k)
        results = retriever.retrieve(query)

        now = time.time()
        scored: list[tuple[str, float, dict]] = []

        for node in results:
            text = node.get_text()
            relevance = node.get_score() or 0.0
            meta = node.node.metadata if node.node else {}

            timestamp = meta.get("timestamp", now)
            age_seconds = max(0.0, now - timestamp)
            recency = math.exp(-0.693 * age_seconds / half_life_seconds) if half_life_seconds > 0 else 0.0

            importance_raw = meta.get("importance", 5)
            importance = importance_raw / 10.0

            composite = alpha * relevance + beta * recency + gamma * importance
            scored.append((text, composite, meta))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def retrieve_recent(self, count: int = 100) -> list[tuple[str, dict]]:
        """Retrieve the most recent memories by timestamp.

        Used by the reflection engine. Returns (text, metadata) tuples.
        """
        retriever = self.index.as_retriever(similarity_top_k=count)
        # Use a generic query to get candidates, then sort by timestamp
        results = retriever.retrieve("recent events and observations")

        items: list[tuple[str, dict, float]] = []
        for node in results:
            meta = node.node.metadata if node.node else {}
            ts = meta.get("timestamp", 0.0)
            items.append((node.get_text(), meta, ts))

        items.sort(key=lambda x: x[2], reverse=True)
        return [(text, meta) for text, meta, _ in items[:count]]

    def get_memory_count(self) -> int:
        """Count nodes in the docstore."""
        try:
            docstore = self.index.storage_context.docstore
            return len(docstore.docs)
        except Exception:
            return 0

    def decay_and_prune(self) -> int:
        """Apply time-based importance decay and prune low-importance memories.

        Skips reflections and consolidated memories. Returns count of pruned memories.
        """
        docstore = self.index.storage_context.docstore
        now = time.time()
        decay_rate = settings.memory_decay_rate_per_day
        prune_threshold = settings.memory_prune_importance_threshold
        to_delete: list[str] = []

        for doc_id, node in list(docstore.docs.items()):
            meta = node.metadata if hasattr(node, "metadata") else {}
            category = meta.get("category", "")
            if category in ("reflection", "consolidated"):
                continue

            importance = meta.get("importance", 5)
            timestamp = meta.get("timestamp", now)
            age_days = (now - timestamp) / 86400.0

            decayed = importance - (decay_rate * age_days * importance)
            decayed = max(0.0, decayed)

            if decayed < prune_threshold:
                to_delete.append(doc_id)
            else:
                meta["importance"] = decayed
                node.metadata = meta

        for doc_id in to_delete:
            try:
                docstore.delete_document(doc_id)
            except Exception:
                pass

        logger.info("Decay/prune for %s: pruned %d memories", self.agent_id, len(to_delete))
        return len(to_delete)

    def consolidate(self) -> int:
        """Consolidate long-term memories by clustering similar ones.

        Triggered when memory count exceeds the cap. Returns count of memories reduced.
        """
        docstore = self.index.storage_context.docstore
        all_docs = list(docstore.docs.items())
        total = len(all_docs)

        if total <= settings.memory_max_per_agent:
            return 0

        # Sort by timestamp, separate short-term buffer
        doc_items: list[tuple[str, any]] = []
        for doc_id, node in all_docs:
            meta = node.metadata if hasattr(node, "metadata") else {}
            ts = meta.get("timestamp", 0.0)
            doc_items.append((doc_id, node, ts))

        doc_items.sort(key=lambda x: x[2], reverse=True)

        buffer_size = settings.memory_short_term_buffer
        short_term = doc_items[:buffer_size]
        long_term = doc_items[buffer_size:]

        if len(long_term) < settings.memory_consolidation_cluster_size:
            return 0

        # Embed long-term memories for clustering
        embed_model = _get_embed_model()
        texts = []
        lt_ids = []
        for doc_id, node, _ts in long_term:
            text = node.get_content() if hasattr(node, "get_content") else str(node)
            texts.append(text)
            lt_ids.append(doc_id)

        try:
            embeddings = embed_model.get_text_embedding_batch(texts)
        except Exception as e:
            logger.warning("Embedding batch failed during consolidation: %s", e)
            return 0

        # Greedy clustering by cosine similarity
        import numpy as np

        emb_array = np.array(embeddings)
        norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normed = emb_array / norms

        assigned = [False] * len(texts)
        clusters: list[list[int]] = []
        threshold = settings.memory_consolidation_similarity_threshold

        for i in range(len(texts)):
            if assigned[i]:
                continue
            cluster = [i]
            assigned[i] = True
            for j in range(i + 1, len(texts)):
                if assigned[j]:
                    continue
                sim = float(np.dot(normed[i], normed[j]))
                if sim >= threshold:
                    cluster.append(j)
                    assigned[j] = True
            if len(cluster) >= settings.memory_consolidation_cluster_size:
                clusters.append(cluster)

        # Summarize each qualifying cluster
        reduced = 0
        for cluster_indices in clusters:
            cluster_texts = [texts[i] for i in cluster_indices]
            summary = self._summarize_cluster(cluster_texts)
            if not summary:
                continue

            # Delete originals
            for idx in cluster_indices:
                try:
                    docstore.delete_document(lt_ids[idx])
                except Exception:
                    pass

            # Insert consolidated memory
            consolidated_node = TextNode(
                text=summary,
                metadata={
                    "agent_id": self.agent_id,
                    "timestamp": time.time(),
                    "importance": 6,  # boosted +1 from default 5
                    "category": "consolidated",
                },
            )
            self.index.insert_nodes([consolidated_node])
            reduced += len(cluster_indices) - 1  # net reduction

        logger.info(
            "Consolidation for %s: %d clusters, reduced by %d memories",
            self.agent_id, len(clusters), reduced,
        )
        return reduced

    def _summarize_cluster(self, texts: list[str]) -> str:
        """Summarize a cluster of similar memories into one paragraph via Gemini."""
        try:
            from google import genai

            combined = "\n".join(f"- {t}" for t in texts)
            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model=settings.memory_importance_model,
                contents=(
                    "Consolidate these related memories into a single concise paragraph "
                    "that preserves all key information, events, and emotional context. "
                    "Write in first person as if recalling the combined experience.\n\n"
                    f"Memories:\n{combined}"
                ),
                config={
                    "max_output_tokens": 200,
                    "temperature": 0.3,
                },
            )
            return response.text.strip()
        except Exception as e:
            logger.warning("Cluster summarization failed: %s", e)
            return ""

    def persist(self) -> None:
        """Save the index to disk."""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.index.storage_context.persist(persist_dir=str(self.persist_dir))


class MemoryStore:
    """Manages all agents' memory indexes."""

    AUTO_PERSIST_INTERVAL = 50  # persist every N inserts per agent

    def __init__(self, persist_base: Optional[str] = None):
        self._persist_base = Path(persist_base or settings.memory_persist_dir)
        self._indexes: dict[str, AgentMemoryIndex] = {}

    def _get_index(self, agent_id: str) -> Optional[AgentMemoryIndex]:
        return self._indexes.get(agent_id)

    def initialize(self, agent_ids: list[str]) -> None:
        """Load or create memory indexes for the given agent IDs."""
        for agent_id in agent_ids:
            persist_dir = self._persist_base / agent_id
            self._indexes[agent_id] = AgentMemoryIndex(agent_id, persist_dir)
        logger.info("Memory store initialized for %d agents", len(agent_ids))

    def add_memory(
        self, agent_id: str, text: str, metadata: Optional[dict] = None
    ) -> int:
        """Add a memory for an agent. Auto-persists periodically. Returns importance."""
        idx = self._indexes.get(agent_id)
        if idx is None:
            logger.warning("No memory index for agent %s — skipping", agent_id)
            return 5

        importance = idx.add_memory(text, metadata)

        if idx._insert_count % self.AUTO_PERSIST_INTERVAL == 0:
            idx.persist()
            logger.debug("Auto-persisted memory index for %s", agent_id)

            # Check if consolidation is needed
            if idx.get_memory_count() > settings.memory_max_per_agent:
                logger.info("Memory cap exceeded for %s — running maintenance", agent_id)
                idx.decay_and_prune()
                idx.consolidate()
                idx.persist()

        return importance

    def retrieve(
        self, agent_id: str, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Retrieve top-K memories for an agent. Backward-compatible (text, score)."""
        idx = self._indexes.get(agent_id)
        if idx is None:
            return []
        ranked = idx.retrieve(query, top_k)
        return [(text, score) for text, score, _meta in ranked]

    def retrieve_recent(
        self, agent_id: str, count: int = 100
    ) -> list[tuple[str, dict]]:
        """Retrieve recent memories for reflection."""
        idx = self._indexes.get(agent_id)
        if idx is None:
            return []
        return idx.retrieve_recent(count)

    def run_maintenance(self, agent_id: str) -> dict:
        """Run decay + consolidation manually for an agent. Returns stats."""
        idx = self._indexes.get(agent_id)
        if idx is None:
            return {"error": f"No memory index for agent {agent_id}"}

        count_before = idx.get_memory_count()
        pruned = idx.decay_and_prune()
        consolidated = idx.consolidate()
        count_after = idx.get_memory_count()
        idx.persist()

        return {
            "agent_id": agent_id,
            "memories_before": count_before,
            "memories_after": count_after,
            "pruned": pruned,
            "consolidated_reduction": consolidated,
        }

    def persist_all(self) -> None:
        """Persist all agent indexes to disk."""
        for agent_id, idx in self._indexes.items():
            idx.persist()
            logger.info("Persisted memory index for %s", agent_id)
