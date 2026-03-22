"""
Agno agent storage backed by SQLite for persistent persona memory.

The SQLite database is stored at the path defined by AGNO_DB_URL
(default: sqlite:///data/agno_memory.db), which is mounted as a
Docker volume so agent memory survives container restarts.

Uses Agno v2 API: SqliteDb for session persistence, `db=` parameter,
and `id=` instead of `agent_id=`.
"""

import os
from typing import Optional

from agno.agent import Agent
from agno.models.google import Gemini
from agno.db.sqlite import SqliteDb
from agno.tools import Toolkit

from core.config import settings

AGNO_DB_URL = os.getenv("AGNO_DB_URL", "sqlite:///data/agno_memory.db")
# Extract the file path from the SQLite URL (strip "sqlite:///")
_db_path = AGNO_DB_URL.replace("sqlite:///", "")

db = SqliteDb(db_file=_db_path, session_table="agent_sessions")

# Default model: Gemini 2.0 Flash — pass API key explicitly from settings
default_model = Gemini(id="gemini-2.5-flash", api_key=settings.gemini_api_key)


def create_agent(
    agent_id: str,
    name: str,
    description: str,
    instructions: list[str],
    role: str = "",
    tools: Optional[list[Toolkit]] = None,
    model=None,
) -> Agent:
    """Create an Agno agent with persistent SQLite-backed memory.

    Args:
        agent_id: Unique identifier for the agent.
        name: Display name for the agent.
        description: The agent's persona / backstory.
        instructions: Behavioral rules the agent must follow.
        role: Role hint used for Team mode coordination.
        tools: List of Toolkit instances the agent can use.
        model: The LLM model instance to use. Defaults to Gemini 2.0 Flash.

    Returns:
        An Agno Agent with session storage wired to SQLite.
    """
    agent = Agent(
        id=agent_id,
        name=name,
        role=role or None,
        model=model or default_model,
        description=description,
        instructions=instructions,
        tools=tools or [],
        db=db,
        add_history_to_context=True,
        num_history_runs=5,
    )
    return agent
