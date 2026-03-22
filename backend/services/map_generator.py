"""
MapGenerator — procedurally expands the world using Gemini.

When a player approaches the edge of the current map, this service
generates new EnvironmentNode subtrees using available tile_keys from
the asset registry.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from core.config import settings
from models.state import EnvironmentNode, WorldState

logger = logging.getLogger(__name__)

# Directions and their offset vectors (in tile coords)
DIRECTION_OFFSETS = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}


class MapGenerator:
    """Generates new world areas by prompting Gemini."""

    EXPANSION_SIZE = 12  # tiles in the expansion direction

    def __init__(self, asset_registry: dict):
        self.asset_registry = asset_registry
        self._available_tile_keys = self._extract_tile_keys()

    def _extract_tile_keys(self) -> list[str]:
        """Get all valid tile_keys from the asset registry."""
        keys: list[str] = []
        for category, items in self.asset_registry.items():
            if category == "_meta":
                continue
            if isinstance(items, dict):
                keys.extend(items.keys())
        return keys

    def expand(
        self,
        world_state: WorldState,
        direction: str,
        trigger_x: int = 0,
        trigger_y: int = 0,
    ) -> Optional[EnvironmentNode]:
        """Generate a new area in the given direction.

        Returns the new EnvironmentNode subtree, or None on failure.
        Also updates world_state.environment_root dimensions and appends the new child.
        """
        if direction not in DIRECTION_OFFSETS:
            logger.warning("Invalid direction: %s", direction)
            return None

        root = world_state.environment_root
        dx, dy = DIRECTION_OFFSETS[direction]

        # Calculate new zone position
        if direction == "north":
            new_x = root.x
            new_y = root.y - self.EXPANSION_SIZE
            new_w = root.w
            new_h = self.EXPANSION_SIZE
        elif direction == "south":
            new_x = root.x
            new_y = root.y + root.h
            new_w = root.w
            new_h = self.EXPANSION_SIZE
        elif direction == "east":
            new_x = root.x + root.w
            new_y = root.y
            new_w = self.EXPANSION_SIZE
            new_h = root.h
        else:  # west
            new_x = root.x - self.EXPANSION_SIZE
            new_y = root.y
            new_w = self.EXPANSION_SIZE
            new_h = root.h

        # Build the prompt
        existing_zones = [c.name for c in root.children if c.name]
        tile_keys_str = ", ".join(self._available_tile_keys)

        prompt = (
            f"You are a world designer for a small town called '{root.name}'.\n"
            f"The town already has these areas: {', '.join(existing_zones)}.\n\n"
            f"Generate a NEW area to the {direction} of the existing town.\n"
            f"The area should be at grid position x={new_x}, y={new_y}, "
            f"with size w={new_w}, h={new_h}.\n\n"
            f"Available tile_keys you MUST use: {tile_keys_str}\n\n"
            "Return a JSON object representing an EnvironmentNode with this schema:\n"
            "{\n"
            '  "id": "unique_zone_id",\n'
            '  "name": "Area Name",\n'
            '  "description": "A description of this area",\n'
            '  "node_type": "zone",\n'
            '  "tile_key": "one of the terrain tile_keys",\n'
            f'  "x": {new_x}, "y": {new_y}, "w": {new_w}, "h": {new_h},\n'
            '  "walkable": true,\n'
            '  "children": [\n'
            '    {"id": "obj_id", "name": "Object Name", "description": "...", '
            '"node_type": "object", "tile_key": "valid_key", '
            '"x": <int>, "y": <int>, "w": 1, "h": 1, "walkable": false, "children": []}\n'
            "  ]\n"
            "}\n\n"
            "Include 3-6 interesting objects (trees, benches, buildings, etc). "
            "Make the area feel like a natural extension of the town. "
            "All tile_keys must come from the available list above. "
            "Return ONLY valid JSON, no other text."
        )

        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "max_output_tokens": 4096,
                    "temperature": 0.9,
                    "response_mime_type": "application/json",
                },
            )
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            data = json.loads(text)
            new_node = EnvironmentNode(**data)

            # Validate tile_keys
            self._validate_tile_keys(new_node)

            # Update world dimensions
            if direction == "north":
                root.y = new_y
                root.h += new_h
            elif direction == "south":
                root.h += new_h
            elif direction == "east":
                root.w += new_w
            elif direction == "west":
                root.x = new_x
                root.w += new_w

            # Append to world
            root.children.append(new_node)
            world_state.expansion_count += 1

            logger.info(
                "Expanded world %s: new zone '%s' at (%d,%d) %dx%d",
                direction, new_node.name, new_x, new_y, new_w, new_h,
            )
            return new_node

        except Exception as e:
            logger.error("Map expansion failed (%s): %s", direction, e)
            return None

    def _validate_tile_keys(self, node: EnvironmentNode) -> None:
        """Replace invalid tile_keys with a safe fallback."""
        if node.tile_key and node.tile_key not in self._available_tile_keys:
            logger.warning("Invalid tile_key '%s', replacing with 'grass'", node.tile_key)
            node.tile_key = "grass"
        for child in node.children:
            self._validate_tile_keys(child)
