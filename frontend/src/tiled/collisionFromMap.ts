export const TILE_SIZE = 32;

export interface TileCollisionGrid {
  width: number;
  height: number;
  isBlocked(tileX: number, tileY: number): boolean;
  findNearestWalkable(tileX: number, tileY: number, maxRadius?: number): { x: number; y: number };
}

export async function loadCollisionFromTiled(url: string): Promise<TileCollisionGrid> {
  const res = await fetch(url);
  const map = await res.json();
  const w: number = map.width;
  const h: number = map.height;
  const layer = map.layers?.find((l: { name?: string }) => l.name === 'Collisions');
  const data: number[] = layer?.data ?? [];
  if (data.length !== w * h) {
    throw new Error(`Collisions layer size mismatch: expected ${w * h}, got ${data.length}`);
  }

  const isBlocked = (tileX: number, tileY: number): boolean => {
    if (tileX < 0 || tileY < 0 || tileX >= w || tileY >= h) return true;
    const gid = data[tileY * w + tileX];
    return gid !== 0;
  };

  const findNearestWalkable = (tileX: number, tileY: number, maxRadius: number = 15): { x: number; y: number } => {
    if (!isBlocked(tileX, tileY)) return { x: tileX, y: tileY };
    for (let r = 1; r <= maxRadius; r++) {
      for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
          if (Math.abs(dx) !== r && Math.abs(dy) !== r) continue;
          const nx = tileX + dx;
          const ny = tileY + dy;
          if (!isBlocked(nx, ny)) return { x: nx, y: ny };
        }
      }
    }
    return { x: tileX, y: tileY };
  };

  return { width: w, height: h, isBlocked, findNearestWalkable };
}

export function tileCenterToWorld(
  tileX: number,
  tileY: number,
  mapWidthTiles: number,
  mapHeightTiles: number,
  tileWorldSize: number,
): { x: number; z: number } {
  const halfW = (mapWidthTiles * tileWorldSize) / 2;
  const halfH = (mapHeightTiles * tileWorldSize) / 2;
  const x = (tileX + 0.5) * tileWorldSize - halfW;
  const z = (tileY + 0.5) * tileWorldSize - halfH;
  return { x, z };
}

export function worldToTile(
  worldX: number,
  worldZ: number,
  mapWidthTiles: number,
  mapHeightTiles: number,
  tileWorldSize: number,
): { tx: number; ty: number } {
  const halfW = (mapWidthTiles * tileWorldSize) / 2;
  const halfH = (mapHeightTiles * tileWorldSize) / 2;
  const tx = Math.floor((worldX + halfW) / tileWorldSize);
  const ty = Math.floor((worldZ + halfH) / tileWorldSize);
  return { tx, ty };
}
