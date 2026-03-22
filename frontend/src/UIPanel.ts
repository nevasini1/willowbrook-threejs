import { ApiClient, AgentState, Relationship } from './ApiClient';

// MainScene type for camera focus — avoid circular import
interface SceneWithFocus {
    focusOnAgent(agentId: string): void;
}

const MOOD_COLORS: Record<string, string> = {
    happy: '#2ea043', sad: '#6e7681', angry: '#f85149',
    excited: '#d29922', anxious: '#a371f7', neutral: '#8b949e',
};

/**
 * UIPanel — DOM-based sidebar control panel for interacting with agents.
 */
export class UIPanel {
    private api: ApiClient;
    private scene: SceneWithFocus | null;
    private root: HTMLElement;
    private agents: AgentState[] = [];
    private selectedAgentId: string = '';

    // DOM refs
    private agentSelect!: HTMLSelectElement;
    private agentCardName!: HTMLDivElement;
    private agentCardDesc!: HTMLDivElement;
    private agentMoodBadge!: HTMLDivElement;
    private agentMoodDot!: HTMLSpanElement;
    private agentMoodLabel!: HTMLSpanElement;

    private chatInput!: HTMLInputElement;
    private chatLog!: HTMLDivElement;
    private innerVoiceInput!: HTMLInputElement;
    private innerVoiceResult!: HTMLDivElement;
    private tickResult!: HTMLDivElement;
    private autoTickStatus!: HTMLDivElement;
    private autoTickToggle!: HTMLButtonElement;
    private planResult!: HTMLDivElement;
    private relResult!: HTMLDivElement;
    private activityLog!: HTMLDivElement;

    // Brain Inspector DOM refs
    private brainPersona!: HTMLDivElement;
    private brainPlan!: HTMLDivElement;
    private brainMemories!: HTMLDivElement;

    // Relationship Web
    private relWebCanvas!: HTMLCanvasElement;

    // Auto-tick state
    private autoTickRunning: boolean = false;

    // Voice controls
    private voiceEnabled: boolean = true;
    private speakerToggle!: HTMLButtonElement;
    private micBtn!: HTMLButtonElement;
    private recognition: any = null;
    private audioCtx: AudioContext | null = null;
    private currentSource: AudioBufferSourceNode | null = null;
    private toggleCooldown: boolean = false;

    // Track all inputs for focus detection
    private allInputs: HTMLElement[] = [];

    // Cache for relationship data used by the web canvas
    private cachedRelationships: Relationship[] = [];

    constructor(api: ApiClient, scene?: SceneWithFocus) {
        this.api = api;
        this.scene = scene ?? null;
        this.root = document.getElementById('panel')!;
        this.build();
    }

    /** Returns true if any sidebar input is focused (so scene can skip WASD) */
    isInputFocused(): boolean {
        return this.allInputs.some(el => el === document.activeElement);
    }

    /** Update agent list from world state */
    setAgents(agents: AgentState[]): void {
        this.agents = agents;
        const prev = this.selectedAgentId;
        this.agentSelect.innerHTML = '';
        for (const a of agents) {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = a.name;
            this.agentSelect.appendChild(opt);
        }
        if (agents.find(a => a.id === prev)) {
            this.agentSelect.value = prev;
        } else if (agents.length > 0) {
            this.agentSelect.value = agents[0].id;
        }
        this.selectedAgentId = this.agentSelect.value;
        this.refreshAgentCard();
        this.refreshBrainPanel();
    }

    /** Called from MainScene when an agent sprite is clicked */
    selectAgentById(agentId: string): void {
        this.selectedAgentId = agentId;
        this.agentSelect.value = agentId;
        this.refreshAgentCard();
        this.refreshBrainPanel();
    }

    // ── Build DOM ──────────────────────────────────────────────────────

    private build(): void {
        this.root.innerHTML = '';

        // Header
        this.el('div', { className: 'panel-header', text: 'Willowbrook Control' }, this.root);

        // 1. Agent Card
        this.buildAgentCard();
        // 2. Controls (Chat + Simulation accordions)
        this.buildControls();
        // 3. Intel Panel (Brain / Plan / Social tabs)
        this.buildIntelPanel();
        // 4. World (Expand map)
        this.buildWorld();
        // 5. Activity Log
        this.buildActivityLog();
    }

    // ── 1. Agent Card ─────────────────────────────────────────────────

    private buildAgentCard(): void {
        const sec = this.section('Agent', 'sec-agent-card', '\u{1F9D9}');

        // Select + Focus row
        const selectRow = this.el('div', { className: 'agent-card-select-row' }, sec);
        this.agentSelect = document.createElement('select');
        this.agentSelect.style.flex = '1';
        this.agentSelect.addEventListener('change', () => {
            this.selectedAgentId = this.agentSelect.value;
            this.refreshAgentCard();
            this.refreshBrainPanel();
        });
        selectRow.appendChild(this.agentSelect);

        const focusBtn = this.el('button', { text: 'Focus' }, selectRow) as HTMLButtonElement;
        focusBtn.addEventListener('click', () => {
            if (this.scene && this.selectedAgentId) {
                this.scene.focusOnAgent(this.selectedAgentId);
            }
        });

        // Agent name (large)
        this.agentCardName = this.el('div', { className: 'agent-card-name' }, sec) as HTMLDivElement;

        // Mood badge
        this.agentMoodBadge = this.el('div', { className: 'agent-mood-badge mood-neutral' }, sec) as HTMLDivElement;
        this.agentMoodDot = document.createElement('span');
        this.agentMoodDot.className = 'mood-dot';
        this.agentMoodBadge.appendChild(this.agentMoodDot);
        this.agentMoodLabel = document.createElement('span');
        this.agentMoodLabel.textContent = 'Neutral';
        this.agentMoodBadge.appendChild(this.agentMoodLabel);

        // Description
        this.agentCardDesc = this.el('div', { className: 'agent-card-desc' }, sec) as HTMLDivElement;
    }

    // ── 2. Controls ───────────────────────────────────────────────────

    private buildControls(): void {
        const sec = this.section('Controls', 'sec-controls', '\u{1F3AE}');

        // Chat accordion (default open)
        const chat = this.accordion('\u{1F4AC} Chat', sec, true);

        // Chat log first (messages appear above input like a messenger)
        this.chatLog = this.el('div', { className: 'response-box chat-log' }, chat.body) as HTMLDivElement;

        // Unified input bar: [speaker] [mic] [input] [send]
        const inputBar = this.el('div', { className: 'chat-input-area' }, chat.body);

        // Voice controls inside the input bar
        const voiceRow = this.el('div', { className: 'voice-controls' }, inputBar);

        this.speakerToggle = this.el('button', { className: 'speaker-toggle active', text: '\uD83D\uDD0A' }, voiceRow) as HTMLButtonElement;
        this.speakerToggle.title = 'Auto-speak replies (ON)';
        this.speakerToggle.addEventListener('click', () => {
            if (this.toggleCooldown) return;
            this.toggleCooldown = true;
            setTimeout(() => { this.toggleCooldown = false; }, 400);
            this.voiceEnabled = !this.voiceEnabled;
            this.speakerToggle.classList.toggle('active', this.voiceEnabled);
            this.speakerToggle.title = this.voiceEnabled ? 'Auto-speak replies (ON)' : 'Auto-speak replies (OFF)';
            if (this.voiceEnabled) this.ensureAudioCtx();
            this.log('voice', this.voiceEnabled ? 'Speaker ON' : 'Speaker OFF');
        });

        const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.micBtn = this.el('button', { className: 'mic-btn', text: '\uD83C\uDFA4' }, voiceRow) as HTMLButtonElement;
            this.micBtn.title = 'Click to speak';
            this.micBtn.addEventListener('click', () => this.onMicToggle(SpeechRecognition));
        }

        // Text input
        this.chatInput = document.createElement('input');
        this.chatInput.type = 'text';
        this.chatInput.placeholder = 'Type a message...';
        this.chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.onChat();
        });
        inputBar.appendChild(this.chatInput);
        this.allInputs.push(this.chatInput);

        // Send button
        const sendBtn = this.el('button', { className: 'primary', text: 'Send' }, inputBar) as HTMLButtonElement;
        sendBtn.addEventListener('click', () => this.onChat());

        // Simulation accordion (default closed)
        const sim = this.accordion('\u{26A1} Simulation', sec, false);

        // Auto-tick controls
        const autoRow = this.el('div', { className: 'btn-row' }, sim.body);
        this.autoTickToggle = this.el('button', { text: 'Stop Auto-Tick' }, autoRow) as HTMLButtonElement;
        this.autoTickToggle.addEventListener('click', () => this.onToggleAutoTick());
        const tickOne = this.el('button', { text: 'Tick Once' }, autoRow) as HTMLButtonElement;
        tickOne.addEventListener('click', () => this.onTick(true));

        this.autoTickStatus = this.el('div', { className: 'response-box' }, sim.body) as HTMLDivElement;
        this.autoTickStatus.style.display = 'block';
        this.autoTickStatus.innerHTML = '<span style="color:#2ea043">Auto-tick active</span>';

        this.tickResult = this.el('div', { className: 'response-box' }, sim.body) as HTMLDivElement;

        // Fetch initial auto-tick status
        this.refreshAutoTickStatus();

        // Inner voice
        const innerVoiceRow = this.el('div', { className: 'input-row' }, sim.body);
        this.innerVoiceInput = document.createElement('input');
        this.innerVoiceInput.type = 'text';
        this.innerVoiceInput.placeholder = 'Inner voice command...';
        this.innerVoiceInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.onInnerVoice();
        });
        innerVoiceRow.appendChild(this.innerVoiceInput);
        this.allInputs.push(this.innerVoiceInput);

        const innerVoiceBtn = this.el('button', { text: 'Send' }, innerVoiceRow) as HTMLButtonElement;
        innerVoiceBtn.addEventListener('click', () => this.onInnerVoice());

        this.innerVoiceResult = this.el('div', { className: 'response-box' }, sim.body) as HTMLDivElement;
    }

    // ── 3. Intel Panel (tabs) ─────────────────────────────────────────

    private buildIntelPanel(): void {
        const sec = this.section('Intel', 'sec-intel', '\u{1F9E0}');

        // Tab bar
        const tabBar = this.el('div', { className: 'tab-bar' }, sec);
        const tabs = ['Brain', 'Plan', 'Social'];
        const tabContents: HTMLDivElement[] = [];

        for (let i = 0; i < tabs.length; i++) {
            const btn = this.el('button', { className: `tab-btn${i === 0 ? ' active' : ''}`, text: tabs[i] }, tabBar) as HTMLButtonElement;
            // Remove border/background overrides for tab buttons
            btn.style.background = 'transparent';
            btn.style.border = 'none';
            btn.style.borderBottom = i === 0 ? '2px solid #58a6ff' : '2px solid transparent';

            const content = this.el('div', { className: `tab-content${i === 0 ? ' active' : ''}` }, sec) as HTMLDivElement;
            tabContents.push(content);

            btn.addEventListener('click', () => {
                // Deactivate all
                tabBar.querySelectorAll('.tab-btn').forEach(b => {
                    b.classList.remove('active');
                    (b as HTMLElement).style.borderBottom = '2px solid transparent';
                });
                tabContents.forEach(c => c.classList.remove('active'));
                // Activate this one
                btn.classList.add('active');
                btn.style.borderBottom = '2px solid #58a6ff';
                content.classList.add('active');
            });
        }

        // Brain tab content
        const brainTab = tabContents[0];
        this.el('div', { className: 'brain-label', text: 'Persona' }, brainTab);
        this.brainPersona = this.el('div', { className: 'brain-persona' }, brainTab) as HTMLDivElement;

        this.el('div', { className: 'brain-label', text: 'Current Plan' }, brainTab);
        this.brainPlan = this.el('div', { className: 'brain-plan' }, brainTab) as HTMLDivElement;

        const brainBtnRow = this.el('div', { className: 'btn-row' }, brainTab);
        const loadBtn = this.el('button', { text: 'Load Memories' }, brainBtnRow) as HTMLButtonElement;
        loadBtn.addEventListener('click', () => this.onLoadMemories());
        const maintBtn = this.el('button', { text: 'Run Maintenance' }, brainBtnRow) as HTMLButtonElement;
        maintBtn.addEventListener('click', () => this.onRunMaintenance());

        this.brainMemories = this.el('div', { className: 'brain-memories' }, brainTab) as HTMLDivElement;
        this.brainMemories.style.display = 'none';

        // Plan tab content
        const planTab = tabContents[1];
        const planBtnRow = this.el('div', { className: 'btn-row' }, planTab);
        const viewPlanBtn = this.el('button', { text: 'View Plan' }, planBtnRow) as HTMLButtonElement;
        viewPlanBtn.addEventListener('click', () => this.onViewPlan());
        const regenBtn = this.el('button', { text: 'Regenerate' }, planBtnRow) as HTMLButtonElement;
        regenBtn.addEventListener('click', () => this.onRegeneratePlan());

        this.planResult = this.el('div', { className: 'response-box' }, planTab) as HTMLDivElement;

        // Social tab content
        const socialTab = tabContents[2];
        const socialBtnRow = this.el('div', { className: 'btn-row' }, socialTab);
        const viewRelBtn = this.el('button', { text: 'View Relationships' }, socialBtnRow) as HTMLButtonElement;
        viewRelBtn.addEventListener('click', () => this.onViewRelationships());
        const drawWebBtn = this.el('button', { text: 'Draw Web' }, socialBtnRow) as HTMLButtonElement;
        drawWebBtn.addEventListener('click', () => this.onDrawRelationshipWeb());

        this.relResult = this.el('div', { className: 'response-box' }, socialTab) as HTMLDivElement;

        this.relWebCanvas = document.createElement('canvas');
        this.relWebCanvas.width = 300;
        this.relWebCanvas.height = 220;
        this.relWebCanvas.style.width = '100%';
        this.relWebCanvas.style.marginTop = '8px';
        this.relWebCanvas.style.borderRadius = '6px';
        this.relWebCanvas.style.background = '#0d1117';
        this.relWebCanvas.style.display = 'none';
        socialTab.appendChild(this.relWebCanvas);
    }

    // ── 4. World ──────────────────────────────────────────────────────

    private buildWorld(): void {
        const sec = this.section('World', 'sec-world', '\u{1F5FA}');
        const grid = this.el('div', { className: 'dir-grid' }, sec);

        // Row 1: _ N _
        this.el('div', {}, grid);
        const n = this.el('button', { text: '\u2191 N' }, grid) as HTMLButtonElement;
        n.addEventListener('click', () => this.onExpand('north'));
        this.el('div', {}, grid);

        // Row 2: W _ E
        const w = this.el('button', { text: '\u2190 W' }, grid) as HTMLButtonElement;
        w.addEventListener('click', () => this.onExpand('west'));
        this.el('div', {}, grid);
        const e = this.el('button', { text: 'E \u2192' }, grid) as HTMLButtonElement;
        e.addEventListener('click', () => this.onExpand('east'));

        // Row 3: _ S _
        this.el('div', {}, grid);
        const s = this.el('button', { text: '\u2193 S' }, grid) as HTMLButtonElement;
        s.addEventListener('click', () => this.onExpand('south'));
        this.el('div', {}, grid);
    }

    // ── 5. Activity Log ───────────────────────────────────────────────

    private buildActivityLog(): void {
        const sec = this.section('Activity Log', 'sec-log', '\u{1F4DC}');
        this.activityLog = this.el('div', { className: 'activity-log' }, sec) as HTMLDivElement;
    }

    // ── Agent Card refresh ────────────────────────────────────────────

    private refreshAgentCard(): void {
        const agent = this.agents.find(a => a.id === this.selectedAgentId);
        if (!agent) return;

        // Name
        this.agentCardName.textContent = agent.name;

        // Mood badge
        const mood = agent.mood ?? 'neutral';
        const moodClass = `mood-${mood}`;
        this.agentMoodBadge.className = `agent-mood-badge ${moodClass}`;
        this.agentMoodLabel.textContent = mood.charAt(0).toUpperCase() + mood.slice(1);

        // Description
        this.agentCardDesc.textContent = agent.description || 'No description';
    }

    // ── Brain Inspector logic ───────────────────────────────────────────

    private refreshBrainPanel(): void {
        const agent = this.agents.find(a => a.id === this.selectedAgentId);
        if (!agent) return;

        // Persona
        this.brainPersona.textContent = agent.description || 'No description';

        // Current plan (inline, from cached agent state)
        if (agent.daily_plan && agent.daily_plan.length > 0) {
            let html = '';
            for (let i = 0; i < agent.daily_plan.length; i++) {
                const isCurrent = i === agent.current_plan_step;
                html += `<div class="plan-step${isCurrent ? ' current' : ''}">${i + 1}. ${this.escapeHtml(agent.daily_plan[i])}${isCurrent ? ' \u25C4' : ''}</div>`;
            }
            this.brainPlan.innerHTML = html;
        } else {
            this.brainPlan.innerHTML = '<span style="color:#8b949e">No plan</span>';
        }
    }

    private async onLoadMemories(): Promise<void> {
        if (!this.selectedAgentId) return;
        const agentName = this.getAgentName();
        this.brainMemories.style.display = 'block';
        this.brainMemories.innerHTML = '<span class="spinner"></span> Loading memories...';
        this.log('brain', `Loading memories for ${agentName}...`);

        try {
            const [planRes, relRes] = await Promise.all([
                this.api.getPlan(this.selectedAgentId),
                this.api.getRelationships(this.selectedAgentId),
            ]);

            let html = '';

            // Plan steps
            const plan: string[] = planRes.daily_plan ?? planRes.plan ?? planRes.steps ?? [];
            if (plan.length > 0) {
                html += '<div class="brain-label">Plan Steps</div>';
                for (let i = 0; i < plan.length; i++) {
                    html += `<div style="color:#c9d1d9">${i + 1}. ${this.escapeHtml(plan[i])}</div>`;
                }
            }

            // Shared social memories
            const rels: any[] = relRes.relationships ?? [];
            this.cachedRelationships = rels;
            if (rels.length > 0) {
                html += '<div class="brain-label" style="margin-top:8px">Social Memories</div>';
                for (const r of rels) {
                    const name = r.agent_b ?? r.target_name ?? r.target_id ?? 'Unknown';
                    const type = r.relation_type ?? r.relationship_type ?? r.type ?? '';
                    html += `<div style="color:#58a6ff;font-weight:600">${this.escapeHtml(String(name))} <span style="color:#8b949e;font-weight:400">(${this.escapeHtml(String(type))})</span></div>`;
                    const shared = r.shared_memories ?? [];
                    if (shared.length > 0) {
                        for (const mem of shared) {
                            html += `<div style="color:#8b949e;margin-left:8px">- ${this.escapeHtml(String(mem))}</div>`;
                        }
                    }
                }
            }

            this.brainMemories.innerHTML = html || '<span style="color:#8b949e">No memories found</span>';
            this.log('brain', `Memories loaded for ${agentName}`);
        } catch (e: any) {
            this.brainMemories.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    private async onRunMaintenance(): Promise<void> {
        if (!this.selectedAgentId) return;
        const agentName = this.getAgentName();
        this.brainMemories.style.display = 'block';
        this.brainMemories.innerHTML = '<span class="spinner"></span> Running maintenance...';
        this.log('brain', `Running memory maintenance for ${agentName}...`);

        try {
            const res = await this.api.runMemoryMaintenance(this.selectedAgentId);
            const pruned = res.pruned ?? res.pruned_count ?? 0;
            const consolidated = res.consolidated ?? res.consolidated_count ?? 0;
            this.brainMemories.innerHTML =
                `<div style="color:#2ea043">Maintenance complete</div>` +
                `<div style="color:#c9d1d9">Pruned: ${pruned} | Consolidated: ${consolidated}</div>`;
            this.log('brain', `Maintenance done — pruned: ${pruned}, consolidated: ${consolidated}`);
        } catch (e: any) {
            this.brainMemories.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    // ── Relationship Web ────────────────────────────────────────────────

    private async onDrawRelationshipWeb(): Promise<void> {
        if (!this.selectedAgentId) return;
        this.relWebCanvas.style.display = 'block';
        this.log('social', 'Drawing relationship web...');

        try {
            const res = await this.api.getRelationships(this.selectedAgentId);
            const rels: Relationship[] = res.relationships ?? [];
            this.cachedRelationships = rels;
            this.drawRelWeb(rels);
        } catch (e: any) {
            this.log('error', `Relationship web: ${e.message}`);
        }
    }

    private drawRelWeb(rels: Relationship[]): void {
        const canvas = this.relWebCanvas;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const W = canvas.width;
        const H = canvas.height;
        ctx.clearRect(0, 0, W, H);

        // Collect unique agent names from relationships
        const nameSet = new Set<string>();
        nameSet.add(this.getAgentName());
        for (const r of rels) {
            const other = r.agent_b ?? (r as any).target_name ?? (r as any).target_id ?? '';
            if (other) nameSet.add(String(other));
        }
        const names = Array.from(nameSet);
        if (names.length === 0) return;

        // Circular layout
        const cx = W / 2;
        const cy = H / 2 - 5;
        const radius = Math.min(W, H) / 2 - 30;
        const positions: Record<string, { x: number; y: number }> = {};
        for (let i = 0; i < names.length; i++) {
            const angle = (2 * Math.PI * i) / names.length - Math.PI / 2;
            positions[names[i]] = {
                x: cx + radius * Math.cos(angle),
                y: cy + radius * Math.sin(angle),
            };
        }

        // Edge colors by type
        const typeColor: Record<string, string> = {
            close_friend: '#2ea043', friend: '#58a6ff',
            acquaintance: '#6e7681', rival: '#d29922', enemy: '#f85149',
        };

        // Draw edges
        for (const r of rels) {
            const selfName = this.getAgentName();
            const otherName = String(r.agent_b ?? (r as any).target_name ?? (r as any).target_id ?? '');
            const from = positions[selfName];
            const to = positions[otherName];
            if (!from || !to) continue;

            const rType = r.relation_type ?? (r as any).relationship_type ?? (r as any).type ?? 'acquaintance';
            ctx.strokeStyle = typeColor[rType] ?? '#6e7681';
            ctx.lineWidth = Math.max(1, Math.abs(r.strength ?? 0) * 3);
            ctx.beginPath();
            ctx.moveTo(from.x, from.y);
            ctx.lineTo(to.x, to.y);
            ctx.stroke();
        }

        // Draw nodes
        const selectedName = this.getAgentName();
        for (const name of names) {
            const pos = positions[name];
            const isSelected = name === selectedName;

            ctx.beginPath();
            ctx.arc(pos.x, pos.y, isSelected ? 8 : 5, 0, Math.PI * 2);
            ctx.fillStyle = isSelected ? '#58a6ff' : '#c9d1d9';
            ctx.fill();

            // Label (first name only)
            const firstName = name.split(' ')[0];
            ctx.fillStyle = '#8b949e';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(firstName, pos.x, pos.y + (isSelected ? 18 : 15));
        }
    }

    // ── Auto-tick logic ───────────────────────────────────────────────

    private async refreshAutoTickStatus(): Promise<void> {
        try {
            const status = await this.api.getAutoTickStatus();
            this.autoTickRunning = status.running;
            this.autoTickToggle.textContent = status.running ? 'Stop Auto-Tick' : 'Start Auto-Tick';
            if (status.running) {
                this.autoTickStatus.innerHTML =
                    `<span style="color:#2ea043">Auto-tick active</span>` +
                    `<span style="color:#8b949e"> \u00B7 ${status.interval_seconds}s interval \u00B7 ${status.tick_count} ticks</span>`;
            } else {
                this.autoTickStatus.innerHTML = '<span style="color:#8b949e">Auto-tick stopped</span>';
            }
            this.autoTickStatus.style.display = 'block';
        } catch {
            this.autoTickStatus.innerHTML = '<span style="color:#8b949e">Auto-tick: backend offline</span>';
            this.autoTickStatus.style.display = 'block';
        }
    }

    private async onToggleAutoTick(): Promise<void> {
        try {
            if (this.autoTickRunning) {
                await this.api.stopAutoTick();
                this.log('tick', 'Auto-tick stopped');
            } else {
                await this.api.startAutoTick(30);
                this.log('tick', 'Auto-tick started (30s interval)');
            }
            await this.refreshAutoTickStatus();
        } catch (e: any) {
            this.log('error', `Auto-tick toggle: ${e.message}`);
        }
    }

    // ── Voice methods ──────────────────────────────────────────────────

    private onMicToggle(SpeechRecognitionCtor: any): void {
        if (this.recognition) {
            // Stop recording
            this.recognition.stop();
            return;
        }

        this.recognition = new SpeechRecognitionCtor();
        this.recognition.lang = 'en-US';
        this.recognition.interimResults = false;
        this.recognition.maxAlternatives = 1;

        this.micBtn.classList.add('recording');
        this.log('voice', 'Listening...');

        this.recognition.onresult = (event: any) => {
            const transcript: string = event.results[0][0].transcript;
            this.chatInput.value = transcript;
            this.log('voice', `Heard: "${transcript}"`);
            // Auto-send the transcribed message
            this.onChat();
        };

        this.recognition.onerror = (event: any) => {
            this.log('error', `Speech recognition: ${event.error}`);
        };

        this.recognition.onend = () => {
            this.micBtn.classList.remove('recording');
            this.recognition = null;
        };

        this.recognition.start();
    }

    // Per-agent browser voice settings (pitch, rate) to differentiate voices
    private static AGENT_VOICE_PARAMS: Record<string, { pitch: number; rate: number; preferFemale: boolean }> = {
        agent_sam: { pitch: 0.9, rate: 1.0, preferFemale: false },
        agent_maya: { pitch: 1.2, rate: 0.95, preferFemale: true },
        agent_isabella: { pitch: 1.1, rate: 0.9, preferFemale: true },
        agent_klaus: { pitch: 0.7, rate: 0.95, preferFemale: false },
        agent_tom: { pitch: 0.8, rate: 1.05, preferFemale: false },
        agent_mei: { pitch: 1.3, rate: 1.0, preferFemale: true },
        agent_latoya: { pitch: 1.15, rate: 1.0, preferFemale: true },
    };

    /** Instant browser-native TTS — zero latency */
    private speakFast(agentId: string, text: string): void {
        if (!window.speechSynthesis) return;
        window.speechSynthesis.cancel(); // stop any current speech
        const utter = new SpeechSynthesisUtterance(text);
        const params = UIPanel.AGENT_VOICE_PARAMS[agentId] ?? { pitch: 1.0, rate: 1.0, preferFemale: false };
        utter.pitch = params.pitch;
        utter.rate = params.rate;

        // Try to pick a voice matching gender preference
        const voices = window.speechSynthesis.getVoices();
        if (voices.length > 0) {
            const preferred = voices.find(v =>
                v.lang.startsWith('en') &&
                (params.preferFemale ? /female|samantha|karen|victoria|fiona/i.test(v.name) : /male|daniel|alex|thomas|james/i.test(v.name))
            ) ?? voices.find(v => v.lang.startsWith('en')) ?? voices[0];
            utter.voice = preferred;
        }
        window.speechSynthesis.speak(utter);
    }

    /** Ensure AudioContext is created (must happen during a user gesture) */
    private ensureAudioCtx(): AudioContext {
        if (!this.audioCtx) {
            this.audioCtx = new AudioContext();
        }
        if (this.audioCtx.state === 'suspended') {
            this.audioCtx.resume();
        }
        return this.audioCtx;
    }

    /** HD Gemini TTS — higher quality but requires network round-trip */
    private async playGeminiTTS(agentId: string, text: string): Promise<void> {
        try {
            this.log('voice', 'Generating HD voice...');
            const blob = await this.api.ttsAudio(agentId, text);
            const arrayBuf = await blob.arrayBuffer();

            const ctx = this.ensureAudioCtx();
            const audioBuf = await ctx.decodeAudioData(arrayBuf);

            // Stop any currently playing audio
            if (this.currentSource) {
                try { this.currentSource.stop(); } catch { /* already stopped */ }
                this.currentSource = null;
            }
            window.speechSynthesis?.cancel(); // stop fast TTS if still playing

            const source = ctx.createBufferSource();
            source.buffer = audioBuf;
            source.connect(ctx.destination);
            source.onended = () => { this.currentSource = null; };
            this.currentSource = source;
            source.start();
            this.log('voice', 'Playing HD voice');
        } catch (e: any) {
            this.log('error', `TTS: ${e.message}`);
        }
    }

    // ── Event handlers ─────────────────────────────────────────────────

    private async onChat(): Promise<void> {
        const msg = this.chatInput.value.trim();
        if (!msg || !this.selectedAgentId) return;
        this.chatInput.value = '';

        // Auto-focus camera on the agent you're chatting with
        if (this.scene) {
            this.scene.focusOnAgent(this.selectedAgentId);
        }

        const agentName = this.getAgentName();
        this.appendChat(`You: ${msg}`, 'user');
        this.log('chat', `Sending to ${agentName}...`);

        try {
            const res = await this.api.chat(this.selectedAgentId, msg);
            this.appendChat(`${agentName}: ${res.reply}`, 'agent', this.selectedAgentId, res.reply);
            this.log('chat', `${agentName} replied`);
            // Auto-speak reply instantly using browser TTS
            if (this.voiceEnabled && res.reply) {
                this.speakFast(this.selectedAgentId, res.reply);
            }
        } catch (e: any) {
            this.appendChat(`Error: ${e.message}`, 'error');
            this.log('error', e.message);
        }
    }

    private async onInnerVoice(): Promise<void> {
        const cmd = this.innerVoiceInput.value.trim();
        if (!cmd || !this.selectedAgentId) return;
        this.innerVoiceInput.value = '';

        const agentName = this.getAgentName();
        this.log('inner-voice', `Command to ${agentName}: ${cmd}`);

        try {
            const res = await this.api.innerVoice(this.selectedAgentId, cmd);
            this.innerVoiceResult.textContent = res.result;
            this.log('inner-voice', `${agentName}: ${res.result.slice(0, 60)}...`);
        } catch (e: any) {
            this.innerVoiceResult.textContent = `Error: ${e.message}`;
            this.log('error', e.message);
        }
    }

    private async onTick(all: boolean): Promise<void> {
        const agentName = all ? 'all agents' : this.getAgentName();
        this.log('tick', `Ticking ${agentName}...`);
        this.tickResult.innerHTML = '<span class="spinner"></span> Ticking...';

        try {
            const res = await this.api.tick(all ? undefined : this.selectedAgentId);
            let html = '';
            for (const r of res.results) {
                const name = this.agents.find(a => a.id === r.agent_id)?.name ?? r.agent_id;
                const icon = r.success ? '\u2713' : '\u2717';
                html += `<div><strong>${icon} ${name}</strong>: ${r.action}</div>`;
                if (r.detail) html += `<div style="color:#8b949e;margin-left:12px">${r.detail}</div>`;
            }
            this.tickResult.innerHTML = html || 'No results';
            this.log('tick', `Completed \u2014 ${res.results.length} result(s)`);
            this.refreshAutoTickStatus();
        } catch (e: any) {
            this.tickResult.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    private async onViewPlan(): Promise<void> {
        if (!this.selectedAgentId) return;
        const agentName = this.getAgentName();
        this.log('plan', `Fetching plan for ${agentName}...`);
        this.planResult.innerHTML = '<span class="spinner"></span> Loading...';

        try {
            const res = await this.api.getPlan(this.selectedAgentId);
            this.renderPlan(res);
            this.log('plan', `Plan loaded for ${agentName}`);
        } catch (e: any) {
            this.planResult.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    private async onRegeneratePlan(): Promise<void> {
        if (!this.selectedAgentId) return;
        const agentName = this.getAgentName();
        this.log('plan', `Regenerating plan for ${agentName}...`);
        this.planResult.innerHTML = '<span class="spinner"></span> Regenerating...';

        try {
            const res = await this.api.regeneratePlan(this.selectedAgentId);
            this.renderPlan(res);
            this.log('plan', `Plan regenerated for ${agentName}`);
        } catch (e: any) {
            this.planResult.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    private async onViewRelationships(): Promise<void> {
        if (!this.selectedAgentId) return;
        const agentName = this.getAgentName();
        this.log('social', `Fetching relationships for ${agentName}...`);
        this.relResult.innerHTML = '<span class="spinner"></span> Loading...';

        try {
            const res = await this.api.getRelationships(this.selectedAgentId);
            if (!res.relationships || res.relationships.length === 0) {
                this.relResult.innerHTML = '<span style="color:#8b949e">No relationships yet</span>';
            } else {
                let html = '';
                for (const r of res.relationships) {
                    html += `<div class="rel-card">`;
                    html += `<span class="rel-name">${(r as any).target_name ?? (r as any).target_id ?? r.agent_b ?? 'Unknown'}</span> `;
                    html += `<span class="rel-type">${r.relation_type ?? (r as any).relationship_type ?? (r as any).type ?? ''}</span>`;
                    if (r.strength != null) html += `<span class="rel-type"> \u00B7 strength: ${r.strength}</span>`;
                    if ((r as any).description) html += `<div style="color:#8b949e;margin-top:2px">${(r as any).description}</div>`;
                    html += `</div>`;
                }
                this.relResult.innerHTML = html;
            }
            this.cachedRelationships = res.relationships ?? [];
            this.log('social', `Loaded ${res.relationships?.length ?? 0} relationships`);
        } catch (e: any) {
            this.relResult.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`;
            this.log('error', e.message);
        }
    }

    private async onExpand(direction: string): Promise<void> {
        this.log('expand', `Expanding ${direction}...`);
        try {
            const res = await this.api.expandWorld(direction, 0, 0);
            if (res.success) {
                this.log('expand', `Expanded ${direction} \u2014 new zone added`);
            } else {
                this.log('expand', `Expansion ${direction} \u2014 ${res.detail ?? 'no change'}`);
            }
        } catch (e: any) {
            this.log('error', `Expand ${direction}: ${e.message}`);
        }
    }

    // ── Render helpers ─────────────────────────────────────────────────

    private renderPlan(data: any): void {
        const plan: string[] = data.daily_plan ?? data.plan ?? data.steps ?? [];
        const currentStep: number = data.current_plan_step ?? data.current_step ?? -1;

        if (!plan || plan.length === 0) {
            this.planResult.innerHTML = '<span style="color:#8b949e">No plan available</span>';
            return;
        }

        let html = '';
        for (let i = 0; i < plan.length; i++) {
            const isCurrent = i === currentStep;
            html += `<div class="plan-step${isCurrent ? ' current' : ''}">${i + 1}. ${plan[i]}${isCurrent ? ' \u25C4' : ''}</div>`;
        }
        this.planResult.innerHTML = html;
    }

    private appendChat(text: string, type: 'user' | 'agent' | 'error', agentId?: string, replyText?: string): void {
        const agentName = type === 'agent' ? this.getAgentName() : '';

        // Message row
        const row = document.createElement('div');
        row.className = `chat-msg ${type}`;

        // Avatar
        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        if (type === 'user') {
            avatar.textContent = 'You';
        } else if (type === 'agent') {
            avatar.textContent = agentName.split(' ').map(w => w[0]).join('').slice(0, 2);
        } else {
            avatar.textContent = '!';
            avatar.style.background = '#f85149';
        }
        row.appendChild(avatar);

        // Content column (sender label + bubble + actions)
        const content = document.createElement('div');
        content.className = 'chat-content';

        // Sender label
        const sender = document.createElement('div');
        sender.className = 'chat-sender';
        sender.textContent = type === 'user' ? 'You' : type === 'agent' ? agentName : 'Error';
        content.appendChild(sender);

        // Bubble with just the message text
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        // Strip the "You: " or "AgentName: " prefix since we show it in the label
        const colonIdx = text.indexOf(': ');
        bubble.textContent = colonIdx > 0 ? text.substring(colonIdx + 2) : text;
        content.appendChild(bubble);

        // Action row for agent replies (play button)
        if (type === 'agent' && agentId && replyText) {
            const actions = document.createElement('div');
            actions.className = 'chat-actions';

            const playBtn = document.createElement('button');
            playBtn.className = 'chat-play-btn';
            playBtn.textContent = '\uD83D\uDD0A';
            playBtn.title = 'Play HD voice';
            playBtn.addEventListener('click', () => {
                this.ensureAudioCtx();
                this.playGeminiTTS(agentId, replyText);
            });
            actions.appendChild(playBtn);
            content.appendChild(actions);
        }

        row.appendChild(content);
        this.chatLog.appendChild(row);
        this.chatLog.style.display = 'flex';
        this.chatLog.scrollTop = this.chatLog.scrollHeight;
    }

    private log(action: string, message: string): void {
        const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        const isError = action === 'error';
        entry.innerHTML = `<span class="log-time">${time}</span> <span class="${isError ? 'log-error' : 'log-action'}">[${action}]</span> <span class="${isError ? 'log-error' : 'log-result'}">${this.escapeHtml(message)}</span>`;
        this.activityLog.appendChild(entry);
        this.activityLog.scrollTop = this.activityLog.scrollHeight;
    }

    private getAgentName(): string {
        return this.agents.find(a => a.id === this.selectedAgentId)?.name ?? this.selectedAgentId;
    }

    // ── DOM utilities ──────────────────────────────────────────────────

    private section(title: string, cssClass?: string, icon?: string): HTMLDivElement {
        const sec = document.createElement('div');
        sec.className = 'section' + (cssClass ? ` ${cssClass}` : '');
        const h = document.createElement('div');
        h.className = 'section-title';
        if (icon) {
            const iconSpan = document.createElement('span');
            iconSpan.className = 'icon';
            iconSpan.textContent = icon;
            h.appendChild(iconSpan);
        }
        const textNode = document.createTextNode(title);
        h.appendChild(textNode);
        sec.appendChild(h);
        this.root.appendChild(sec);
        return sec;
    }

    private accordion(label: string, parent: HTMLElement, startOpen: boolean): { header: HTMLDivElement; body: HTMLDivElement } {
        const header = document.createElement('div');
        header.className = 'accordion-header' + (startOpen ? ' open' : '');

        const labelEl = document.createElement('span');
        labelEl.className = 'acc-label';
        labelEl.textContent = label;
        header.appendChild(labelEl);

        const arrow = document.createElement('span');
        arrow.className = 'acc-arrow';
        arrow.textContent = '\u25B6';
        header.appendChild(arrow);

        parent.appendChild(header);

        const body = document.createElement('div');
        body.className = 'accordion-body' + (startOpen ? ' open' : '');
        parent.appendChild(body);

        header.addEventListener('click', () => {
            const isOpen = header.classList.toggle('open');
            body.classList.toggle('open', isOpen);
        });

        return { header, body };
    }

    private el(tag: string, opts: { className?: string; text?: string }, parent: HTMLElement): HTMLElement {
        const el = document.createElement(tag);
        if (opts.className) el.className = opts.className;
        if (opts.text) el.textContent = opts.text;
        parent.appendChild(el);
        return el;
    }

    private escapeHtml(s: string): string {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}
