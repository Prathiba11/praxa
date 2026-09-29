# Tracing

Every agent turn can be recorded as a tree in [LangSmith](https://smith.langchain.com):
the turn at the root, retrieval and tool calls as steps beneath it, and each
model call as a leaf carrying its tokens, cost and latency.

It is **off by default**. A fresh clone runs, and the tests pass, with no
LangSmith account.

## Turning it on

Add to `.env`:

```
CC_TRACING_ENABLED=true
LANGSMITH_API_KEY=ls__your_key_here
LANGSMITH_PROJECT=praxa
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
```

`LANGSMITH_PROJECT` is optional and defaults to `praxa`.

**`LANGSMITH_ENDPOINT` is required on a non-US workspace.** If you sign in at a
URL beginning `eu.` — `eu.smith.langchain.com` — your data lives in the EU
region, and the SDK talks to the US region unless told otherwise. Every trace
is then rejected at ingest, with an error that does not explain why.

The value is the **API** host, not the address you sign in at: the same name
with `api.` in front of it. Getting that wrong is the single most common
tracing problem, so the code warns when the endpoint looks like a web address.
Confirm the exact value on the API keys page of your workspace settings rather
than copying it from anywhere else.

Leave `LANGSMITH_ENDPOINT` unset on a US workspace — the SDK default is correct
there, and setting it to the wrong region breaks what would otherwise work.

Half-configured is off, not broken: the flag without a key logs a warning and
carries on untraced. That matters because the failure mode of getting it wrong
would otherwise be a stalled request on every turn.

## The test suite never traces

`tests/conftest.py` forces tracing off for every test, whichever way your
`.env` is set. Without that, running the suite on a configured machine would
ship traces to your workspace — spending quota and filling the project with
runs that never happened in an application.

It **sets** the settings off rather than deleting the environment variables,
which is the subtle part: deleting a variable does not make a setting unset.
Pydantic-settings simply falls through to the next source, which is `.env`. The
tests that exercise tracing turn it back on for themselves.

## Why this is not the two-line version

LangSmith traces LangChain and LangGraph calls automatically, and the usual
setup instructions stop there. This codebase would show nothing, because
`core.llm.chat` talks to the OpenAI SDK directly rather than through LangChain.

So two pieces do the work:

- `instrument()` wraps the OpenAI client, which produces the **leaves** — the
  model calls, with tokens and cost.
- `@traced` on the agent turn, the retrieval pipeline and `Tool.run` produces
  the **tree** those leaves hang from.

Without the first you get shape and no substance; without the second you get a
flat list of model calls with no idea which turn they belonged to.

## What it costs when it is off

One boolean check per decorated function, once. `@traced` resolves to the
undecorated function on its first call and stays that way, so a disabled build
does not pay per call.

## What is recorded

| Step | Kind | Notes |
|---|---|---|
| `agent turn` | chain | Root. Carries `mode`, `session_id` and `max_steps` as metadata. |
| `rag answer` | retriever | The full retrieval pipeline for one question. |
| `tool` | tool | One per tool call, named by the tool. |
| model calls | llm | From the wrapped client: tokens, cost, latency. |

`session_id` on the root is what ties a trace back to a row in `usage.jsonl`,
so a trace and its spend can be lined up.

## Known gap

The off path is covered by tests. The on path is verified only as far as
"the SDK gets configured" — whether traces actually arrive is something to
check once, by hand, the first time you add a key.
