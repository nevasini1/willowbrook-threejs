import Phaser from 'phaser';
import { ApiClient, WorldState, AgentState } from '../ApiClient';
import { WorldRenderer, TILE_SIZE } from '../WorldRenderer';
import { CHARACTER_NAMES } from './BootScene';
import { UIPanel } from '../UIPanel';
import { FALLBACK_AGENTS } from '../fallbackWorld';

const PLAYER_SPEED = 160; // pixels per second (for arcade physics)
const DEFAULT_PLAYER_SPRITE = 'Adam_Smith';

// Always-visible mood display: text + color (never empty)
const MOOD_DISPLAY: Record<string, { text: string; color: number }> = {
  happy: { text: '\u263A', color: 0x2ea043 },  // ☺
  sad: { text: '\u2639', color: 0x6e7681 },  // ☹
  angry: { text: '\u2620', color: 0xf85149 },  // ☠
  excited: { text: '\u2605', color: 0xd29922 },  // ★
  anxious: { text: '\u2248', color: 0xa371f7 },  // ≈
  neutral: { text: '\u2014', color: 0x8b949e },  // —
};

// Per-agent metadata tracked alongside Container sprites
interface AgentMeta {
  container: Phaser.GameObjects.Container;
  moodIcon: Phaser.GameObjects.Text;
  moodBar: Phaser.GameObjects.Graphics;
  thoughtBubble: Phaser.GameObjects.Container | null;
  mood: string;
  planStep: string;
  spriteName: string;
}

export class MainScene extends Phaser.Scene {
  private apiClient!: ApiClient;
  private worldState: WorldState | null = null;
  private worldRenderer!: WorldRenderer;
  private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
  private keysDown: Record<string, boolean> = {};
  private player!: Phaser.Types.Physics.Arcade.SpriteWithDynamicBody;
  private agentSprites: Map<string, Phaser.GameObjects.Container> = new Map();
  private agentMeta: Map<string, AgentMeta> = new Map();
  private initialized: boolean = false;
  private uiPanel!: UIPanel;
  private selectedAgentId: string | null = null;
  private selectionIndicator: Phaser.GameObjects.Graphics | null = null;
  private selectionPulseTime: number = 0;

  constructor() {
    super({ key: 'MainScene' });
  }

  async create(): Promise<void> {
    this.apiClient = new ApiClient();

    // Build the tilemap world
    this.worldRenderer = new WorldRenderer(this);
    const map = this.worldRenderer.buildWorld();

    // Create walking animations for each character atlas
    this.createCharacterAnimations();

    // Create the player sprite
    this.createPlayer(map);

    // Camera setup
    this.cameras.main.setBounds(0, 0, this.worldRenderer.getMapWidthPx(), this.worldRenderer.getMapHeightPx());
    this.cameras.main.startFollow(this.player, true, 0.08, 0.08);

    // Input — arrow keys via Phaser, WASD via DOM so they don't get
    // swallowed when the user is typing in sidebar inputs.
    this.cursors = this.input.keyboard!.createCursorKeys();

    // Un-capture keys so the sidebar inputs can receive Space and other keys natively
    this.input.keyboard!.clearCaptures();

    const onKeyDown = (e: KeyboardEvent) => { this.keysDown[e.code] = true; };
    const onKeyUp = (e: KeyboardEvent) => { this.keysDown[e.code] = false; };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    this.events.on('shutdown', () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    });

    // Unfocus active inputs when clicking the game canvas so movement can resume
    this.input.on('pointerdown', () => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });

    // Scroll-to-zoom
    this.input.on('wheel', (_p: unknown, _gx: unknown, _gy: unknown, _dx: unknown, dy: number) => {
      const cam = this.cameras.main;
      cam.setZoom(Phaser.Math.Clamp(cam.zoom - dy * 0.001, 0.4, 3));
    });

    // Try fetching agents from backend, fall back to sample agents
    let backendAvailable = false;
    let agents: AgentState[] = FALLBACK_AGENTS;
    try {
      this.worldState = await this.apiClient.fetchState();
      backendAvailable = true;
      agents = this.worldState.agents;
    } catch {
      console.warn('Backend unavailable \u2014 using fallback agents');
    }
    this.renderAgents(agents);

    // HUD
    const mode = backendAvailable ? '' : ' [OFFLINE]';
    const agentCount = agents.length;
    this.add.text(10, 10, `WASD / Arrows = move   Scroll = zoom${mode}`, {
      fontSize: '14px', color: '#ffffff',
      backgroundColor: '#000000aa', padding: { x: 8, y: 4 },
    }).setScrollFactor(0).setDepth(1000);

    this.add.text(10, 35, `Agents: ${agentCount}`, {
      fontSize: '12px', color: '#aaffaa',
      backgroundColor: '#000000aa', padding: { x: 6, y: 4 },
    }).setScrollFactor(0).setDepth(1000);

    // Selection indicator (single reusable Graphics object)
    this.selectionIndicator = this.add.graphics();
    this.selectionIndicator.setDepth(999);
    this.selectionIndicator.setVisible(false);

    // UI Panel
    this.uiPanel = new UIPanel(this.apiClient, this);
    this.uiPanel.setAgents(agents);

    // WebSocket for live updates
    if (backendAvailable) {
      this.apiClient.onStateUpdate((state: WorldState) => {
        this.worldState = state;
        this.updateAgentPositions(state.agents);
        this.uiPanel.setAgents(state.agents);
      });
      this.apiClient.connectWebSocket();
    }

    this.initialized = true;
  }

  update(): void {
    if (!this.initialized) return;

    // Skip movement when typing in sidebar inputs
    const ae = document.activeElement;
    const isTyping = ae instanceof HTMLInputElement || ae instanceof HTMLTextAreaElement;
    if (isTyping) {
      this.player.setVelocity(0, 0);
      this.player.anims.stop();
      return;
    }

    // Player movement
    let vx = 0;
    let vy = 0;
    if (this.cursors.left.isDown || this.keysDown['KeyA']) vx = -PLAYER_SPEED;
    else if (this.cursors.right.isDown || this.keysDown['KeyD']) vx = PLAYER_SPEED;
    if (this.cursors.up.isDown || this.keysDown['KeyW']) vy = -PLAYER_SPEED;
    else if (this.cursors.down.isDown || this.keysDown['KeyS']) vy = PLAYER_SPEED;

    this.player.setVelocity(vx, vy);

    // Normalize diagonal speed
    if (vx !== 0 && vy !== 0) {
      this.player.setVelocity(vx * 0.707, vy * 0.707);
    }

    // Play appropriate walking animation
    const spriteKey = DEFAULT_PLAYER_SPRITE;
    if (vx < 0) {
      this.player.anims.play(`${spriteKey}_left_walk`, true);
    } else if (vx > 0) {
      this.player.anims.play(`${spriteKey}_right_walk`, true);
    } else if (vy < 0) {
      this.player.anims.play(`${spriteKey}_up_walk`, true);
    } else if (vy > 0) {
      this.player.anims.play(`${spriteKey}_down_walk`, true);
    } else {
      this.player.anims.stop();
      // Set idle frame based on last direction
      const currentAnim = this.player.anims.currentAnim;
      if (currentAnim) {
        const dir = currentAnim.key.includes('left') ? 'left' :
          currentAnim.key.includes('right') ? 'right' :
            currentAnim.key.includes('up') ? 'up' : 'down';
        this.player.setFrame(dir);
      }
    }

    // Advance pulse timer
    this.selectionPulseTime += 0.05;

    // Keep selection indicator following the selected agent
    this.updateSelectionIndicator();
  }

  // Create walking animations for all character atlases
  private createCharacterAnimations(): void {
    const directions = ['down', 'left', 'right', 'up'];

    for (const name of CHARACTER_NAMES) {
      if (!this.textures.exists(name)) continue;

      for (const dir of directions) {
        this.anims.create({
          key: `${name}_${dir}_walk`,
          frames: [
            { key: name, frame: `${dir}-walk.000` },
            { key: name, frame: `${dir}-walk.001` },
            { key: name, frame: `${dir}-walk.002` },
            { key: name, frame: `${dir}-walk.003` },
          ],
          frameRate: 4,
          repeat: -1,
        });
      }
    }
  }

  private createPlayer(map: Phaser.Tilemaps.Tilemap): void {
    // Spawn near the town center (Ryan Park's area — open space)
    // Validate player spawn against collision layer
    const playerSpawn = this.worldRenderer.findNearestWalkable(65, 25);
    const spawnX = playerSpawn.x * TILE_SIZE + TILE_SIZE / 2;
    const spawnY = playerSpawn.y * TILE_SIZE + TILE_SIZE / 2;

    this.player = this.physics.add.sprite(spawnX, spawnY, DEFAULT_PLAYER_SPRITE, 'down');
    this.player.setDepth(4);
    this.player.body.setSize(20, 20);
    this.player.body.setOffset(6, 12);

    // Add collision with the collision layer
    const collisionLayer = this.worldRenderer.getCollisionLayer();
    if (collisionLayer) {
      this.physics.add.collider(this.player, collisionLayer);
    }

    // Add a "YOU" tag above the player
    const tag = this.add.text(0, 0, 'YOU', {
      fontSize: '13px', fontStyle: 'bold', color: '#ffc107',
      backgroundColor: '#1a1a2eee', padding: { x: 6, y: 3 },
      shadow: { offsetX: 1, offsetY: 1, color: '#000000', blur: 3, fill: true },
    }).setOrigin(0.5, 1).setDepth(1000);

    // Update tag position each frame
    this.events.on('update', () => {
      tag.setPosition(this.player.x, this.player.y - 20);
    });
  }

  // Agent rendering
  private renderAgents(agents: AgentState[]): void {
    for (const agent of agents) {
      this.createAgentSprite(agent);
    }
  }

  private createAgentSprite(agent: AgentState): void {
    // Validate position against collision layer — nudge to nearest walkable tile
    const safe = this.worldRenderer.findNearestWalkable(agent.x, agent.y);
    const px = safe.x * TILE_SIZE + TILE_SIZE / 2;
    const py = safe.y * TILE_SIZE + TILE_SIZE / 2;

    const children: Phaser.GameObjects.GameObject[] = [];

    // Use character atlas sprite if available, otherwise fallback circle
    const spriteName = agent.sprite_key || agent.name.replace(/ /g, '_');
    if (this.textures.exists(spriteName)) {
      const sprite = this.add.sprite(0, 0, spriteName, 'down');
      sprite.setName('sprite');
      children.push(sprite);
    } else {
      // Fallback colored circle
      const gfx = this.add.graphics();
      const agentColors = [0xff4444, 0x4488ff, 0x44cc44, 0xffaa00, 0xff44ff];
      const colorIdx = Math.abs(agent.id.split('').reduce((a, c) => a + c.charCodeAt(0), 0)) % agentColors.length;
      gfx.fillStyle(agentColors[colorIdx], 1);
      gfx.fillCircle(0, 0, TILE_SIZE * 0.4);
      gfx.lineStyle(2, 0xffffff, 1);
      gfx.strokeCircle(0, 0, TILE_SIZE * 0.4);
      children.push(gfx);
    }

    const nameTag = this.add.text(0, -TILE_SIZE * 1.3, agent.name, {
      fontSize: '20px', fontStyle: 'bold', color: '#ffffff',
      backgroundColor: '#1a1a2eee', padding: { x: 8, y: 4 },
      shadow: { offsetX: 1, offsetY: 1, color: '#000000', blur: 4, fill: true },
    }).setOrigin(0.5, 1);
    children.push(nameTag);

    const actionTag = this.add.text(0, TILE_SIZE * 0.8, agent.current_action, {
      fontSize: '15px', color: '#e0e0e0',
      backgroundColor: '#1a1a2ecc', padding: { x: 6, y: 3 },
      shadow: { offsetX: 1, offsetY: 1, color: '#000000', blur: 2, fill: true },
    }).setOrigin(0.5, 0);
    actionTag.setName('actionLabel');
    children.push(actionTag);

    // Mood icon (always visible — never empty)
    const moodData = MOOD_DISPLAY[agent.mood] ?? MOOD_DISPLAY.neutral;
    const moodIcon = this.add.text(0, -TILE_SIZE * 1.3 - 28, moodData.text, {
      fontSize: '20px',
    }).setOrigin(0.5, 1);
    moodIcon.setName('moodIcon');
    children.push(moodIcon);

    // Mood bar (colored bar under name tag)
    const moodBar = this.add.graphics();
    moodBar.fillStyle(moodData.color, 0.9);
    moodBar.fillRoundedRect(-20, -TILE_SIZE * 1.3 + 6, 40, 6, 3);
    children.push(moodBar);

    const container = this.add.container(px, py, children);
    container.setDepth(4);
    container.setSize(TILE_SIZE, TILE_SIZE);

    // Make container interactive for click-to-select
    container.setInteractive(
      new Phaser.Geom.Rectangle(-TILE_SIZE / 2, -TILE_SIZE / 2, TILE_SIZE, TILE_SIZE),
      Phaser.Geom.Rectangle.Contains,
    );
    container.on('pointerdown', () => {
      this.selectAgent(agent.id);
    });

    this.agentSprites.set(agent.id, container);
    this.agentMeta.set(agent.id, {
      container,
      moodIcon,
      moodBar,
      thoughtBubble: null,
      mood: agent.mood ?? 'neutral',
      planStep: '',
      spriteName,
    });
  }

  private updateAgentPositions(agents: AgentState[]): void {
    for (const agent of agents) {
      const container = this.agentSprites.get(agent.id);
      if (!container) {
        this.createAgentSprite(agent);
        continue;
      }
      // Validate target position against collision layer
      const safe = this.worldRenderer.findNearestWalkable(agent.x, agent.y);
      const px = safe.x * TILE_SIZE + TILE_SIZE / 2;
      const py = safe.y * TILE_SIZE + TILE_SIZE / 2;

      // Determine direction for walking animation
      const dx = px - container.x;
      const dy = py - container.y;
      const spriteName = agent.sprite_key || agent.name.replace(/ /g, '_');
      const sprite = container.getByName('sprite') as Phaser.GameObjects.Sprite | null;

      if (sprite && this.textures.exists(spriteName) && (Math.abs(dx) > 1 || Math.abs(dy) > 1)) {
        let animKey: string;
        if (Math.abs(dx) > Math.abs(dy)) {
          animKey = dx < 0 ? `${spriteName}_left_walk` : `${spriteName}_right_walk`;
        } else {
          animKey = dy < 0 ? `${spriteName}_up_walk` : `${spriteName}_down_walk`;
        }
        if (this.anims.exists(animKey)) {
          sprite.anims.play(animKey, true);
        }
      }

      this.tweens.add({
        targets: container,
        x: px, y: py,
        duration: 300,
        ease: 'Power2',
        onComplete: () => {
          if (sprite) sprite.anims.stop();
        },
      });

      const actionLabel = container.getByName('actionLabel') as Phaser.GameObjects.Text;
      if (actionLabel) {
        actionLabel.setText(agent.current_action);
      }

      // Update mood icon + bar when mood changes
      const meta = this.agentMeta.get(agent.id);
      if (meta) {
        const newMood = agent.mood ?? 'neutral';
        if (newMood !== meta.mood) {
          meta.mood = newMood;
          const moodData = MOOD_DISPLAY[newMood] ?? MOOD_DISPLAY.neutral;
          meta.moodIcon.setText(moodData.text);
          // Redraw mood bar with new color
          meta.moodBar.clear();
          meta.moodBar.fillStyle(moodData.color, 0.8);
          meta.moodBar.fillRoundedRect(-12, -TILE_SIZE * 0.7 + 2, 24, 4, 2);
        }

        // Show thought bubble when plan step changes
        const currentPlanText = (agent.daily_plan && agent.daily_plan[agent.current_plan_step]) ?? '';
        if (currentPlanText && currentPlanText !== meta.planStep) {
          meta.planStep = currentPlanText;
          this.showThoughtBubble(meta, container);
        }
      }
    }
  }

  // ── Click-to-select ──────────────────────────────────────────────

  private selectAgent(agentId: string): void {
    this.selectedAgentId = agentId;
    if (this.uiPanel) {
      this.uiPanel.selectAgentById(agentId);
    }
  }

  private updateSelectionIndicator(): void {
    if (!this.selectionIndicator) return;
    if (!this.selectedAgentId) {
      this.selectionIndicator.setVisible(false);
      return;
    }
    const container = this.agentSprites.get(this.selectedAgentId);
    if (!container) {
      this.selectionIndicator.setVisible(false);
      return;
    }
    this.selectionIndicator.setVisible(true);
    this.selectionIndicator.clear();

    const t = this.selectionPulseTime;
    const pulseAlpha = 0.3 + 0.2 * Math.sin(t);
    const innerAlpha = 0.6 + 0.3 * Math.sin(t);
    const innerRadius = 18 + 2 * Math.sin(t);

    // Outer glow ring
    this.selectionIndicator.lineStyle(4, 0x58a6ff, pulseAlpha);
    this.selectionIndicator.strokeCircle(container.x, container.y, innerRadius + 4);

    // Inner ring
    this.selectionIndicator.lineStyle(3, 0x58a6ff, innerAlpha);
    this.selectionIndicator.strokeCircle(container.x, container.y, innerRadius);
  }

  // ── Thought bubbles ─────────────────────────────────────────────

  private showThoughtBubble(meta: AgentMeta, agentContainer: Phaser.GameObjects.Container): void {
    // Destroy existing bubble if any
    if (meta.thoughtBubble) {
      meta.thoughtBubble.destroy();
      meta.thoughtBubble = null;
    }

    const truncated = meta.planStep.length > 55 ? meta.planStep.slice(0, 52) + '...' : meta.planStep;

    const textObj = this.add.text(0, -8, truncated, {
      fontSize: '15px',
      color: '#1c1e21',
      wordWrap: { width: 200 },
      padding: { x: 0, y: 0 },
    }).setOrigin(0.5, 1);

    const bounds = textObj.getBounds();
    const padX = 8;
    const padY = 6;
    const bgW = bounds.width + padX * 2;
    const bgH = bounds.height + padY * 2;

    // Drop shadow
    const shadow = this.add.graphics();
    shadow.fillStyle(0x000000, 0.3);
    shadow.fillRoundedRect(-bgW / 2 + 2, -bgH - 8 + 2, bgW, bgH, 8);

    const bg = this.add.graphics();
    bg.fillStyle(0xffffff, 0.92);
    bg.fillRoundedRect(-bgW / 2, -bgH - 8, bgW, bgH, 8);
    // Triangle pointer
    bg.fillTriangle(-4, -8, 4, -8, 0, 0);

    textObj.setPosition(0, -8 - padY);

    const bubble = this.add.container(agentContainer.x, agentContainer.y - 44, [shadow, bg, textObj]);
    bubble.setDepth(1002);
    bubble.setAlpha(0);
    meta.thoughtBubble = bubble;

    // Fade-in tween (0 → 1, 300ms)
    this.tweens.add({
      targets: bubble,
      alpha: 1,
      duration: 300,
      ease: 'Power2',
    });

    // 10s total: 9s visible + 1s fade-out
    this.time.delayedCall(9000, () => {
      if (meta.thoughtBubble === bubble) {
        this.tweens.add({
          targets: bubble,
          alpha: 0,
          duration: 1000,
          ease: 'Power2',
          onComplete: () => {
            if (meta.thoughtBubble === bubble) {
              bubble.destroy();
              meta.thoughtBubble = null;
            }
          },
        });
      }
    });
  }

  // ── Camera focus ────────────────────────────────────────────────

  public focusOnAgent(agentId: string): void {
    const container = this.agentSprites.get(agentId);
    if (!container) return;

    // Stop following the player temporarily
    this.cameras.main.stopFollow();
    this.cameras.main.pan(container.x, container.y, 500, 'Power2');

    this.selectedAgentId = agentId;
  }
}
