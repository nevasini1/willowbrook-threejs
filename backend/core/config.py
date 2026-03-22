from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    project_name: str = "Gemini Hackathon AI World"
    gemini_api_key: str = ""

    # Memory
    memory_persist_dir: str = "data/memory_indexes"

    # Memory scoring weights
    memory_relevance_weight: float = 0.5
    memory_recency_weight: float = 0.3
    memory_importance_weight: float = 0.2
    memory_recency_half_life_hours: float = 24.0
    memory_importance_model: str = "gemini-2.5-flash"

    # Planning
    plan_steps_min: int = 5
    plan_steps_max: int = 8
    plan_decompose_granularity_minutes: int = 15

    # Reflection
    reflection_importance_threshold: float = 150.0
    reflection_recent_memory_count: int = 100
    reflection_default_importance: int = 8

    # Memory consolidation
    memory_max_per_agent: int = 500
    memory_short_term_buffer: int = 50
    memory_consolidation_similarity_threshold: float = 0.85
    memory_consolidation_cluster_size: int = 5
    memory_decay_rate_per_day: float = 0.02
    memory_prune_importance_threshold: float = 1.0

    # Auto-tick
    auto_tick_enabled: bool = True
    auto_tick_interval_seconds: int = 30

    # Event log
    event_log_max_per_location: int = 20

    # Relationship dynamics
    relationship_decay_rate_per_day: float = 0.01
    relationship_negative_min: float = -1.0

    # Social graph
    social_graph_persist_dir: str = "data/social_graph"

    # Neo4j (graph database for social relationships)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # Langfuse observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"
    langfuse_enabled: bool = False

    # Temporal
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "agent-task-queue"

    class Config:
        env_file = ("../.env", ".env")
        extra = "ignore"

settings = Settings()
