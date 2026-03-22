"""
ReflectionEngine — generates high-level reflections when importance accumulates.

When the sum of importance scores for an agent's recent memories exceeds a
threshold (default 150), the engine:
1. Retrieves the 100 most recent memories
2. Asks Gemini for 3 salient high-level questions
3. Uses those questions to retrieve additional relevant memories
4. Generates 3 insight reflections
5. Stores reflections as memories (category="reflection", importance=8)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from core.config import settings

if TYPE_CHECKING:
    from services.memory_store import MemoryStore

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Generates high-level reflections from accumulated memories."""

    def __init__(self, memory_store: Optional[MemoryStore] = None):
        self.memory_store = memory_store
        self._importance_accumulators: dict[str, float] = {}

    def accumulate_importance(self, agent_id: str, importance: int) -> None:
        """Add importance score to the running total for an agent."""
        current = self._importance_accumulators.get(agent_id, 0.0)
        self._importance_accumulators[agent_id] = current + importance

    def check_threshold(self, agent_id: str) -> bool:
        """Check if the agent's accumulated importance exceeds the reflection threshold."""
        return self._importance_accumulators.get(agent_id, 0.0) >= settings.reflection_importance_threshold

    def reset_accumulator(self, agent_id: str) -> None:
        """Reset the importance accumulator after reflection."""
        self._importance_accumulators[agent_id] = 0.0

    def generate_reflections(self, agent_id: str, agent_name: str) -> list[str]:
        """Generate high-level reflections for an agent.

        This is a synchronous call (suitable for fire-and-forget via asyncio.ensure_future).
        """
        if self.memory_store is None:
            return []

        # Reset accumulator first to prevent re-triggering
        self.reset_accumulator(agent_id)

        # Step 1: Retrieve recent memories
        recent = self.memory_store.retrieve_recent(
            agent_id, count=settings.reflection_recent_memory_count
        )
        if not recent:
            return []

        recent_texts = [text for text, _meta in recent]
        statements_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(recent_texts[:50]))

        # Step 2: Ask for salient questions
        questions = self._generate_questions(agent_name, statements_block)
        if not questions:
            return []

        # Step 3: Retrieve memories relevant to each question
        extra_context: list[str] = []
        for q in questions:
            results = self.memory_store.retrieve(agent_id, q, top_k=5)
            for text, _score in results:
                if text not in extra_context and text not in recent_texts:
                    extra_context.append(text)

        # Step 4: Generate reflections
        all_context = recent_texts[:30] + extra_context[:20]
        context_block = "\n".join(f"  - {t}" for t in all_context)
        reflections = self._generate_insights(agent_name, questions, context_block)

        # Step 5: Store reflections as memories
        for reflection in reflections:
            self.memory_store.add_memory(
                agent_id,
                reflection,
                metadata={
                    "category": "reflection",
                    "importance": settings.reflection_default_importance,
                },
            )

        logger.info(
            "Stored %d reflections for %s (accumulator was %.1f)",
            len(reflections),
            agent_id,
            settings.reflection_importance_threshold,
        )
        return reflections

    def _generate_questions(self, agent_name: str, statements: str) -> list[str]:
        """Ask Gemini for 3 salient high-level questions about recent memories."""
        prompt = (
            f"Given the following recent memories of {agent_name}:\n"
            f"{statements}\n\n"
            "What are 3 most salient high-level questions we can answer about "
            f"{agent_name}'s life and experiences based on these statements?\n"
            "Return ONLY a JSON array of 3 question strings."
        )
        return self._call_gemini_json_list(prompt, max_items=3)

    def _generate_insights(
        self, agent_name: str, questions: list[str], context: str
    ) -> list[str]:
        """Generate 3 insight reflections from questions and context."""
        questions_block = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))
        prompt = (
            f"You are {agent_name} reflecting on your experiences.\n"
            f"Questions to consider:\n{questions_block}\n\n"
            f"Relevant memories:\n{context}\n\n"
            "Based on these memories, generate exactly 3 high-level insight reflections. "
            "Each reflection should be a profound observation about your life, "
            "relationships, or situation — not a simple summary of events. "
            "Write in first person as the character.\n"
            "Return ONLY a JSON array of 3 reflection strings."
        )
        return self._call_gemini_json_list(prompt, max_items=3)

    def _call_gemini_json_list(self, prompt: str, max_items: int = 3) -> list[str]:
        """Call Gemini and parse a JSON list response."""
        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "max_output_tokens": 512,
                    "temperature": 0.7,
                },
            )
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            result = json.loads(text)
            if isinstance(result, list):
                return [str(item) for item in result[:max_items]]
        except Exception as e:
            logger.warning("Gemini JSON list call failed: %s", e)

        return []
