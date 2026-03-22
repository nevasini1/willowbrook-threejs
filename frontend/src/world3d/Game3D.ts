import * as THREE from 'three';
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { clone as cloneSkinned } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { ApiClient, AgentState, WorldState } from '../ApiClient';
import { UIPanel } from '../UIPanel';
import { FALLBACK_AGENTS } from '../fallbackWorld';
import {
  loadCollisionFromTiled,
  tileCenterToWorld,
  worldToTile,
  type TileCollisionGrid,
} from '../tiled/collisionFromMap';
import { glbPathForAgent, pickAnimationClip } from './characterModel';

const MAP_JSON = '/assets/the_ville/visuals/the_ville_jan7.json';
const TILE_WORLD = 1;
const PLAYER_SPEED = 4.5;
const DEFAULT_PLAYER_SPRITE_KEY = 'Adam_Smith';

const MOOD_EMOJI: Record<string, string> = {
  happy: '\u263A',
  sad: '\u2639',
  angry: '\u2620',
  excited: '\u2605',
  anxious: '\u2248',
  neutral: '\u2014',
};

interface GltfTemplate {
  scene: THREE.Object3D;
  animations: THREE.AnimationClip[];
}

interface AgentVisual {
  root: THREE.Group;
  mixer: THREE.AnimationMixer | null;
  walkAction: THREE.AnimationAction | null;
  idleAction: THREE.AnimationAction | null;
  label: CSS2DObject;
  targetX: number;
  targetZ: number;
  planStep: string;
  mood: string;
}

export class Game3D {
  focusOnAgent(agentId: string): void {
    const vis = this.agentVisuals.get(agentId);
    if (!vis) return;
    const ax = vis.root.position.x;
    const az = vis.root.position.z;
    this.panCam0.copy(this.camera.position);
    this.panLook0.set(this.playerX, 0.6, this.playerZ);
    this.panCam1.set(ax + 6, 13, az + this.cameraDistance);
    this.panLook1.set(ax, 0.8, az);
    this.panT0 = performance.now();
    this.panning = true;
    this.followPlayer = false;
    this.selectedAgentId = agentId;
  }

  private container: HTMLElement;
  private grid!: TileCollisionGrid;
  private mapW = 140;
  private mapH = 100;

  private scene = new THREE.Scene();
  private camera!: THREE.PerspectiveCamera;
  private renderer!: THREE.WebGLRenderer;
  private labelRenderer!: CSS2DRenderer;
  private clock = new THREE.Clock();

  private raycaster = new THREE.Raycaster();
  private pointerNdc = new THREE.Vector2();

  private gltfLoader = new GLTFLoader();
  private gltfCache = new Map<string, Promise<GltfTemplate>>();

  private playerRoot!: THREE.Group;
  private playerMixer: THREE.AnimationMixer | null = null;
  private playerWalk: THREE.AnimationAction | null = null;
  private playerIdle: THREE.AnimationAction | null = null;
  private playerX = 0;
  private playerZ = 0;

  private agentVisuals = new Map<string, AgentVisual>();
  private selectionRing!: THREE.Mesh;
  private selectedAgentId: string | null = null;
  private selectionPulse = 0;

  private keysDown: Record<string, boolean> = {};
  private cameraDistance = 14;
  private followPlayer = true;
  private panning = false;
  private panT0 = 0;
  private readonly panDur = 850;
  private panCam0 = new THREE.Vector3();
  private panCam1 = new THREE.Vector3();
  private panLook0 = new THREE.Vector3();
  private panLook1 = new THREE.Vector3();

  private apiClient!: ApiClient;
  private uiPanel!: UIPanel;
  private hud!: HTMLDivElement;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  async start(): Promise<void> {
    this.grid = await loadCollisionFromTiled(MAP_JSON);
    this.mapW = this.grid.width;
    this.mapH = this.grid.height;

    const w = this.container.clientWidth;
    const h = window.innerHeight;

    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 500);
    this.camera.position.set(0, 18, 22);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);

    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.setSize(w, h);
    this.labelRenderer.domElement.style.position = 'absolute';
    this.labelRenderer.domElement.style.top = '0';
    this.labelRenderer.domElement.style.left = '0';
    this.labelRenderer.domElement.style.pointerEvents = 'none';
    this.container.appendChild(this.labelRenderer.domElement);

    this.scene.background = new THREE.Color(0x1a1a2e);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xfff5e6, 1.05);
    sun.position.set(40, 80, 30);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.near = 1;
    sun.shadow.camera.far = 200;
    sun.shadow.camera.left = -80;
    sun.shadow.camera.right = 80;
    sun.shadow.camera.top = 80;
    sun.shadow.camera.bottom = -80;
    this.scene.add(sun);

    const groundW = this.mapW * TILE_WORLD;
    const groundD = this.mapH * TILE_WORLD;
    const groundGeo = new THREE.PlaneGeometry(groundW, groundD);
    const groundMat = new THREE.MeshStandardMaterial({
      color: 0x3d6b45,
      roughness: 0.92,
      metalness: 0.05,
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    const gridHelper = new THREE.GridHelper(Math.max(groundW, groundD) + 2, Math.max(this.mapW, this.mapH), 0x223322, 0x1a2a1a);
    gridHelper.position.y = 0.01;
    this.scene.add(gridHelper);

    const spawn = this.grid.findNearestWalkable(65, 25);
    const p0 = tileCenterToWorld(spawn.x, spawn.y, this.mapW, this.mapH, TILE_WORLD);
    this.playerX = p0.x;
    this.playerZ = p0.z;

    this.playerRoot = new THREE.Group();
    this.playerRoot.position.set(this.playerX, 0, this.playerZ);
    this.playerRoot.userData.agentId = '__player__';
    this.scene.add(this.playerRoot);

    await this.attachCharacterModel(this.playerRoot, DEFAULT_PLAYER_SPRITE_KEY, 'Player');
    this.setupPlayerAnimations(this.playerRoot);

    const youDiv = document.createElement('div');
    youDiv.className = 'agent-label';
    youDiv.innerHTML = `<div class="agent-name" style="background:#ffc107;color:#1a1a2e">YOU</div>`;
    const youLabel = new CSS2DObject(youDiv);
    youLabel.position.set(0, 2.2, 0);
    this.playerRoot.add(youLabel);

    this.selectionRing = new THREE.Mesh(
      new THREE.RingGeometry(0.35, 0.55, 32),
      new THREE.MeshBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.85, side: THREE.DoubleSide }),
    );
    this.selectionRing.rotation.x = -Math.PI / 2;
    this.selectionRing.visible = false;
    this.selectionRing.position.y = 0.03;
    this.scene.add(this.selectionRing);

    this.apiClient = new ApiClient();
    let agents: AgentState[] = FALLBACK_AGENTS;
    let backendAvailable = false;
    try {
      const state = await this.apiClient.fetchState();
      agents = state.agents;
      backendAvailable = true;
    } catch {
      console.warn('Backend unavailable — using fallback agents');
    }

    for (const a of agents) {
      await this.createAgent(a);
    }

    this.hud = document.createElement('div');
    this.hud.style.cssText =
      'position:absolute;left:10px;top:10px;color:#fff;font:14px system-ui;background:#000000aa;padding:8px 10px;border-radius:6px;pointer-events:none;z-index:2';
    this.hud.textContent = `WASD / arrows — move   Scroll — zoom   Click agent — select${backendAvailable ? '' : ' [OFFLINE]'}`;
    this.container.style.position = 'relative';
    this.container.appendChild(this.hud);

    const countEl = document.createElement('div');
    countEl.style.cssText =
      'position:absolute;left:10px;top:48px;color:#aaffaa;font:12px system-ui;background:#000000aa;padding:6px 8px;border-radius:6px;pointer-events:none;z-index:2';
    countEl.textContent = `Agents: ${agents.length}`;
    this.container.appendChild(countEl);

    this.uiPanel = new UIPanel(this.apiClient, this);
    this.uiPanel.setAgents(agents);

    if (backendAvailable) {
      this.apiClient.onStateUpdate((state: WorldState) => {
        this.syncAgents(state.agents);
        this.uiPanel.setAgents(state.agents);
      });
      this.apiClient.connectWebSocket();
    }

    this.bindInput();
    window.addEventListener('resize', () => this.onResize());
    this.renderer.setAnimationLoop(() => this.frame());
  }

  private bindInput(): void {
    const canvas = this.renderer.domElement;

    const kd = (e: KeyboardEvent): void => {
      this.keysDown[e.code] = true;
    };
    const ku = (e: KeyboardEvent): void => {
      this.keysDown[e.code] = false;
    };
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);

    canvas.addEventListener('pointerdown', () => {
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    });

    canvas.addEventListener('click', (e) => this.onPointerClick(e));

    canvas.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        this.cameraDistance = THREE.MathUtils.clamp(this.cameraDistance + e.deltaY * 0.02, 6, 42);
      },
      { passive: false },
    );
  }

  private onPointerClick(event: PointerEvent): void {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointerNdc.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointerNdc.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    this.raycaster.setFromCamera(this.pointerNdc, this.camera);
    const hits = this.raycaster.intersectObjects(this.scene.children, true);
    for (const hit of hits) {
      let o: THREE.Object3D | null = hit.object;
      while (o) {
        const id = o.userData.agentId as string | undefined;
        if (id && id !== '__player__') {
          this.selectedAgentId = id;
          this.uiPanel.selectAgentById(id);
          return;
        }
        o = o.parent;
      }
    }
  }

  private onResize(): void {
    const w = this.container.clientWidth;
    const h = window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labelRenderer.setSize(w, h);
  }

  private async loadGltfTemplate(url: string): Promise<GltfTemplate> {
    const existing = this.gltfCache.get(url);
    if (existing) return existing;
    const p = new Promise<GltfTemplate>((resolve, reject) => {
      this.gltfLoader.load(
        url,
        (gltf: GLTF) => {
          resolve({ scene: gltf.scene, animations: gltf.animations });
        },
        undefined,
        reject,
      );
    });
    this.gltfCache.set(url, p);
    return p;
  }

  private normalizeCharacterScale(model: THREE.Object3D): void {
    const box = new THREE.Box3().setFromObject(model);
    const h = box.max.y - box.min.y;
    if (h > 1e-6) {
      const target = 1.65;
      model.scale.setScalar(target / h);
    } else {
      model.scale.setScalar(1);
    }
    model.traverse((c: THREE.Object3D) => {
      const m = c as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
      }
    });
  }

  private async attachCharacterModel(root: THREE.Group, spriteKey: string, name: string): Promise<void> {
    const url = glbPathForAgent(spriteKey, name);
    const tpl = await this.loadGltfTemplate(url);
    const model = cloneSkinned(tpl.scene);
    this.normalizeCharacterScale(model);
    root.add(model);
    root.userData.animations = tpl.animations;
  }

  private setupPlayerAnimations(root: THREE.Group): void {
    const anims = root.userData.animations as THREE.AnimationClip[];
    if (!anims?.length) return;
    this.playerMixer = new THREE.AnimationMixer(root);
    const wi = pickAnimationClip(anims, ['walk', 'run', 'jog']);
    const ii = pickAnimationClip(anims, ['idle', 'tpose', 'tp']);
    this.playerWalk = this.playerMixer.clipAction(anims[wi]);
    this.playerIdle = this.playerMixer.clipAction(anims[ii]);
    if (this.playerWalk === this.playerIdle && anims.length > 1) {
      this.playerIdle = this.playerMixer.clipAction(anims[(ii + 1) % anims.length]);
    }
    this.playerIdle?.play();
  }

  private setupAgentAnimations(root: THREE.Group): { mixer: THREE.AnimationMixer; walk: THREE.AnimationAction | null; idle: THREE.AnimationAction | null } {
    const anims = root.userData.animations as THREE.AnimationClip[];
    if (!anims?.length) {
      return { mixer: new THREE.AnimationMixer(root), walk: null, idle: null };
    }
    const mixer = new THREE.AnimationMixer(root);
    const wi = pickAnimationClip(anims, ['walk', 'run', 'jog']);
    const ii = pickAnimationClip(anims, ['idle', 'tpose', 'tp']);
    let walk = mixer.clipAction(anims[wi]);
    let idle = mixer.clipAction(anims[ii]);
    if (walk === idle && anims.length > 1) {
      idle = mixer.clipAction(anims[(ii + 1) % anims.length]);
    }
    idle.play();
    return { mixer, walk, idle };
  }

  private async createAgent(agent: AgentState): Promise<void> {
    const safe = this.grid.findNearestWalkable(agent.x, agent.y);
    const p = tileCenterToWorld(safe.x, safe.y, this.mapW, this.mapH, TILE_WORLD);

    const root = new THREE.Group();
    root.position.set(p.x, 0, p.z);
    root.userData.agentId = agent.id;
    this.scene.add(root);

    const spriteKey = agent.sprite_key || agent.name.replace(/ /g, '_');
    await this.attachCharacterModel(root, spriteKey, agent.name);

    const { mixer, walk, idle } = this.setupAgentAnimations(root);

    const wrap = document.createElement('div');
    wrap.className = 'agent-label';
    const mood = MOOD_EMOJI[agent.mood] ?? MOOD_EMOJI.neutral;
    wrap.innerHTML =
      `<div class="agent-mood">${mood}</div>` +
      `<div class="agent-name">${this.escapeHtml(agent.name)}</div>` +
      `<div class="agent-action">${this.escapeHtml(agent.current_action || '')}</div>`;

    const label = new CSS2DObject(wrap);
    label.position.set(0, 2.2, 0);
    root.add(label);

    const planText = (agent.daily_plan && agent.daily_plan[agent.current_plan_step]) || '';

    this.agentVisuals.set(agent.id, {
      root,
      mixer,
      walkAction: walk,
      idleAction: idle,
      label,
      targetX: p.x,
      targetZ: p.z,
      planStep: planText,
      mood: agent.mood ?? 'neutral',
    });
  }

  private escapeHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  private syncAgents(agents: AgentState[]): void {
    const seen = new Set<string>();
    for (const agent of agents) {
      seen.add(agent.id);
      let vis = this.agentVisuals.get(agent.id);
      if (!vis) {
        void this.createAgent(agent);
        continue;
      }
      const safe = this.grid.findNearestWalkable(agent.x, agent.y);
      const p = tileCenterToWorld(safe.x, safe.y, this.mapW, this.mapH, TILE_WORLD);
      vis.targetX = p.x;
      vis.targetZ = p.z;

      const el = vis.label.element as HTMLDivElement;
      const mood = MOOD_EMOJI[agent.mood] ?? MOOD_EMOJI.neutral;
      const moodEl = el.querySelector('.agent-mood');
      if (moodEl) moodEl.textContent = mood;
      const nameEl = el.querySelector('.agent-name');
      if (nameEl) nameEl.textContent = agent.name;
      const actEl = el.querySelector('.agent-action');
      if (actEl) actEl.textContent = agent.current_action || '';

      const dx = p.x - vis.root.position.x;
      const dz = p.z - vis.root.position.z;
      const moving = dx * dx + dz * dz > 0.002;
      if (vis.mixer && vis.walkAction && vis.idleAction) {
        if (moving) {
          vis.walkAction.paused = false;
          vis.walkAction.play();
          vis.idleAction.paused = true;
        } else {
          vis.walkAction.paused = true;
          vis.idleAction.paused = false;
          vis.idleAction.play();
        }
      }

      if (Math.abs(dx) > 1e-4 || Math.abs(dz) > 1e-4) {
        vis.root.lookAt(p.x, vis.root.position.y, p.z);
      }

      const planText = (agent.daily_plan && agent.daily_plan[agent.current_plan_step]) || '';
      if (planText && planText !== vis.planStep) {
        vis.planStep = planText;
      }
      vis.mood = agent.mood ?? 'neutral';
    }

    for (const id of this.agentVisuals.keys()) {
      if (!seen.has(id)) {
        const vis = this.agentVisuals.get(id)!;
        this.scene.remove(vis.root);
        this.agentVisuals.delete(id);
      }
    }
  }

  private tryAxisMove(fromX: number, fromZ: number, toX: number, toZ: number): { x: number; z: number } {
    const t1 = worldToTile(toX, fromZ, this.mapW, this.mapH, TILE_WORLD);
    if (!this.grid.isBlocked(t1.tx, t1.ty)) fromX = toX;
    const t2 = worldToTile(fromX, toZ, this.mapW, this.mapH, TILE_WORLD);
    if (!this.grid.isBlocked(t2.tx, t2.ty)) fromZ = toZ;
    return { x: fromX, z: fromZ };
  }

  private frame(): void {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    const typing =
      this.uiPanel.isInputFocused() ||
      document.activeElement instanceof HTMLInputElement ||
      document.activeElement instanceof HTMLTextAreaElement;

    if (!typing) {
      let vx = 0;
      let vz = 0;
      if (this.keysDown['ArrowLeft'] || this.keysDown['KeyA']) vx -= 1;
      if (this.keysDown['ArrowRight'] || this.keysDown['KeyD']) vx += 1;
      if (this.keysDown['ArrowUp'] || this.keysDown['KeyW']) vz -= 1;
      if (this.keysDown['ArrowDown'] || this.keysDown['KeyS']) vz += 1;
      if (vx !== 0 && vz !== 0) {
        vx *= 0.707;
        vz *= 0.707;
      }
      const sp = PLAYER_SPEED * dt;
      const next = this.tryAxisMove(this.playerX, this.playerZ, this.playerX + vx * sp, this.playerZ + vz * sp);
      this.playerX = next.x;
      this.playerZ = next.z;
      this.playerRoot.position.x = this.playerX;
      this.playerRoot.position.z = this.playerZ;
      if (Math.abs(vx) + Math.abs(vz) > 0.01) {
        this.playerRoot.lookAt(this.playerX + vx, this.playerRoot.position.y, this.playerZ + vz);
        this.followPlayer = true;
      }
      if (this.playerMixer && this.playerWalk && this.playerIdle) {
        const moving = Math.abs(vx) + Math.abs(vz) > 0.01;
        if (moving) {
          this.playerWalk.paused = false;
          this.playerWalk.play();
          this.playerIdle.paused = true;
        } else {
          this.playerWalk.paused = true;
          this.playerIdle.paused = false;
          this.playerIdle.play();
        }
      }
    }

    for (const vis of this.agentVisuals.values()) {
      const ax = vis.root.position.x;
      const az = vis.root.position.z;
      const lerp = 1 - Math.exp(-dt * 5);
      vis.root.position.x = ax + (vis.targetX - ax) * lerp;
      vis.root.position.z = az + (vis.targetZ - az) * lerp;
      vis.mixer?.update(dt);
    }

    this.playerMixer?.update(dt);

    const now = performance.now();
    if (this.panning) {
      const u = Math.min(1, (now - this.panT0) / this.panDur);
      const t = u * u * (3 - 2 * u);
      this.camera.position.lerpVectors(this.panCam0, this.panCam1, t);
      const lk = new THREE.Vector3().lerpVectors(this.panLook0, this.panLook1, t);
      this.camera.lookAt(lk);
      if (u >= 1) this.panning = false;
    } else if (this.followPlayer) {
      const tx = this.playerX;
      const tz = this.playerZ;
      const camX = tx + 6;
      const camZ = tz + this.cameraDistance;
      this.camera.position.x += (camX - this.camera.position.x) * (1 - Math.exp(-dt * 4));
      this.camera.position.z += (camZ - this.camera.position.z) * (1 - Math.exp(-dt * 4));
      this.camera.position.y += (12 - this.camera.position.y) * (1 - Math.exp(-dt * 3));
      this.camera.lookAt(tx, 0.5, tz);
    }

    this.selectionPulse += dt * 4;
    if (this.selectedAgentId && this.agentVisuals.has(this.selectedAgentId)) {
      const vis = this.agentVisuals.get(this.selectedAgentId)!;
      this.selectionRing.visible = true;
      this.selectionRing.position.set(vis.root.position.x, 0.03, vis.root.position.z);
      const mat = this.selectionRing.material as THREE.MeshBasicMaterial;
      mat.opacity = 0.45 + 0.25 * Math.sin(this.selectionPulse);
    } else {
      this.selectionRing.visible = false;
    }

    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
  }
}
