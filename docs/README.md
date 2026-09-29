# The documentation, and what each part is for

Each document answers a different question, and each states what it cannot
claim as well as what it can — the limits are part of the design, not omissions
from it.

## Start here

| Document | The question it answers |
|---|---|
| [Career-Copilot-walkthrough.pptx](Career-Copilot-walkthrough.pptx) | The 30-minute version: what it does, how it is built, and what the numbers say. |

## How it works

| Document | The question it answers |
|---|---|
| [retrieval.md](retrieval.md) | How does a question become evidence, and when does the system go back for more? |
| [memory.md](memory.md) | What does it keep between sessions, and how does the user get rid of it? |
| [api.md](api.md) | What does the HTTP layer expose, and what does a failure look like halfway through a stream? |

## Whether to trust it

| Document | The question it answers |
|---|---|
| [security.md](security.md) | What can go wrong, how likely is it, what stops it, and what is accepted? |
| [evaluation.md](evaluation.md) | Does the retrieval grading loop actually improve anything? |
| [tracing.md](tracing.md) | How do you see inside a turn after it has happened? |
| [weaknesses.md](weaknesses.md) | What is wrong with this, and what was knowingly accepted? |

## Where things are

| Document | The question it answers |
|---|---|
| [reference.md](reference.md) | Where does everything live, what does each script do, what does each setting change? |
| [project-history.md](project-history.md) | Why is it built this way, and what went wrong on the way? |

## Reading orders

**To understand the system**, read `retrieval.md` then `api.md`. The first is
the loop that turns a question into evidence; the second is how that loop's
progress reaches a browser while it is still running.

**To review the engineering judgement**, read `security.md` and
`evaluation.md`. The threat analysis maps every threat to a control and the
test that proves the control works, and retains five risks with reasons —
including R8, an injection the red-team suite caught succeeding. The
evaluation reports a measurement *and* the measured noise floor that bounds
what it can claim.

**To check the privacy story**, read `memory.md` and section 7 of
`security.md`. Between them they cover what is stored, what is masked, what
reaches the model provider, and what is deliberately accepted.

## The three claims worth checking hardest

Each of these is somewhere the system could look better than it is, so each is
written to be checkable rather than believed.

**"Retrieval is a loop."** The grader fails open — if it cannot be reached, the
answer is written from whatever came back. That means a grader which never runs
is indistinguishable from one that always approves. `scripts/check_models.py`
is the check; the story of it being broken for a week is in `retrieval.md`.

**"The grading loop improves retrieval."** Now demonstrated, narrowly. On 47
questions over 24 documents hit@5 moves 89% to 91% at document level and 66% to
68% at section level, with a measured 0% noise floor. One question is a genuine
rescue: the single search missed it entirely and the re-query found it at rank
1. Two more were reranked. Three questions carry the gain, on a corpus where the
same code rescued nothing when it was smaller — so the honest reading is that a
harder corpus gives the loop more to fix, not that the feature improved.
`evaluation.md` carries the per-question detail, including three questions
counted as misses because the golden set asks them ambiguously.

**"Memory is safe."** It is bounded, masked, visible and deletable, and framed
in the prompt as preference rather than evidence. It still has a residual
injection path — the extractor reads the assistant's reply, and that reply can
have been influenced by retrieved text. That is retained risk R6 in
`security.md`, with the reasoning for accepting it.
