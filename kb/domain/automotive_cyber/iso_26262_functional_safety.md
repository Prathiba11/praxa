# ISO 26262 — Road Vehicles: Functional Safety

Personal reference summary. Verify part and clause numbering against the
published standard before using it in a customer deliverable.

## What the standard is for

ISO 26262 covers **functional safety** of electrical and electronic systems in
production road vehicles: the absence of unreasonable risk caused by malfunctions
of those systems. The current edition is ISO 26262:2018, the second edition,
published in twelve parts. The first edition of 2011 covered passenger cars up to
3.5 tonnes; the 2018 edition widened scope to trucks, buses, trailers and
motorcycles, and added Part 11 on semiconductors and Part 12 on adaptations for
motorcycles.

It is an adaptation of IEC 61508 for the automotive domain. Where IEC 61508 uses
Safety Integrity Levels, ISO 26262 uses **ASILs**, and the derivation is
automotive-specific.

## The distinction from cybersecurity

This is the question most often asked badly in interviews, so it is worth being
precise.

- **ISO 26262 addresses malfunction.** A component fails, a bit flips, software
  takes a wrong branch, and the vehicle behaves unsafely. The threat model is
  random hardware faults and systematic development faults. Nobody is trying to
  cause it.
- **ISO/SAE 21434 addresses attack.** Somebody *is* trying to cause it, and they
  adapt when you defend.

The practical consequence: a safety argument may assume a fault is random and
reason about failure rates. A security argument may not — an attacker will pick
the worst case deliberately, and repeat it. A single fault metric means nothing
against an adversary who can trigger that fault at will.

They meet where a security failure causes a safety consequence, which is most of
the interesting cases. A TARA that identifies a safety impact should trace to the
relevant safety goal, and a hazard whose cause could be induced remotely belongs
in both analyses. The two processes remain separate; the artefacts reference each
other.

## ASIL: how a hazard gets a level

An ASIL is assigned to a **hazardous event** — a hazard in an operational
situation — not to a component. Three parameters combine:

- **Severity (S0–S3)** — S0 no injuries, S3 life-threatening or fatal injuries
- **Exposure (E0–E4)** — how often the operational situation occurs, E0 being
  incredibly unlikely and E4 being a high probability
- **Controllability (C0–C3)** — whether the driver or other road users can act to
  avoid harm. C0 is controllable in general, C3 is difficult to control or
  uncontrollable.

The combination yields **QM, ASIL A, B, C or D**, where QM means quality
management alone is sufficient and ASIL D carries the most stringent
requirements. D arises only from the severe end of all three: a life-threatening
outcome, in a situation that occurs often, that the driver cannot escape.

Two consequences engineers get wrong:

1. **QM is not "no requirements".** It means the hazard is handled by ordinary
   development quality rather than the safety lifecycle. It still has to be
   developed competently.
2. **The level is an argument, not a measurement.** S, E and C are engineering
   judgements made by a team and recorded with rationale. An ASIL assignment
   without written reasoning is not defensible in assessment.

## The safety lifecycle in outline

- **Concept phase** — item definition, then the **Hazard Analysis and Risk
  Assessment (HARA)**, which produces the hazardous events, their ASILs and the
  **safety goals**. A safety goal is a top-level safety requirement stated at
  vehicle level, and it inherits the ASIL of its hazardous event.
- **Functional safety concept** — safety goals refined into functional safety
  requirements, allocated to architecture, with fault-handling and warning
  strategies, and the **fault tolerant time interval** within which a fault must
  be handled before the hazard occurs.
- **Product development at system, hardware and software level** — the two sides
  of the classic V, with verification at each level.
- **Production, operation, service and decommissioning.**
- **Supporting processes** — configuration and change management, verification,
  documentation, qualification of software tools, and the **safety case**: the
  structured argument, supported by evidence, that the item is acceptably safe.

## ASIL decomposition

A requirement at a high ASIL can be decomposed onto two sufficiently independent
elements at lower ASILs — for example ASIL D onto ASIL B(D) and ASIL B(D), or
onto ASIL D(D) and QM(D). The bracketed level records the original requirement,
which is what makes the decomposition traceable.

The independence claim is the whole argument, and it is where decompositions
fail. Two channels sharing a power supply, a clock, a microcontroller or a
development team are not independent, and a **Dependent Failure Analysis** is
required to show that common-cause and cascading failures have been considered.
Decomposition that only exists on a slide is a way of reducing paperwork rather
than risk.

## Hardware metrics

For ASIL B and above, ISO 26262 asks for quantitative hardware evidence:

- **Single Point Fault Metric (SPFM)** — the fraction of hardware failure rate
  that is not single-point or residual
- **Latent Fault Metric (LFM)** — the fraction that is not latent
- **Probabilistic Metric for random Hardware Failures (PMHF)** — an overall
  failure rate target, expressed in FIT

The targets rise with ASIL. The numbers depend on a failure rate database and on
diagnostic coverage claims, and both are assumptions: a metric computed from an
optimistic diagnostic coverage figure is an optimistic metric.

## Software-level expectations

The standard recommends rather than mandates, with the strength of the
recommendation rising by ASIL: a coding standard such as MISRA C, enforced
statically; restricted use of dynamic memory, recursion and unstructured control
flow; freedom from interference between software partitions of different ASILs,
typically through memory protection and timing protection; and structural
coverage evidence, with MC/DC expected at ASIL D.

Note the pattern — at higher ASILs the standard asks for *more evidence about the
same code*, not different code.

## Practical observations

- **The HARA is the document everything else rests on.** An item definition that
  quietly excludes an operational situation removes every hazard that would have
  come from it, and nothing downstream will notice.
- **Tool qualification is where schedules disappear.** A tool that could
  introduce or fail to detect a fault needs a confidence argument, and that
  includes code generators, compilers and test tools.
- **A safety case is written throughout, not assembled at the end.** A safety
  case produced in the last month of a programme is a document about a process
  that did not happen.
- **Freedom from interference is claimed far more often than it is shown.**
  Memory protection is the easy half; timing and execution-order interference on
  a shared core is the half that gets waved through.
