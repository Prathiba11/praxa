# Layout, scripts and configuration

The lookup material: where things live, what each script does, and every
environment variable. Split out of the root README so that file can be
read start to finish.

## Project layout

```
career_copilot/
  core/        config, errors, logging, LLM client, usage, security, conversation memory
  rag/         loaders, chunkers, embeddings, store, query analysis, translation,
               retrieval, reranking, pipeline
  agent/       the tool-calling loop
  tools/       typed tools + the per-mode allowlist
  jobs/        job sources, normalisation, dedupe, classification, sync
  interview/   personas, rubric, question generation, state machine, session
  documents/   ATS-safe Word export
  storage/     SQLAlchemy models and repositories, including remembered facts
  memory/      what a finished turn is worth keeping, and how it is recalled
  api/         FastAPI app, routes, schemas, one error envelope
  audio/       speech-to-text adapter (local or hosted)
frontend/      React client (Vite, TypeScript, Tailwind); built into frontend/dist
kb/            the knowledge base: guides, domain references, sample CVs
scripts/       ingest, fetch jobs, profile, compare retrieval, evaluate, diagnose
docs/          the walkthrough deck, plus retrieval, memory, the API,
               tracing, security, evaluation, weaknesses
tests/         unit, integration, functional, live (red team), eval
```

## Scripts

| Script | What it does |
|---|---|
| `verify_setup.py` | Checks your `.env`, the API key and the model round-trip before anything else. Run this first if something is not working. |
| `ingest.py` | Loads `kb/` and `data/kb/resumes/`, chunks, embeds and writes the Chroma index. |
| `search.py` | Query the index from the terminal, without the UI or an LLM call. |
| `agent_demo.py` | Run one agent turn with `--trace`, to see the tool calls and timings. |
| `fetch_jobs.py` | Pull postings from the job APIs into SQLite. |
| `compare_retrieval.py` | The A/B harness behind the reranking table above. |
| `profile_turn.py` | Stage-by-stage latency, cold and warm. |
| `migrate_interviews.py` | Additive schema changes to the interview tables. Idempotent. |
| `generate_personas.py` | The four seated figures on the Interview page - three interviewers and the candidate's chair. Run once; the WEBPs are committed alongside the background art, so a clone has them without a key. Invented people, no likeness of anyone; the page falls back to initials if they are missing. |
| `check_models.py` | One token to every configured model. Run it after changing any model id — grading and memory fail open, so a wrong id is silent. |
| `evaluate_grading.py` | The grading A/B above. `--limit N` for a smoke test, `--report-only` to rewrite the report from saved results. |
| `diagnose_latency.py` | Locates a connection stall: three ways of spending the same gap, so "idle" and "busy" can be told apart. `--connect` times raw TCP by address family, free. |
| `generate_art.py` | Regenerates the background textures through the same OpenRouter key the app uses. Run once, by hand; the results are committed, so the interface makes no network call to draw itself. `--list` shows which of your models return images. Costs about a cent per piece. |

---

## Configuration

Every setting is in `.env` (see `.env.example`). The ones worth knowing:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Required. All chat models are routed through OpenRouter. |
| `CC_MODEL` | Which chat model to use. Any OpenRouter model id works. |
| `CC_CHROMA_DIR`, `CC_DB_PATH` | Where the two stores live. |
| `CC_RERANK_ENABLED`, `CC_RERANK_TOP_K`, `CC_RERANK_MODEL` | Reranking behaviour. |
| `CC_SESSION_BUDGET_USD`, `CC_MONTHLY_BUDGET_USD` | Spend ceilings, enforced before every call. |
| `CC_GRADER_MODEL` | The grader and the memory extractor. Classification, not writing — but check any change with `check_models.py`. |
| `CC_GRADING_ENABLED`, `CC_MAX_RETRIEVAL_ROUNDS` | The retrieval loop. Off and `1` are the evaluation's baseline. |
| `CC_MEMORY_ENABLED` | Long-term memory. Off skips extraction and injects nothing. |
| `CC_WARM_MODELS` | Load the embedder and reranker at startup instead of inside the first question. |
| `CC_HF_OFFLINE` | Load both from the local cache and never ask the Hugging Face Hub. Turn on after the first run. |
| `CC_FORCE_IPV4`, `CC_HTTP_KEEPALIVE_SECONDS` | Connection behaviour. See weakness 15. |
| `GROQ_API_KEY` / `OPENAI_API_KEY` | Optional. Enables fast hosted speech-to-text. |

OpenRouter routes chat models only — it has no audio endpoint — which is why
speech-to-text has its own adapter with a local default.
