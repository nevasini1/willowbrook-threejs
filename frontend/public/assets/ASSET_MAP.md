# Asset Library → Environment Tree Mapping

This document describes how sprites in `public/assets/` map to nodes in the
environment tree (`seed_world.json`) via tile keys defined in `asset_registry.json`.

## How the mapping works

```
seed_world.json node            asset_registry.json          sprite file
─────────────────────────────   ──────────────────────────   ─────────────────────────
{ "tile_key": "grass", ... }  →  terrain.grass.sprite       →  terrain/grass.png
{ "tile_key": "fountain", … } →  outdoor_objects.fountain    →  outdoor/fountain.png
{ "tile_key": "stove", … }    →  furniture.stove.sprite      →  furniture/stove.png
```

Every node in the environment tree carries a `tile_key`. The renderer looks up
that key in `asset_registry.json` to find the `sprite` path, then loads the
corresponding `.png` from this directory.

## Folder structure

```
assets/
├── terrain/          # Ground tiles (grass, roads, floors)
│   ├── grass.png
│   ├── dirt_path.png
│   ├── road.png
│   ├── water.png
│   ├── floor_wood.png
│   ├── floor_tile.png
│   └── floor_carpet.png
│
├── structures/       # Walls, doors, building shells
│   ├── wall_h.png
│   ├── wall_v.png
│   ├── door.png
│   ├── window.png
│   └── house.png
│
├── furniture/        # Indoor interactable objects
│   ├── stove.png
│   ├── fridge.png
│   ├── kitchen_table.png
│   ├── chair.png
│   ├── bed.png
│   ├── desk.png
│   ├── bookshelf.png
│   ├── couch.png
│   ├── tv.png
│   └── sink.png
│
├── outdoor/          # Nature + outdoor furniture
│   ├── tree_oak.png
│   ├── tree_pine.png
│   ├── bush.png
│   ├── flower_bed.png
│   ├── bench.png
│   ├── fountain.png
│   ├── lamp_post.png
│   ├── mailbox.png
│   └── trash_can.png
│
└── characters/       # Animated character spritesheets
    ├── char_1.png
    ├── char_2.png
    └── char_3.png
```

## Environment tree hierarchy (seed_world.json)

The tree maps the logical structure of the world. Each level narrows scope:

```
World: "Willowbrook" (40×30 tiles, grass)
│
├── Zone: "Town Square" (12×10, dirt_path)
│   ├── fountain, bench ×2, oak_tree ×2, lamp_post
│
├── Zone: "Main Street" (6×3, road)
│
├── Building: "Johnson Residence" (6×8, house_exterior)
│   ├── Room: "Kitchen" (6×4, floor_tile)
│   │   └── stove, fridge, sink, kitchen_table, chair ×2
│   ├── Object: "Front Door" (door)
│   └── Room: "Bedroom" (6×4, floor_carpet)
│       └── bed, desk, bookshelf
│
├── Zone: "Willowbrook Park" (12×7, grass)
│   ├── tree_pine ×2, tree_oak, flower_bed, bench, bush
│
└── Object: "Mailbox" (mailbox)
```

## Node types

| node_type  | Purpose                              | Example              |
|------------|--------------------------------------|----------------------|
| `world`    | Root container, sets default terrain | Willowbrook          |
| `zone`     | Open outdoor area                    | Town Square, Park    |
| `building` | Walled structure with rooms          | Johnson Residence    |
| `room`     | Interior space inside a building     | Kitchen, Bedroom     |
| `object`   | Single tile-key item (leaf node)     | Stove, Bench, Tree   |

## Rendering rules

1. **Terrain first** — Paint the parent's `tile_key` across its `w×h` area.
2. **Children on top** — Render child nodes over the parent terrain at their `x,y`.
3. **Walkability** — `walkable: false` objects block pathfinding; the collision
   map is built by compositing all non-walkable nodes.
4. **Multi-tile objects** — Some objects specify `w`/`h` > 1 (e.g. fountain 2×2,
   bed 1×2). Default is 1×1.
5. **Characters** — Agents reference a `sprite_key` from the `characters` section
   and are positioned independently of the environment tree.

## Adding new assets

1. Add the sprite `.png` to the appropriate folder.
2. Add a matching entry in `backend/data/asset_registry.json` with the correct
   `sprite` path, `category`, `walkable`, and optional `w`/`h`.
3. The LLM world generator can now use that `tile_key` in new environment nodes.
