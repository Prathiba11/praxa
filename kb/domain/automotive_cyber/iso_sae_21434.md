# ISO/SAE 21434 — Road Vehicles: Cybersecurity Engineering

Personal reference summary. Verify clause numbering and requirement wording
against the published standard before using it in a customer deliverable.

## What the standard is for

ISO/SAE 21434:2021 defines cybersecurity engineering requirements across the
entire lifecycle of road-vehicle electrical and electronic systems — concept,
development, production, operation, maintenance and decommissioning. It is a
*process* standard: it does not prescribe technical controls, it prescribes the
engineering discipline by which a manufacturer decides which controls are needed
and demonstrates that decision was made competently.

It is the technical backbone for demonstrating conformity to UNECE R155, which is
the regulation that actually gates type approval.

## Structure

Broadly:

- **Organisational cybersecurity management** — policy, rules and processes,
  competence management, a cybersecurity culture, tool management, information
  sharing, and organisational cybersecurity audit
- **Project-dependent cybersecurity management** — cybersecurity planning, the
  cybersecurity case, cybersecurity assessment, release for post-development
- **Distributed cybersecurity activities** — supplier capability evaluation and
  the Cybersecurity Interface Agreement (CIA) that allocates responsibilities
  between customer and supplier
- **Continual cybersecurity activities** — cybersecurity monitoring, event
  assessment, vulnerability analysis and vulnerability management. These run
  independently of any single project and continue after start of production.
- **Concept phase** — item definition, cybersecurity goals and claims,
  cybersecurity concept
- **Product development** — requirements refinement, design, integration and
  verification at hardware and software level
- **Cybersecurity validation** — validating the vehicle-level cybersecurity goals
- **Production** — the production control plan
- **Operations and maintenance** — incident response, and updates
- **End of cybersecurity support and decommissioning**
- **Threat analysis and risk assessment (TARA) methods** — the analytical core

## TARA: the analytical core

The risk assessment methods are the part practitioners spend most time in. The
sub-methods can be applied individually or as a full chain:

1. **Asset identification** — identify assets with cybersecurity properties
   (confidentiality, integrity, availability) and their damage scenarios
2. **Threat scenario identification** — what could compromise which property of
   which asset. STRIDE is commonly used as the elicitation aid.
3. **Impact rating** — rate damage scenarios across four categories:
   **Safety, Financial, Operational and Privacy (S/F/O/P)**, each as negligible,
   moderate, major or severe
4. **Attack path analysis** — the routes by which a threat scenario can be
   realised; top-down (deductive, e.g. attack trees) or bottom-up (inductive)
5. **Attack feasibility rating** — how feasible each path is. Three recognised
   approaches: attack-potential-based (elapsed time, expertise, knowledge of the
   item, window of opportunity, equipment), CVSS-based, or attack-vector-based.
6. **Risk value determination** — combine impact and attack feasibility into a
   risk value, conventionally 1–5
7. **Risk treatment decision** — avoid, reduce, share/transfer, or retain the
   risk. Retained risks must be justified and recorded.

The output feeds cybersecurity goals, which become cybersecurity requirements,
which become design and test artefacts. Traceability across that chain is what an
assessor looks for.

## Cybersecurity Assurance Level (CAL)

CAL is a scheme (CAL1–CAL4) for scaling the *rigour* of assurance activities
according to the impact and attack-vector characteristics of an item. It is
informative rather than a hard requirement, and it is frequently misunderstood as
being analogous to ASIL — it is not a risk classification of the item, it is a
guide to how much assurance effort is warranted.

## The cybersecurity case

The cumulative argument, with supporting evidence, that the item is
cybersecurity-adequate. It is assembled through development rather than written
at the end, and it is the artefact a cybersecurity assessment interrogates.

## Practical observations from project work

- **Item definition quality determines everything downstream.** A vague boundary
  produces a TARA that is either unmanageably broad or misses interfaces.
- **Impact rating is where stakeholders disagree most.** Safety impact is usually
  uncontroversial; financial and operational ratings are negotiated. Recording the
  rationale matters more than the number.
- **Attack feasibility is where analyses become inconsistent between engineers.**
  Fixing the rating approach and its scale up front, per project, avoids
  irreconcilable results later.
- **Interface-first analysis is a pragmatic strategy under deadline pressure** —
  analysing external communication interfaces (CAN, Ethernet, diagnostics, OTA,
  wireless) before internal decomposition, because that is where realistic attack
  paths enter.
- **The Cybersecurity Interface Agreement is often the real bottleneck** in
  OEM–supplier work: unclear responsibility allocation surfaces late, usually
  during assessment preparation.
- **Continual activities are the requirement organisations underestimate.**
  Monitoring, triage and vulnerability management need staffing and tooling long
  after the project team has moved on.

## Relationship to neighbouring standards

- **UNECE R155 / R156** — the regulations. 21434 is how you demonstrate the
  engineering competence they require.
- **ISO 26262** — functional safety. Different hazard source (random and
  systematic failure versus deliberate attack), but overlapping architecture and
  shared work products. Safety and security analyses should be coordinated, since
  a security control can compromise a safety goal and vice versa.
- **Automotive SPICE** — process capability assessment. 21434 says *what*
  processes are needed; ASPICE assesses *how capably* they are performed.
- **ISO/PAS 5112** — guidance for auditing cybersecurity engineering.
