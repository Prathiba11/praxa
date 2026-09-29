# Does the retrieval grader earn its place?

`scripts/evaluate_grading.py`, 47 questions from `tests/eval/golden_set.json`, k=5.

Two runs per question, differing in one setting: whether the evidence is
graded and re-queried. The query analysis is computed once and shared.

| configuration | what it does |
|---|---|
| `ungraded` | search once, answer from whatever came back |
| `graded` | search, judge the evidence, re-query once if it is thin |

Metrics are deterministic — the golden set says which document and which
section each question should reach, so nothing here is a model marking its
own work.

## Overall

### Document level — was the right file found?

| configuration | hit@k | MRR | n |
|---|---|---|---|
| ungraded | 89% | 0.730 | 47 |
| graded | 91% | 0.782 | 47 |

### Section level — was the right part of it found?

| configuration | hit@k | MRR | n |
|---|---|---|---|
| ungraded | 66% | 0.479 | 47 |
| graded | 68% | 0.501 | 47 |

## How much of this is noise

On a question where the grader approves the first round, the two
configurations **must** retrieve identically: grading judges round one, it
does not change it. Any difference on those questions is measurement noise,
and measuring it is what makes the rest of this report readable.

- Questions where the loop did not fire: **38**
- Of those, the document rank still differed: **0** (**0%**)

Nothing differed, so the two configurations are cleanly comparable on
the questions where the loop did not fire.

## How often the loop fired

- Questions where the grader sent retrieval back out: **9 of 47**
- Verdicts on the graded run: `none` x1, `sufficient` x42, `weak` x4

A verdict of `sufficient` on the first round means the loop cost one extra
model call and changed nothing — which is the intended common case. The
feature is only *capable* of helping on the questions below.

## Where it actually fired

The loop re-queried **9** questions. Of those, **3** retrieved anything
different from the single-search run — the rest searched again and landed on
the ranks they already had. Every number in the two tables below is carried by
those 3 questions.

- how do I show a manager in numbers whether we are shipping quickly — doc None to 1, section None to 1
- when is it reasonable to stop building features for a while and wo — doc 4 to 1, section None to None
- should I copy phrases straight out of the advert into my CV? — doc 3 to 1, section None to None

### Document level, re-queried questions only (n=9)

| configuration | hit@k | MRR | n |
|---|---|---|---|
| ungraded | 56% | 0.398 | 9 |
| graded | 67% | 0.667 | 9 |

### Section level, re-queried questions only (n=9)

| configuration | hit@k | MRR | n |
|---|---|---|---|
| ungraded | 11% | 0.111 | 9 |
| graded | 22% | 0.222 | 9 |

### What it searched for instead

**how do I show a manager in numbers whether we are shipping quickly and safely?**

1. `how do I show a manager in numbers whether we are shipping quickly and safely?`
2. `how to measure shipping efficiency and safety metrics`

- ungraded: doc rank None
- graded: doc rank 1, final verdict `sufficient`

**when is it reasonable to stop building features for a while and work on stability instead?**

1. `when is it reasonable to stop building features for a while and work on stability instead?`
2. `when to prioritize stability over feature development`

- ungraded: doc rank 4
- graded: doc rank 1, final verdict `sufficient`

**what is the difference between the process maturity assessment and the security standard?**

1. `what is the difference between the process maturity assessment and the security standard?`
2. `difference between process maturity models and security frameworks`

- ungraded: doc rank 1
- graded: doc rank 1, final verdict `weak`

**should I copy phrases straight out of the advert into my CV?**

1. `should I copy phrases straight out of the advert into my CV?`
2. `should I use exact phrases from job postings in my CV?`

- ungraded: doc rank 3
- graded: doc rank 1, final verdict `sufficient`

**have I ever taught this material to other engineers?**

1. `have I ever taught this material to other engineers?`
2. `have I conducted training sessions for engineers?`

- ungraded: doc rank 1
- graded: doc rank 1, final verdict `weak`

**what is the weather in Stuttgart tomorrow?**

1. `what is the weather in Stuttgart tomorrow?`
2. `weather forecast Stuttgart`

- ungraded: doc rank None
- graded: doc rank None, final verdict `none`

**our assistant keeps stating the wrong company policy - should we train it on our own documents?**

1. `our assistant keeps stating the wrong company policy - should we train it on our own documents?`
2. `how to train an AI assistant on company policies`

- ungraded: doc rank 1
- graded: doc rank 1, final verdict `weak`

**I worked nine years in one industry and want to move - do I explain why I am switching?**

1. `I worked nine years in one industry and want to move - do I explain why I am switching?`
2. `how to explain a career change in an interview`

- ungraded: doc rank None
- graded: doc rank None, final verdict `sufficient`

**how do I show I can do work I have never been paid to do?**

1. `how do I show I can do work I have never been paid to do?`
2. `how to showcase transferable skills in a job application`

- ungraded: doc rank None
- graded: doc rank None, final verdict `weak`

## What it cost

Model calls and money are the portable numbers — they are the same on any
machine. Wall-clock is not, and on the machine this ran on it is badly
misleading, for a reason that has nothing to do with grading: a call that
follows the cross-encoder stalls for about 45 seconds here. The graded
configuration makes more calls, so it collects more stalls.

| configuration | model calls | cost | mean latency (this machine) |
|---|---|---|---|
| ungraded | 0 | $0.0000 | 24.0 s |
| graded | 66 | $0.0103 | 31.0 s |

Total for this run: **$0.0103** across 47 questions x 2 configurations.

The real cost of the feature is the call count: one grading call per round,
plus a full extra retrieval on the questions that are re-queried. In money
that is fractions of a cent. Do not read the latency column as the cost of
grading — read it as the cost of a stall this machine has.

These are warm numbers. The embedder and cross-encoder are loaded before
the first measurement, because they take about ninety seconds in a fresh
process and whichever configuration ran first would otherwise be charged
for all of it. The application pays that cost once at startup, not per
question, so charging it to a question here would be measuring the
benchmark rather than the feature.

## Reproducing this

```
python scripts/evaluate_grading.py
```

Raw per-question results, including every passage retrieved, are written to
`data\eval\grading_ab.json` so any number here can be checked rather than believed.
