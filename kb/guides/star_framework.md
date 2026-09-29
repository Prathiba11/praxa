# STAR and Behavioural Interview Framework

Reference material for generating interview questions, evaluating spoken answers,
and coaching improvements. Written for engineering interviews in the German and
wider European market.

## The STAR structure

**Situation** — the context, in one or two sentences. Where, when, who was
involved, what was at stake. Enough for the interviewer to picture it, no more.

**Task** — what *you specifically* were responsible for. Not the team's goal:
yours. This is the letter most candidates skip, and skipping it is why answers
sound like someone else's work.

**Action** — what you did, step by step, in the first person singular. The bulk
of the answer. Include the decision points: what you considered, what you
rejected, and why.

**Result** — the outcome, quantified wherever possible, plus what you learned or
would do differently. An answer without a result is an anecdote.

Target length: 90 seconds to 2 minutes. Rough proportions: Situation 15%,
Task 15%, Action 55%, Result 15%.

## Strong versus weak, letter by letter

| | Weak | Strong |
|---|---|---|
| **S** | "We had a lot of security problems." | "A tier-1 supplier needed ISO/SAE 21434 conformity for an ECU platform three months before a homologation deadline." |
| **T** | "We had to fix it." | "I owned the TARA for that platform and the resulting process gap analysis." |
| **A** | "We did threat modelling and improved things." | "I ran structured threat analysis across the communication interfaces, mapped findings to CVE and CWE entries, prioritised by impact, and presented a remediation plan directly to the customer's development lead. I chose interface-level analysis over full-system modelling because the deadline made the latter unachievable." |
| **R** | "It went well." | "All high-severity findings were closed before homologation. The interface-first approach became the template for two later projects. What I would change: I would have involved the test team a week earlier." |

## The four failure modes to score against

**1 · "We" instead of "I".** The most common problem. The interviewer cannot
tell what the candidate personally did. Probe: *"You have said 'we' three times.
What did you personally do?"*

**2 · No number in the Result.** Probe: *"What was the measurable outcome? Give
me a figure."* If no metric exists, a qualitative but concrete result is
acceptable — "the finding blocked release until it was fixed" — but vagueness is
not.

**3 · No decision visible in the Action.** A list of steps without reasoning
shows execution but not judgement. Probe: *"Walk me through that decision. What
was the alternative and why did you reject it?"*

**4 · Rambling.** Four minutes for a 90-second question is itself a failure — it
signals poor prioritisation under pressure. Probe: *"Give me the 30-second
version."*

## Scoring rubric

Score each dimension 1–5. Show the rubric after the session, never during — mid
-interview feedback destroys realism.

| dimension | 1 | 3 | 5 |
|---|---|---|---|
| **STAR structure** | no discernible structure | S/A present, T or R missing | all four present and proportionate |
| **Specificity** | generic claims | some concrete detail | names, systems, standards, timeframes throughout |
| **Quantified outcome** | none | vague ("much faster") | explicit figure with a basis |
| **Ownership** | "we" throughout | mixed | clear personal contribution, credit given to others where due |
| **Relevance** | unrelated to the role | loosely relevant | directly evidences a stated requirement |
| **Conciseness** | rambling or too brief | slightly long | tightly delivered in 90–120 s |
| **Technical depth** | surface terminology | correct but shallow | accurate, appropriately deep, handles follow-ups |

## Interviewer behaviour: how to be realistic rather than helpful

A default language model is encouraging and accommodating, which is the opposite
of an interviewer. An interviewer simulation must be explicitly instructed to:

- adopt a specific persona (HR screener, hiring manager, technical lead, panel)
- **not praise answers** and not offer hints unless asked
- **interrupt vagueness and probe for specifics** — two to three follow-ups per
  question is what makes it feel real
- be sceptical of unquantified claims
- reserve all feedback until the session ends
- enforce a visible time limit and disallow re-recording an answer

Follow-up probes are the single biggest realism upgrade. Real interviewers do not
accept the first answer.

## Question categories

**Screening** — motivation, why this company, why leaving, salary expectation,
notice period, language level, relocation.

**Behavioural (STAR)** — conflict with a colleague; a failure and what was
learned; influencing without authority; a tight deadline; disagreeing with a
senior decision; handling ambiguous requirements; delivering bad news to a
customer; a time you were wrong.

**Technical deep-dive** — role-specific and drawn from the actual job posting
where possible. Examples: design a secure OTA update flow for an ECU; a
Kubernetes cluster is throttling at 03:00, walk me through the diagnosis;
your RAG system returns confident but wrong answers, how do you find out why.

**Stress** — challenge a claim on the CV; ask about a gap or a career change;
push back on an answer just given to see whether the candidate holds or folds.

**Reverse** — "what questions do you have for me?" Candidates fail this
constantly. Strong questions are specific to the team, the codebase, the
roadmap, or how success is measured in the first six months.

## Career-transition and gap questions

Candidates changing specialism or returning from a break should have prepared,
non-defensive answers for:

- Why the change, and what evidence supports readiness — projects, study,
  transferable work
- What was done during a career break to stay current
- How a background in an adjacent field is an advantage rather than a deficit
- Which skills are genuinely still developing, and the concrete plan for them

The strongest form is brief, factual, forward-looking, and does not apologise.
Preparing these deliberately matters more than preparing the technical answers,
because they are the ones asked cold.

## Delivery metrics for spoken practice

Beyond content, spoken answers should be measured on:

- **Filler-word rate** — "um", "like", "basically", "ähm", "genau" per minute
- **Pace** — words per minute; flag above ~170 (rushing) or below ~110 (dragging)
- **Answer length** — against the question's expected duration
- **Hesitation** — silence before starting

These are the specific gap between typing an answer and speaking one, and they
are invisible in text-only practice.
