/**
 * ApiClient — REST + WebSocket client for the backend.
 */

export interface EnvironmentNode {
    id: string;
    name: string;
    description: string;
    node_type: string;
    tile_key: string | null;
    x: number;
    y: number;
    w: number;
    h: number;
    walkable: boolean;
    children: EnvironmentNode[];
}

export interface AgentState {
    id: string;
    name: string;
    location_id: string;
    current_action: string;
    x: number;
    y: number;
    sprite_key: string;
    description: string;
    daily_plan: string[] | null;
    current_plan_step: number;
    day_number: number;
    mood: string;
}

export interface Relationship {
    agent_a: string;
    agent_b: string;
    relation_type: string;
    strength: number;
    sentiment_history: number[];
    interaction_count: number;
    shared_memories: string[];
}

export interface WorldState {
    environment_root: EnvironmentNode;
    agents: AgentState[];
    expansion_count: number;
}

export interface AssetEntry {
    sprite: string;
    category: string;
    walkable?: boolean;
    description?: string;
    interactable?: boolean;
    w?: number;
    h?: number;
}

export interface AssetRegistry {
    _meta: { tile_size: number; render_scale: number; description: string };
    [category: string]: { [key: string]: AssetEntry } | any;
}

export type StateUpdateCallback = (state: WorldState) => void;

export class ApiClient {
    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private stateCallbacks: StateUpdateCallback[] = [];

    private async jsonOrThrow(res: Response): Promise<any> {
        const text = await res.text();
        if (!res.ok) {
            throw new Error(text || `HTTP ${res.status}`);
        }
        try {
            return JSON.parse(text);
        } catch {
            throw new Error(text || `Unexpected non-JSON response (${res.status})`);
        }
    }

    async fetchState(): Promise<WorldState> {
        const res = await fetch('/state');
        return this.jsonOrThrow(res);
    }

    async fetchAssets(): Promise<AssetRegistry> {
        const res = await fetch('/api/assets');
        return this.jsonOrThrow(res);
    }

    async expandWorld(direction: string, x: number, y: number): Promise<any> {
        const res = await fetch('/world/expand', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ direction, trigger_x: x, trigger_y: y }),
        });
        return this.jsonOrThrow(res);
    }

    onStateUpdate(callback: StateUpdateCallback): void {
        this.stateCallbacks.push(callback);
    }

    connectWebSocket(): void {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.action === 'state_update' && data.state) {
                        for (const cb of this.stateCallbacks) {
                            cb(data.state);
                        }
                    }
                } catch (e) {
                    console.warn('Failed to parse WS message:', e);
                }
            };

            this.ws.onerror = (error) => {
                console.warn('WebSocket error:', error);
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected, reconnecting in 3s...');
                this.scheduleReconnect();
            };
        } catch (e) {
            console.error('Failed to connect WebSocket:', e);
            this.scheduleReconnect();
        }
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connectWebSocket();
        }, 3000);
    }

    // ── Agent REST endpoints ──────────────────────────────────────────

    async chat(agentId: string, message: string): Promise<{ agent_id: string; reply: string }> {
        const res = await fetch('/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: agentId, message }),
        });
        return this.jsonOrThrow(res);
    }

    async innerVoice(agentId: string, command: string): Promise<{ agent_id: string; result: string }> {
        const res = await fetch('/agent/inner-voice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: agentId, command }),
        });
        return this.jsonOrThrow(res);
    }

    async tick(agentId?: string): Promise<{ results: { agent_id: string; action: string; success: boolean; detail: string }[] }> {
        const res = await fetch('/agent/tick', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: agentId ?? null }),
        });
        return this.jsonOrThrow(res);
    }

    async getPlan(agentId: string): Promise<any> {
        const res = await fetch(`/agent/${agentId}/plan`);
        return this.jsonOrThrow(res);
    }

    async regeneratePlan(agentId: string): Promise<any> {
        const res = await fetch(`/agent/${agentId}/plan/regenerate`, { method: 'POST' });
        return this.jsonOrThrow(res);
    }

    async getRelationships(agentId: string): Promise<{ agent_id: string; relationships: Relationship[] }> {
        const res = await fetch(`/agent/${agentId}/relationships`);
        return this.jsonOrThrow(res);
    }

    async getMood(agentId: string): Promise<{ agent_id: string; mood: string }> {
        const res = await fetch(`/agent/${agentId}/mood`);
        return this.jsonOrThrow(res);
    }

    async ttsAudio(agentId: string, text: string): Promise<Blob> {
        const res = await fetch('/agent/voice/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: agentId, text }),
        });
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(errText || `TTS HTTP ${res.status}`);
        }
        return res.blob();
    }

    async runMemoryMaintenance(agentId: string): Promise<any> {
        const res = await fetch(`/agent/${agentId}/memory/maintenance`, { method: 'POST' });
        return this.jsonOrThrow(res);
    }

    // ── Auto-tick endpoints ─────────────────────────────────────────

    async startAutoTick(intervalSeconds?: number): Promise<any> {
        const res = await fetch('/auto-tick/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval_seconds: intervalSeconds ?? 30 }),
        });
        return this.jsonOrThrow(res);
    }

    async stopAutoTick(): Promise<any> {
        const res = await fetch('/auto-tick/stop', { method: 'POST' });
        return this.jsonOrThrow(res);
    }

    async getAutoTickStatus(): Promise<{ running: boolean; interval_seconds: number; tick_count: number }> {
        const res = await fetch('/auto-tick/status');
        return this.jsonOrThrow(res);
    }

    sendWs(data: Record<string, any>): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }
}
