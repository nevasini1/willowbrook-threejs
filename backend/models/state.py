from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class NodeType(str, Enum):
    WORLD = "world"
    ZONE = "zone"          # outdoor area (town square, park)
    BUILDING = "building"  # structure with interior rooms
    ROOM = "room"          # interior space (kitchen, bedroom)
    OBJECT = "object"      # interactable thing (stove, bench)


class EnvironmentNode(BaseModel):
    id: str
    name: str
    description: str
    node_type: NodeType = NodeType.OBJECT
    tile_key: Optional[str] = None  # maps to asset_registry entry
    x: int = 0                      # grid position (tile coords)
    y: int = 0
    w: int = 1                      # size in tiles
    h: int = 1
    walkable: bool = True
    children: List["EnvironmentNode"] = []


# Resolve forward references
EnvironmentNode.model_rebuild()


class AgentState(BaseModel):
    id: str
    name: str
    location_id: str       # id of the EnvironmentNode the agent is in
    current_action: str
    x: int = 0             # grid position within their location
    y: int = 0
    sprite_key: str = "character_1"
    description: str = ""           # persona/backstory
    instructions: List[str] = []   # behavioral rules
    role: str = ""                  # role hint for Team mode
    daily_plan: Optional[List[str]] = None
    current_plan_step: int = 0
    day_number: int = 1
    mood: str = "neutral"


class WorldState(BaseModel):
    environment_root: EnvironmentNode
    agents: List[AgentState]
    expansion_count: int = 0
    pending_messages: Dict[str, List[dict]] = Field(default_factory=dict)
    location_events: Dict[str, List[dict]] = Field(default_factory=dict)
