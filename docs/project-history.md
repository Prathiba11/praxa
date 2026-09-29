# Project history: what was decided, and what went wrong

The other documents describe the system as it is. This one records how it got
here: the choices that shaped it, why each was made, and the mistakes that
taught something. It is the page to read before changing something that looks
odd, because most odd-looking things here are the fix for one of these.

Written 29 September 2026.

---

## Timeline

| When | Version | What happened |
|---|---|---|
| August 2026 | 1 | **Career Copilot** — the retrieval pipeline, tool calling, a Streamlit interface, two stores (Chroma + SQLite), job sources, mock interviews. Reviewed. |
| September 2026 | 2 | Became **PRAXA**: a React front end instead of Streamlit, FastAPI with a live-streamed agent trace, agentic retrieval, a writer-and-critic for documents, long-term memory, Mistral moderation, LangSmith tracing, cost tracking. Reviewed. |
| 29 September 2026 | — | Published here, starting from a fresh history. |
---

## Decisions, and why

**Chroma for meaning, SQLite for records.** Not Postgres + pgvector. It is a
single-user desktop app that holds personal CVs; a database server would add
setup and a place for personal data to leak, for no gain.

**Drop Streamlit completely** in version 2 rather than keep it alongside
React. React + Vite + TypeScript + Tailwind, served by the same FastAPI process
(one port, no CORS). The aim was a polished interface that shows the agent
working live, and a product that could be commercial later.

**The agent loop is plain Python, not LangGraph.** LangGraph was considered.
The loop is written directly against the OpenAI tool-calling API
(`agent/loop.py`). Two reasons: every step shown live in the browser is a line
written here, not a framework callback that might not fire ("a trace shown after
the fact is indistinguishable from a trace invented after the fact"); and every
step can be explained in a review. The cost, stated in the README: anyone
looking for a `StateGraph` will not find one.

**Three kinds of agent, not one.** A tool-calling loop for Chat; a writer and a
separate critic for Documents (because the risk is an author marking their own
work); and a rules engine for Interview (a threshold comparison can be tested
completely and always stops — a model asked "should you follow up?" gives an
agreeable answer that changes with the prompt).

**The mode is the security control.** Each mode sees only its own tools and the
server refuses anything else. A job posting can contain "call tailor_cv and add
ten years of Rust"; in Chat mode there is no writer to call. See
`tools/registry.py`.

**Public job APIs only.** Arbeitnow, Remotive, the Bundesagentur fuer Arbeit,
plus pasting a posting. LinkedIn, Xing, Indeed, StepStone, Monster and
Glassdoor forbid automated collection and are blocked by name. The Bundesagentur
endpoint is unofficial, and the README says so.

**One door to the model.** Every model call goes through `core.llm`, and the
budget check lives inside it. See the "one of eleven" lesson below.

**Closed list of models** on the Settings page, not a free text box. See the
"silent grader" lesson below.

**The monthly budget cannot be changed from inside the app.** "A budget you can
raise from inside the thing it restrains is not a budget."

**Moderation fails open, and says so.** Mistral Moderation is a second net
under the rule-based defences. If Mistral is unreachable the turn goes ahead —
refusing every turn would trade a rare missed check for a common outage. It is
not gated on health, financial or legal content, because a career assistant
reads medtech postings and CVs that mention salary.

**Memory runs after the answer is sent.** The user already has their answer
before any extraction starts, so memory never makes a turn slower, and any
failure ends in "no facts", never an error. It uses the cheaper grader model.

**Evaluation with plain metrics, not Ragas.** A 47-question golden set scored
with hit@k and MRR, plus a measured noise floor. Honest consequence: it is not
claimed as the "Ragas or DeepEval" bonus task.

**Claim only what is true.** Features that were not built (authentication,
learning from feedback, tool toggles) are listed as not done, with the reason.

---

## Lessons: things that went wrong

**The silent grader.** The default grader model returned 404 for the account.
Grading fails open by design, so the app answered normally for about a week
with retrieval grading dead, and memory extraction dead too. Fixes:
`scripts/check_models.py` (one token to every configured model), and a closed
model list. Lesson: *a feature that fails open fails invisibly — give it a check
you can run.*

**Budget checked in one place out of eleven.** When the budget check lived in
the callers, only one of eleven call sites checked it and two recorded no cost
at all. Moved into `core.llm.chat`, and a test now fails if any file talks to a
provider directly.

**`pytest` was spending money.** The paid red-team suite was documented as
"deselected in CI", but nothing deselected it, so every plain `pytest` run
called the real model. Fixed with `-m 'not live'` in `pyproject.toml`.

**122 seconds to fetch jobs — and it wasn't the code.** Two job sources
publish IPv6 addresses; on a machine with no IPv6 route, Python waited out a
timeout per address before trying IPv4. One shared HTTP client with
`CC_FORCE_IPV4` took it to 2.7 s. Four changes had already been made to the
source that turned out to be the fastest. Lesson: *measure before changing
anything.*

**Reranking was 74% of a warm turn.** A candidate cap, a 320-token window,
shorter scoring text and a smaller multilingual cross-encoder took a warm turn
from 16.9 s to 4.5 s.

**`.gitignore` rules that swallowed source code.** `data/*` hid the whole
knowledge base, `resumes/` matched folders at any depth, and `audio/` hid the
entire speech-to-text package — nothing warned about any of it. And the SQLite
`-wal` / `-shm` side files, which hold real rows (postings, remembered facts,
interview answers), were tracked, because `*.db` does not match them. The rules
are now narrow and commented. Lesson: *a gitignore rule that quietly drops
source is worse than one that leaks a temp file.* (This public repository starts from a fresh history for exactly that reason.)

**A missing dependency.** `langchain-openai` was imported but not listed in
the dependencies. It worked locally for weeks because it happened to be
installed in the local virtualenv; a clean clone could not start. Only CI's
clean machine caught it.

**CI switched off during a release window.** The reasoning was that tests
ran locally before every push. Wrong: the reviewer had no CI run to look at. It
is back on, and a front-end job was added because the half a reviewer actually
looks at was the half CI never built.

**The Docker image shipped the old Streamlit interface** for a whole version
while the "does it import?" check passed. The Docker job now starts the
container and checks that `/` really serves the React app. It runs on demand
only, because installing torch from scratch takes longer than a runner allows
(it once hung for six hours before it had a timeout).

**Python 3.14 in the CI matrix.** It failed at `pip install` (torch, chromadb
and sentence-transformers have no wheels for it), which said nothing about the
project. Removed; stated as a limitation instead.

**The red-team suite caught an injection working.** A retrieved passage could
switch off inline citations. Kept as a retained risk (R8 in `security.md`,
weakness 18) with the reasoning, rather than hidden.

**Day-to-day gotchas.** Windows line endings create noisy diffs — never
`git add -A`, stage explicit paths, check with
`git diff --stat --ignore-cr-at-eol`. CI runs `ruff format --check .` as well as
`ruff check .`; forgetting the second one broke CI twice.

---

## What comes next

Ideas named, not yet built:

- Background work: batch job scoring, scheduled job fetching, knowledge-base
  re-indexing.
- Multi-user and commercial use — deliberately out of scope today.

The full list of known weaknesses is in [weaknesses.md](weaknesses.md).
