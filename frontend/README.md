# Praxa frontend

React + Vite + TypeScript + Tailwind, using shadcn/ui conventions. This replaces
the Streamlit app; it talks to the FastAPI layer under `/api`.

## Commands

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm run build      # -> frontend/dist, which FastAPI serves in production
npm run typecheck
npm run lint
```

`npm run dev` expects uvicorn on port 8000. Point it somewhere else with
`$env:PRAXA_API_URL = "http://127.0.0.1:9000"` before `npm run dev`.

## Decisions worth knowing

**Same-origin by construction.** The client always calls a relative `/api`. In
development Vite proxies it; in production FastAPI serves this bundle from
`dist/` and owns `/api` on the same origin. There is no base-URL setting to get
wrong and no CORS to configure.

**Tailwind v3, not v4.** v3 with `tailwind.config.js` and PostCSS is the
combination every shadcn component is written against, and it does not move
under you mid-sprint. `components.json` is present, so `npx shadcn@latest add
<component>` still drops files into `src/components/ui/` when you want one.

**The UI primitives are in the repo, not fetched.** `button`, `card`, `badge`,
`input`, `skeleton` and `empty-state` are authored here using shadcn's own
conventions — same paths, same `cn()` helper, same `class-variance-authority`
variants. A fresh clone builds with no network call to a component registry.
Each component's variants live in a sibling `*-variants.ts` file so the
component file only exports a component, which is what React Fast Refresh needs.

**SSE, not websockets.** `streamChat` in `src/lib/api.ts` reads a `fetch` stream
and parses SSE frames, so a chat turn can POST its body (which `EventSource`
cannot) and still stream back. The parser tolerates malformed frames rather than
killing the stream.

**The agent loop is visible.** `src/components/agent-trace.tsx` renders the phase
the agent is in and one row per retrieval round with the grader's verdict. When
the retrieval grader decides the evidence is thin and re-queries, that shows up
as a second row — which is the point of agentic retrieval being agentic.

## Layout

```
src/
  lib/types.ts       the API contract, written from the client side
  lib/api.ts         fetch wrapper, typed errors, SSE reader
  hooks/             chat stream, theme
  components/ui/     primitives (shadcn conventions)
  components/layout/ shell, page frame, usage meter
  routes/            chat, jobs, interview, memory, settings
```

`src/lib/types.ts` is the single place the request and response shapes live. It
is written before the endpoints exist on purpose: it is the spec the FastAPI
models are built against.

## What the Dockerfile needs

A Node build stage that runs `npm ci && npm run build` in `frontend/`, then
copies `frontend/dist` into the Python image where FastAPI mounts it. Keep the
existing explicit CPU-only PyTorch install before the project install — that is
what stops the CUDA build being pulled.
