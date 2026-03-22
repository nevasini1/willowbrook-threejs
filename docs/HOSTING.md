# Hosting for real users

Visitors **do not** create API keys or edit `.env`. They open your site; the **browser talks only to your backend**. You (the operator) put **one** `GEMINI_API_KEY` on the server and pay for usage (or cap it with quotas / rate limits on your side).

## What runs where

| Piece | Role | Secrets |
|-------|------|---------|
| **Static frontend** (`frontend/dist/`) | Three.js UI, maps, GLB models | None |
| **Python API** (FastAPI) | Agents, chat, memory, Gemini calls | `GEMINI_API_KEY` and optional DB keys |

Map files and models load from the **same origin as the page** (paths like `/assets/...`). All **JSON APIs and WebSocket** go to the backend URL you configure.

## 1. Same domain (simplest for users)

Put nginx (or Caddy) in front of both:

- `https://yoursite.com/` → static files from `frontend/dist/`
- `https://yoursite.com/state`, `/agent/*`, `/ws`, `/api/assets`, `/auto-tick/*`, … → reverse proxy to Uvicorn on `127.0.0.1:8000`

Do **not** expose `GEMINI_API_KEY` to the client. It lives only in the API process environment.

Build the frontend **without** `VITE_API_BASE_URL` so requests stay same-origin:

```bash
cd frontend && npm run build
```

Example nginx location split (static under `/assets/` vs API — note `location = /assets` for the registry JSON if you ever mount `GET /assets` on the API; this project uses `GET /api/assets` for the registry so `location /assets/` can be static files only):

```nginx
location / {
    root /var/www/willowbrook/dist;
    try_files $uri $uri/ /index.html;
}

location /ws {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}

location ~ ^/(state|agent|world|simulation|api|auto-tick|health) {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

Set on the server:

```bash
export GEMINI_API_KEY=...
# Optional: lock CORS to your real site (empty = allow all origins)
export CORS_ORIGINS=https://yoursite.com,https://www.yoursite.com
```

## 2. Split hosting (e.g. Netlify + Fly.io)

- Deploy **static** `dist/` to Netlify / Vercel / Cloudflare Pages at `https://app.example.com`.
- Deploy **API** to Fly, Railway, Render, etc. at `https://api.example.com`.

Build with the API origin baked in:

```bash
cd frontend
VITE_API_BASE_URL=https://api.example.com npm run build
```

On the API host:

```bash
GEMINI_API_KEY=...
CORS_ORIGINS=https://app.example.com
```

The client will call `https://api.example.com/state`, `wss://api.example.com/ws`, etc. Map/GLB URLs stay on `https://app.example.com/assets/...`.

`VITE_API_BASE_URL` must include the scheme (`https://` or `http://`).

## 3. Health checks

`GET /health` returns `{"status":"ok"}` for load balancers.

## 4. Cost and abuse

Public traffic will consume Gemini quota. For “genuine” public use you will want:

- Rate limiting (per IP) on `/agent/chat`, ticks, and TTS
- Optional authentication or invite-only
- Monitoring and spend alerts in Google AI Studio / Cloud

This repo does not include rate limits; add them at the reverse proxy or in FastAPI middleware when you go live.

## 5. What still uses an external API

The simulation **depends on Google Gemini** on the server (chat, planning, embeddings, optional TTS). There is no browser-side Gemini key and no way for guests to “bring their own key” unless you add that feature. To remove cloud APIs entirely you would need a different model stack (e.g. self-hosted Ollama) and code changes across the backend services.
