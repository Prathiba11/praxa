# Agent Architectures

Personal reference summary. Framework names and APIs move quickly; the patterns
below are stable, the libraries are not.

## What makes a system an agent

The useful definition is narrow: **an agent decides what to do next.** A pipeline
with a fixed sequence of model calls is not an agent, however many calls it
makes. An agent chooses which tool to call, with what arguments, and when it has
finished.

That single property is where the value and every operational problem come from.
A fixed pipeline has a bounded cost and a known failure set. An agent has neither
until you impose them.

## The basic loop

Almost every agent reduces to:

1. Assemble a prompt: instructions, available tools, conversation so far
2. Call the model
3. If it returned tool calls, execute them and append the results
4. Repeat until it returns an answer, or a limit is hit

Everything else — planning, reflection, multi-agent structures — is a variation
on what goes into step 1 and what counts as "finished" in step 4.

The loop must be bounded on three axes, and all three matter:

- **Turns** — a hard maximum, because a model that keeps calling one tool will
  keep calling it forever
- **Cost** — checked *before* each call, not after, so an over-budget turn costs
  nothing
- **Wall clock** — because a slow tool can hold a loop open long after the user
  has left

An agent without all three is a service that can be made to spend money by a
sufficiently confusing question.

## Tool design is most of the work

Model quality matters less than tool quality, which is unintuitive until you have
watched a capable model fail against a badly described tool.

- **One clear job per tool.** A tool that does three things depending on an
  argument is a tool that gets called with the wrong argument.
- **The description is the specification.** It is read by the model, every turn,
  and it is the only documentation it has. Say what the tool does, what it needs
  and when *not* to use it.
- **Validate arguments in code.** The model produces a plausible object, not a
  valid one. Parse it into a typed schema and reject what fails.
- **Errors must be instructive.** "Error: 400" teaches nothing. "job_id not found;
  call search_jobs first to get one" is a recoverable turn.
- **Truncate tool output.** A tool returning 50,000 characters will fill the
  context and push out the instructions.

## Limiting what an agent can reach

The blast radius question: what can this loop do that is hard to undo?

- **Allowlist tools per mode**, and enforce it on the **server** rather than in
  the prompt. A prompt-level restriction is a request; a registry that refuses to
  resolve a tool name is a control.
- **Separate read from write.** Reads can be free; writes should be few, explicit
  and logged.
- **Put a person in front of irreversible actions.** Generating a document and
  persisting it are two operations, and the gap between them is where approval
  belongs.
- **Treat every tool result as untrusted input.** Retrieved text, a fetched page
  and an API response can all contain instructions. Delimit them and say in the
  prompt that content inside the delimiters is data.

## Patterns worth naming

- **ReAct** — interleaved reasoning and acting, the default shape above.
- **Plan-and-execute** — produce a plan first, then carry it out. Fewer model
  calls and easier to inspect; brittle when a step fails and the plan needs
  rewriting.
- **Reflection** — the model critiques its own output and revises. Cheap to add,
  and weak: a model asked to check its own work tends to agree with itself.
- **Generator–critic** — a *second* call, with a different prompt and no tools,
  reviews the first one's output against a source. Stronger than reflection
  precisely because the critic cannot rewrite, only report. The asymmetry is the
  point.
- **Router** — a cheap first call classifies the request and dispatches to a
  specialised handler. Often the highest-value structure, and the least
  glamorous.

## Multi-agent, and when it is worth it

"Multi-agent" covers two quite different things:

- **Several roles in one process**, each with its own prompt and tool set —
  writer and reviewer, planner and executor. Usually worth it when the roles have
  genuinely different objectives, because a single prompt asked to both produce
  and judge will favour producing.
- **Independent agents communicating** — more machinery, more failure modes,
  and rarely justified at application scale.

The honest test: does each agent have a different objective, or just a different
paragraph of the same one? If the latter, it is one agent with a longer prompt
and twice the cost.

## Evaluating an agent

Final-answer accuracy is necessary and insufficient. Also measure:

- **Tool-call correctness** — right tool, right arguments, on a fixed set of cases
- **Turn count and cost distribution** — the tail is what hurts, not the mean
- **Recovery** — inject a failing tool and see whether the loop adapts or spirals
- **Termination** — how often it hits the turn limit rather than finishing

The last one is the most informative single number, and almost nobody records it.

## Practical observations

- **Most "the model is not smart enough" turns out to be a tool description.**
  Read the trace before changing the model.
- **Determinism is not available; reproducibility partly is.** Log the full
  message list for every turn. Without it a bad turn cannot be investigated, only
  re-rolled.
- **A framework that hides the loop makes the loop hard to trace.** The trade is
  real either way: hand-writing it is more code and complete visibility.
- **Streaming changes the failure mode.** Once tokens have reached the user you
  cannot retract them, so validation that must gate an answer has to happen
  before the first token, not after the last.
