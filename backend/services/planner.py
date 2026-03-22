"""
Planner — generates daily plans for agents using Gemini.

Agents receive a multi-step plan at the start of each day (or when their
current plan is exhausted). Plans are informed by recent memories and persona.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from core.config import settings

if TYPE_CHECKING:
    from services.memory_store import MemoryStore

logger = logging.getLogger(__name__)


class Planner:
    """Generates and decomposes daily plans for agents."""

    def __init__(self, memory_store: Optional[MemoryStore] = None):
        self.memory_store = memory_store

    def generate_plan(
        self,
        agent_id: str,
        name: str,
        persona: str,
        previous_summary: str = "",
        location: str = "",
        reflection_context: str = "",
        mood: str = "neutral",
        relationship_context: str = "",
    ) -> list[str]:
        """Generate a daily plan for an agent.

        Returns a list of 5-8 high-level steps.
        """
        # Gather recent memory context
        memory_context = ""
        if self.memory_store is not None:
            memories = self.memory_store.retrieve(
                agent_id, f"{name}'s recent activities and plans", top_k=10
            )
            if memories:
                memory_lines = [f"  - {text}" for text, _score in memories]
                memory_context = "\nRecent memories:\n" + "\n".join(memory_lines)

        mood_context = f"\nCurrent mood: {mood}. Let this mood influence the plan.\n" if mood != "neutral" else ""
        reflection_block = f"\nKey reflections:\n{reflection_context}\n" if reflection_context else ""
        relationship_block = f"\n{relationship_context}\n" if relationship_context else ""

        prompt = (
            f"You are generating a daily plan for {name}.\n"
            f"Persona: {persona}\n"
            f"Current location: {location}\n"
            f"{f'Previous day summary: {previous_summary}' if previous_summary else ''}"
            f"{memory_context}"
            f"{mood_context}"
            f"{reflection_block}"
            f"{relationship_block}\n"
            f"Generate a realistic daily plan with {settings.plan_steps_min} to {settings.plan_steps_max} steps. "
            "Each step should be a concrete action the character would take during their day. "
            "Consider the character's relationships — they might seek out friends, avoid rivals, or plan activities with people they know. "
            "Return ONLY a JSON array of strings, no other text.\n"
            'Example: ["Wake up and make breakfast", "Walk to the town square", "Chat with neighbors"]'
        )

        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "max_output_tokens": 512,
                    "temperature": 0.8,
                },
            )
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            steps = json.loads(text)
            if isinstance(steps, list) and all(isinstance(s, str) for s in steps):
                return steps[: settings.plan_steps_max]
        except Exception as e:
            logger.warning("Plan generation failed for %s: %s", agent_id, e)

        # Fallback plan
        return [
            "Observe surroundings and take stock of the day",
            "Walk to a nearby area and explore",
            "Talk to someone nearby",
            "Interact with an interesting object",
            "Reflect on the day's events",
        ]

    def decompose_step(self, description: str, agent_name: str) -> list[str]:
        """Decompose a plan step into 15-minute sub-steps."""
        prompt = (
            f"Break down this plan step for {agent_name} into smaller sub-steps "
            f"of about {settings.plan_decompose_granularity_minutes} minutes each.\n"
            f"Step: {description}\n"
            "Return ONLY a JSON array of strings."
        )

        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "max_output_tokens": 256,
                    "temperature": 0.7,
                },
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            sub_steps = json.loads(text)
            if isinstance(sub_steps, list):
                return sub_steps
        except Exception as e:
            logger.warning("Step decomposition failed: %s", e)

        return [description]
