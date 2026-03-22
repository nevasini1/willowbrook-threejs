# Willowbrook — Generative AI World Simulation

A living, breathing pixel-art town where AI agents autonomously plan their days, form relationships, hold conversations, and evolve over time. Powered by Gemini 2.5 Flash for reasoning, memory, and voice.

![Willowbrook Screenshot](docs/screenshot.png)

## What is Willowbrook?

Willowbrook is a generative AI simulation where autonomous agents inhabit a pixel-art town. Each agent possesses persistent memory, emotional states, social relationships, and daily plans — forming opinions, forging friendships, and evolving over time. Players observe and intervene: chat with residents using natural voice (speech-to-text input, per-character TTS output with mood-inflected delivery), whisper inner-voice commands, or simply watch emergent narratives unfold. A reflection engine synthesizes experiences into higher-order insights, while a social graph tracks relationship dynamics across every interaction. Part sandbox, part social experiment — Willowbrook asks: what happens when AI characters truly remember?

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Game Engine** | Phaser 3 (TypeScript) — tilemap rendering, sprites, camera |
| **Backend** | FastAPI + Uvicorn (Python) — REST, WebSocket |
| **LLM** | Gemini 2.5 Flash — agent reasoning, planning, conversation |
| **Voice** | Gemini 2.5 Flash TTS — per-character voices with mood-inflected delivery |
| **Embeddings** | Gemini Embedding 001 — semantic memory vectors |
| **Agent Framework** | Agno — agent lifecycle, tool use, multi-agent team coordination |
| **Memory / RAG** | LlamaIndex — per-agent vector indices, similarity retrieval |
| **Social Graph** | Neo4j (optional, JSON fallback) — relationship tracking and decay |
| **Orchestration** | Temporal (optional) — durable workflow orchestration |
| **Observability** | Langfuse (optional) — LLM tracing |
| **Dev Server** | Vite — HMR, proxy |
| **Map Editor** | Tiled — 140x100 tilemap with collision and spawning layers |

## Features

- **Autonomous Agents** — Each agent plans their day, moves through the world, interacts with objects, and converses with other agents without human intervention
- **Persistent Memory** — Every experience is embedded and stored via LlamaIndex; agents recall relevant memories using semantic similarity search (RAG)
- **Reflection Engine** — When accumulated experience crosses an importance threshold, agents synthesize higher-order insights from concrete memories
- **Social Graph** — Tracks relationship type, strength, sentiment history, and shared memories between all agent pairs; relationships decay without interaction
- **Mood System** — Agent mood shifts based on conversation sentiment and social context; mood influences behavior, planning, and voice tone
- **Voice Chat** — Speak to agents via browser Speech Recognition; hear replies instantly via browser TTS or in high-definition Gemini voice
- **Per-Character Voices** — Each agent has a unique Gemini TTS voice (Charon, Kore, Aoede, etc.) with mood-based style prompts
- **Daily Planning** — Agents generate multi-step plans informed by personality, mood, reflections, and relationships
- **Agent-to-Agent Conversation** — Agents exchange messages during tick cycles; conversations resolve naturally across tick rounds
- **Interactive World** — Click agents to select, chat via sidebar, send inner-voice commands, trigger ticks, expand the map procedurally

## Project Structure

```
gemini-hackathon/
├── backend/
│   ├── main.py                    # FastAPI app, endpoints, WebSocket, auto-tick
│   ├── core/config.py             # Settings (API keys, intervals)
│   ├── models/
│   │   ├── state.py               # WorldState, AgentState, EnvironmentNode
│   │   └── api_models.py          # Request/response schemas
│   ├── services/
│   │   ├── agent_manager.py       # Agent orchestrator (chat, tick, planning, mood)
│   │   ├── voice_service.py       # Gemini TTS wrapper with per-agent voices
│   │   ├── memory_store.py        # LlamaIndex vector memory
│   │   ├── reflection.py          # Importance-weighted reflection engine
│   │   ├── social_graph.py        # Neo4j/JSON relationship tracking
│   │   ├── planner.py             # Daily plan generation
│   │   ├── world_tools.py         # Agent tools (move, interact, talk)
│   │   └── map_generator.py       # Procedural world expansion
│   └── data/
│       ├── seed_world.json        # World definition, rooms, objects, agents
│       └── asset_registry.json    # Tile-to-sprite mapping
├── frontend/
│   ├── src/
│   │   ├── scenes/MainScene.ts    # Phaser scene, tilemap, sprites, camera
│   │   ├── ApiClient.ts           # REST + WebSocket client
│   │   ├── UIPanel.ts             # Sidebar UI, chat, voice, controls
│   │   └── WorldRenderer.ts       # Tilemap rendering, collision detection
│   ├── public/assets/             # Tiled map, sprite sheets, tilesets
│   ├── index.html                 # Entry point + CSS
│   └── vite.config.ts             # Dev server, proxy config
└── docs/
    └── screenshot.png
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- A [Gemini API key](https://ai.google.dev/)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set your API key
export GEMINI_API_KEY=your_key_here

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5174` in your browser.

## How It Works

1. **Startup** — Backend loads the world from `seed_world.json`, validates agent spawn positions against room bounds, initializes LlamaIndex memory indices, and creates Agno agents
2. **Auto-Tick Loop** — Every 30 seconds, each agent receives a contextual prompt with their plan, mood, nearby events, incoming messages, and relevant memories, then decides an action
3. **User Chat** — When you type a message, it's sent to the selected agent with full memory/social context; the reply is spoken aloud via browser TTS
4. **Memory** — Every interaction is embedded and indexed; retrieval surfaces the most relevant memories for each new situation
5. **Reflection** — When accumulated importance crosses a threshold, the agent generates abstract insights from recent concrete memories
6. **Social Updates** — Each interaction updates relationship strength, sentiment, and shared memories; relationship context influences future behavior

## License

MIT
