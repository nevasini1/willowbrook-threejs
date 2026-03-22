/**
 * WorldRenderer — renders the pre-built Tiled tilemap ("the Ville")
 * using Phaser's native tilemap system and provides collision detection
 * from the Collisions layer.
 */

import Phaser from 'phaser';

const TILE_SIZE = 32;

// Tileset names as they appear in the_ville_jan7.json
const TILESET_NAMES = [
  'CuteRPG_Field_B',
  'CuteRPG_Field_C',
  'CuteRPG_Harbor_C',
  'Room_Builder_32x32',
  'CuteRPG_Village_B',
  'CuteRPG_Forest_B',
  'CuteRPG_Desert_C',
  'CuteRPG_Mountains_B',
  'CuteRPG_Desert_B',
  'CuteRPG_Forest_C',
  'interiors_pt1',
  'interiors_pt2',
  'interiors_pt3',
  'interiors_pt4',
  'interiors_pt5',
  'blocks',
  'blocks_2',
  'blocks_3',
];

// Layer names in order, as they appear in the tilemap JSON
const LAYER_CONFIG = [
  { name: 'Bottom Ground', depth: -4 },
  { name: 'Exterior Ground', depth: -3 },
  { name: 'Exterior Decoration L1', depth: -2 },
  { name: 'Exterior Decoration L2', depth: -1 },
  { name: 'Interior Ground', depth: 0 },
  { name: 'Wall', depth: 1 },
  { name: 'Interior Furniture L1', depth: 2 },
  { name: 'Interior Furniture L2 ', depth: 3 },  // note trailing space in JSON
  { name: 'Foreground L1', depth: 5 },
  { name: 'Foreground L2', depth: 6 },
  { name: 'Collisions', depth: -10 },
];

export class WorldRenderer {
  private scene: Phaser.Scene;
  private map!: Phaser.Tilemaps.Tilemap;
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  /** Build the world from the pre-loaded Tiled tilemap. */
  buildWorld(): Phaser.Tilemaps.Tilemap {
    this.map = this.scene.make.tilemap({ key: 'the_ville' });

    // Add all tilesets
    const tilesets: Phaser.Tilemaps.Tileset[] = [];
    for (const name of TILESET_NAMES) {
      const ts = this.map.addTilesetImage(name, name);
      if (ts) tilesets.push(ts);
    }

    // Create each layer
    for (const cfg of LAYER_CONFIG) {
      const layer = this.map.createLayer(cfg.name, tilesets);
      if (!layer) continue;

      layer.setDepth(cfg.depth);

      if (cfg.name === 'Collisions') {
        // Hide the collision layer and set up collision
        layer.setVisible(false);
        layer.setCollisionByProperty({ collide: true });
        // Also set collision on any tile that exists in this layer
        layer.setCollisionByExclusion([-1]);
        this.collisionLayer = layer;
      }

      // Foreground layers should render on top of characters (depth > character depth of 4)
      if (cfg.name.startsWith('Foreground')) {
        layer.setDepth(cfg.depth);
      }
    }

    return this.map;
  }

  /** Get the tilemap. */
  getMap(): Phaser.Tilemaps.Tilemap {
    return this.map;
  }

  /** Get the collision layer for physics. */
  getCollisionLayer(): Phaser.Tilemaps.TilemapLayer | null {
    return this.collisionLayer;
  }

  /** Get the map width in pixels. */
  getMapWidthPx(): number {
    return this.map.widthInPixels;
  }

  /** Get the map height in pixels. */
  getMapHeightPx(): number {
    return this.map.heightInPixels;
  }

  /** Check if a tile coordinate is blocked (has a collision tile). */
  isBlocked(tileX: number, tileY: number): boolean {
    if (!this.collisionLayer) return false;
    if (tileX < 0 || tileY < 0 || tileX >= this.map.width || tileY >= this.map.height) return true;
    const tile = this.collisionLayer.getTileAt(tileX, tileY);
    return tile !== null;
  }

  /** Check if a pixel position is blocked. */
  isBlockedAtPixel(px: number, py: number): boolean {
    const tileX = Math.floor(px / TILE_SIZE);
    const tileY = Math.floor(py / TILE_SIZE);
    return this.isBlocked(tileX, tileY);
  }

  /** Find the nearest walkable tile to the given tile coordinate.
   *  Returns the original position if it's already walkable, otherwise
   *  spirals outward up to `maxRadius` tiles to find a valid spot. */
  findNearestWalkable(tileX: number, tileY: number, maxRadius: number = 15): { x: number; y: number } {
    if (!this.isBlocked(tileX, tileY)) return { x: tileX, y: tileY };

    for (let r = 1; r <= maxRadius; r++) {
      for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue; // only check perimeter
          const nx = tileX + dx;
          const ny = tileY + dy;
          if (!this.isBlocked(nx, ny)) return { x: nx, y: ny };
        }
      }
    }

    // Fallback: return original position (shouldn't happen on a normal map)
    return { x: tileX, y: tileY };
  }
}

export { TILE_SIZE };
