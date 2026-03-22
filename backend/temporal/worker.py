"""
Temporal Worker — generic launcher.

Run with:  python -m temporal.worker

Or call ``run_worker()`` programmatically after registering providers.
The worker itself has NO app-specific imports — it only knows about
the activities and workflows defined inside the ``temporal`` package.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from temporalio.client import Client
from temporalio.worker import Worker

from temporal.activities import (
    call_llm,
    generate_daily_plan,
    retrieve_memories,
    update_world_state,
)
from temporal.workflows import (
    AgentLifecycleWorkflow,
    AgentTickWorkflow,
    WorldSimulationWorkflow,
)


async def run_worker(
    *,
    host: str = "localhost:7233",
    namespace: str = "default",
    task_queue: str = "agent-task-queue",
) -> None:
    """Connect to the Temporal server and run the worker until interrupted.

    Providers **must** be registered (via ``temporal.registry``) before
    calling this function.
    """
    print(f"Connecting to Temporal at {host} (namespace={namespace})...")

    client = await Client.connect(host, namespace=namespace)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[
            AgentTickWorkflow,
            AgentLifecycleWorkflow,
            WorldSimulationWorkflow,
        ],
        activities=[
            call_llm,
            generate_daily_plan,
            retrieve_memories,
            update_world_state,
        ],
    )

    print(f"Worker started — polling task queue '{task_queue}'.")
    await worker.run()


def main() -> None:
    """CLI entry-point.

    When invoked directly (``python -m temporal.worker``) this bootstraps
    the default providers from the app layer.  If you're embedding the
    temporal package elsewhere, call ``run_worker()`` after your own
    provider registration.
    """
    import sys
    from pathlib import Path

    # Ensure backend root is importable
    backend_dir = str(Path(__file__).resolve().parent.parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import json  # noqa: E402

    # Import the app-specific bootstrap that registers providers
    from providers import bootstrap_providers  # noqa: E402
    from services.memory_store import MemoryStore  # noqa: E402
    from models.state import WorldState  # noqa: E402

    # Load seed world state so the state provider can mutate it
    data_dir = Path(__file__).resolve().parent.parent / "data"
    with open(data_dir / "seed_world.json") as f:
        world_state = WorldState(**json.load(f))

    memory_store = MemoryStore()
    bootstrap_providers(memory_store=memory_store, world_state=world_state)

    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("\nWorker stopped.")


if __name__ == "__main__":
    main()
