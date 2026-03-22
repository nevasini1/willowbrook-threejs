const GLB_BASE = '/assets/3d/blocky-characters/Models/GLB format';
const VARIANTS = 'abcdefghijklmnopqrstuvwxyz'.split('');

export function glbPathForAgent(spriteKey: string, name: string): string {
  const key = (spriteKey || name).replace(/ /g, '_');
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  const idx = Math.abs(h) % 18;
  const letter = VARIANTS[idx];
  return `${GLB_BASE}/character-${letter}.glb`;
}

export function pickAnimationClip(
  animations: { name: string }[],
  preferred: string[],
): number {
  const lower = animations.map((a) => a.name.toLowerCase());
  for (const p of preferred) {
    const i = lower.findIndex((n) => n.includes(p));
    if (i >= 0) return i;
  }
  return 0;
}
