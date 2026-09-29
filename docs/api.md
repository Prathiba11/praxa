# The HTTP layer

One FastAPI process serves the API under `/api` and the built React bundle at
everything else. That is the whole deployment: one command, one port, one URL.

## Running it

Development — two processes, because Vite's hot reload is worth it:

```bash
uvicorn career_copilot.api.app:create_app --factory --reload --port 8000
cd frontend && npm run dev          # http://localhost:5173, proxies /api to 8000
```

Production — one process:

```bash
cd frontend && npm run build        # writes frontend/dist
uvicorn career_copilot.api.app:create_app --factory --port 8000
```

Then open <http://localhost:8000>. Interactive API docs are at `/api/docs`.

There is no module-level `app`, hence `--factory`. Building one at import time
would read the settings - and so fail on a missing key - before anything had
asked for a server, which is how a test suite ends up requiring a `.env`.

A checkout with no `frontend/dist` still serves the API and answers `/` with a
note saying how to build the bundle. The evaluation harness and the tests need
the API and have no use for the HTML.

## Why there is no CORS configuration

Same origin by construction. The client calls `/api`, always: no base-URL
setting to get wrong, no preflight, no allowlist to widen by accident. In
development the Vite proxy preserves the same property.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/health` | Liveness, version, and whether tracing is on. No model call. |
| `GET` | `/api/usage` | Spend for a thread (`?threadId=`) and month-to-date. |
| `POST` | `/api/chat/stream` | One agent turn, streamed as server-sent events. |
| `GET` | `/api/jobs` | Saved postings, filtered by profile, place, company, status, text or fit. |
| `GET` | `/api/jobs/funnel` | How many postings sit at each application status. |
| `GET` | `/api/jobs/{id}` | One posting, with its full description and history. |
| `POST` | `/api/jobs/{id}/status` | Move an application through the funnel. |
| `POST` | `/api/jobs/paste` | Save a posting pasted in by hand. |
| `GET` | `/api/memory` | Everything remembered, most recently mentioned first. |
| `POST` | `/api/memory` | Record a fact the user stated outright (`origin: stated`). |
| `DELETE` | `/api/memory/{id}` | Forget one fact. |
| `DELETE` | `/api/memory` | Forget everything; returns how many rows went. |

Only `/api/chat/stream` calls a model. Everything else is SQL and
serialisation. The test suite refuses at the model client, so a page endpoint
that acquired an LLM call fails its own tests rather than quietly spending
money — an agent capability that leaks into a page is a cost the user never
asked for and a code path the trace panel cannot show.

Requests and responses are camelCase, because the consumer is a browser. Python
stays snake_case and Pydantic's alias generator bridges the two.

## The stream

A turn takes seconds and spends most of them retrieving. Streaming is not about
the text arriving a word at a time - it is about the agent's decisions being
visible **while they are being made**, because a trace shown after the fact is
indistinguishable from a trace invented after the fact.

Frames, in order:

| `type` | When | Carries |
|---|---|---|
| `status` | Each phase change | `phase`: moderating, thinking, searching, grading, requerying, answering |
| `tool` | Around each tool call | `name`, `state`: started, finished, error |
| `retrieval` | Each retrieve-grade-requery round | `round`, `verdict`, `query`, `sources` |
| `token` | The answer | `text` |
| `citations` | With the answer | the passages it drew on |
| `done` | Success | `messageId`, and what this turn cost |
| `error` | Failure after the 200 | `code`, `message`, `correlationId` |
| `end` | Always last | nothing |

The answer arrives as **many** `token` frames, one per fragment, because
`core.llm.stream_chat` streams from the provider. A turn that also calls a tool
streams from the same request, so the server reassembles the tool call from
fragments keyed by `index` before running it; the client sees only the `tool`
frames and then the text. Usage is requested with the stream
(`stream_options={"include_usage": True}`), so the ledger counts a streamed
turn exactly as it counts a plain one.

`retrieval` is emitted once per round of the retrieve-grade-requery loop — see
`docs/retrieval.md`. A second event with the same question but a different
`query` is the pipeline deciding its own first search was not good enough.

`citations` is declared and rendered but not yet emitted: structured citations
come out of the retrieval pipeline, and the tool that calls it currently hands
the agent formatted text. The shape is agreed here rather than discovered twice.

`end` exists so that a stream cut short by a dead server is distinguishable
from one that finished. Without it both look like a closed connection.

### Failures mid-stream

The status line said `200` before the first byte was written, so there is no
status left to fail with. A failure after that point becomes an `error` frame
carrying the same `code` an ordinary error response would have carried, and the
stream then closes normally. A `POST /api/chat/stream` that reaches the agent
is therefore always a `200`; only a malformed request is a `422`.

### Disconnects

If the client goes away, the turn keeps running to completion. It cannot be
cancelled mid-tool without leaving half-written state, and it must still be
billed - the money was spent whether or not anyone was listening.

## Error envelope

Every non-2xx response under `/api` has the same body:

```json
{ "code": "budget_exhausted", "message": "The spending limit for this session has been reached.", "correlationId": "177ff529" }
```

The UI branches on `code`, never on the status or the message text: "your
spending limit is reached" and "the model provider is down" both look like a
failed request, and a user who cannot tell them apart will retry the wrong one -
and pay for the retry.

`detail`, the full technical description, is logged and never sent.
`correlationId` is sent, so a screenshot of an error can be found in the log.

| `code` | Status | Meaning |
|---|---|---|
| `budget_exhausted` | 429 | A spend ceiling is reached. |
| `rate_limited` | 429 | The provider asked us to slow down. |
| `moderation_blocked` | 400 | Refused on security grounds. |
| `invalid_request` | 400 / 422 | The request is malformed. |
| `insufficient_evidence` | 502 | Retrieval could not support an answer. |
| `tool_not_permitted` | 400 | The tool is not in this mode's allowlist. |
| `not_found` | 404 | No such endpoint. |
| `upstream_unavailable` | 503 | The model provider is down. |
| `internal_error` | 500 | A bug. Quote the correlation id. |

Pydantic's own 422 body - a list of error dicts under `detail` - is logged and
replaced with this envelope. It is useful while developing and useless to a
client that branches on `code`.

## Threads, sessions and the budget

The client mints a `threadId` and sends one message; the server holds the
recent history. That store is a bounded dictionary in the serving process: 16
messages per thread, 32 threads, least-recently-used evicted. **Restarting the
server forgets every conversation.** That is the honest cost of not having a
conversation store yet, and long-term memory - facts that survive a restart,
extracted on purpose - is a different thing arriving in its own phase.

The thread id is also the usage session id, which has a consequence worth
stating plainly: **a client that rotates its thread id resets its own session
ceiling.** The monthly ceiling cannot be evaded that way, and it is what
actually protects the card. `GET /api/usage` reports both, and
`budgetRemainingUsd` is the smaller of the two headrooms - the number that will
stop the next turn.

One turn runs at a time per thread. Two would interleave their messages and
make the before/after usage snapshot meaningless.

`unpricedCalls` is the honesty field. A cost total assembled partly from calls
whose price nobody knows is an understatement, and showing the total without
showing that is worse than showing nothing.

## Concurrency

`run_agent` is synchronous and spends its time waiting on the network. Called
directly from the event loop it would block every other request, so it runs in
a worker thread and reports progress back through an `asyncio.Queue` written
with `call_soon_threadsafe`. The queue is the only thing crossing the boundary.

## Testing

`tests/api/` runs against `TestClient`, with the agent stubbed. What is under
test is the wire - which frames arrive, in what order, in what spelling, and
what happens when a turn fails after the 200 has gone out. Whether the model
answers well is the evaluation suite's question, not this one's.

`tests/api/test_static_serving.py` builds the app with a bundle present, which
the rest do not. That distinction is not decoration: with no `frontend/dist`
the static mount does not exist, so a fallback rule that swallows `/api` paths
passes every other test and then fails the first time anybody builds the
frontend. It was found exactly that way, by curling a running server.
