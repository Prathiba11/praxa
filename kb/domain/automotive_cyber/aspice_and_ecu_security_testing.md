# Automotive SPICE and ECU Security Testing

Personal reference summary covering two adjacent topics: the process assessment
model customers are measured against, and the hands-on testing discipline.

## Part 1 — Automotive SPICE (ASPICE)

### What it is

A process assessment model published by the VDA Quality Management Centre, built
on the ISO/IEC 330xx family of process assessment standards. It does not tell an
organisation *what* to build; it assesses *how capably* it performs defined
engineering processes. OEMs use it as a supplier qualification gate, so a
supplier's assessed capability level has direct commercial consequences.

### Capability levels

| level | name | in plain terms |
|---|---|---|
| 0 | Incomplete | the process is not performed, or fails to achieve its purpose |
| 1 | Performed | the work gets done and the outputs exist |
| 2 | Managed | the work is planned, monitored, and its work products are controlled |
| 3 | Established | a defined standard process exists and is tailored per project |
| 4 | Predictable | the process is quantitatively measured and controlled |
| 5 | Innovating | the process is continuously improved against business goals |

Most automotive supplier programmes target **Level 2 or Level 3**. Levels 4 and 5
are rare in practice.

The step most organisations find hardest is 1 → 2: not doing the work, but
demonstrating that it was planned, tracked, reviewed, and that its outputs were
under configuration control with bidirectional traceability.

### Process scope

Assessments cover a selected scope of processes, typically spanning system and
software engineering along the V-model — requirements elicitation, system and
software requirements analysis, architectural design, detailed design and unit
construction, and the corresponding verification, integration and qualification
test processes — plus supporting and management processes such as project
management, quality assurance, configuration management, problem resolution and
change request management, and supplier monitoring.

### Cybersecurity and ASPICE

Cybersecurity engineering processes have their own assessment treatment, and
recent versions of the model restructured how security is handled. Since the
detail here changes between model versions, **confirm which version and which
process scope an assessment is being run against** rather than assuming — this is
a recurring source of confusion in customer projects.

The conceptual relationship is stable, though: ISO/SAE 21434 says which
cybersecurity processes must exist; ASPICE assesses how capably they are
performed. The two are complementary, and evidence gathered for one is largely
reusable for the other.

### Practical observations

- **Traceability is the recurring finding.** Requirement → architecture → design
  → test → result, in both directions, with change history. Teams do the
  engineering and fail the traceability.
- **Consistency across projects is what Level 3 actually means.** One well-run
  project does not establish a process.
- **Tooling shapes outcomes.** Codebeamer, DOORS and similar tools make
  traceability demonstrable; spreadsheets rarely survive an assessment.
- **Assessment preparation is not a documentation exercise.** Retrofitted evidence
  is visible to an experienced assessor.

## Part 2 — ECU Security Testing

### Test knowledge categories

- **Black box** — no internal knowledge. Realistic attacker simulation, but
  inefficient and prone to missing reachable weaknesses.
- **White box** — full access to source, design and keys. Efficient and thorough,
  but can drift away from realistic attack paths.
- **Grey box** — partial knowledge: interface specifications, architecture,
  possibly some source. The pragmatic industry default, because it directs effort
  at plausible attack paths without wasting time on discovery the attacker would
  also skip.

### Typical ECU attack surface

- **CAN / CAN FD** — no authentication or encryption by design. Spoofing,
  replay, flooding and denial of service. SecOC (Secure Onboard Communication)
  adds authentication where deployed.
- **Automotive Ethernet** — larger surface; standard IP-layer attack classes
  apply alongside automotive protocols such as SOME/IP.
- **Diagnostics (UDS over CAN or DoIP)** — security access seed/key strength,
  session and state-machine handling, service-level authorisation, brute-force
  and lockout behaviour. A frequently productive area.
- **Bootloader and secure boot** — signature verification, rollback protection,
  debug interface lockdown.
- **Debug interfaces** — JTAG/SWD left enabled in production is a classic finding.
- **Key and credential storage** — HSM usage versus keys in flash; key
  provisioning and diversification.
- **Wireless and OTA** — Bluetooth, Wi-Fi, telematics; update authentication and
  integrity.
- **Supply-chain and third-party components** — known-vulnerable library versions.

### Method

1. **Scope and preparation** — interface specifications, architecture, prior TARA
   output. Derive test objectives from identified threat scenarios so the campaign
   is traceable rather than exploratory.
2. **Test concept and case design** — per interface, per threat scenario, with
   both positive and negative cases. Vector CANoe and vTESTstudio for automated
   execution; test cases held under version control.
3. **Execution** — fuzzing, spoofing, replay, malformed frames, state-machine
   abuse, timing and boundary conditions.
4. **Vulnerability analysis** — map findings against CVE and CWE entries so they
   are classified rather than merely described. CWE mapping is what makes a
   finding actionable for developers.
5. **Reporting** — reproducible steps, severity with a stated rating basis,
   affected component and interface, and concrete remediation guidance. Findings
   are presented directly to the customer's development team.

### Practical observations

- **Traceability from TARA to test case is what distinguishes a security test
  campaign from ad-hoc probing** — and it is what an assessor asks for.
- **Negative testing finds more than positive testing.** Malformed input,
  out-of-sequence requests and invalid state transitions are where implementations
  fail.
- **Diagnostic services are consistently productive.** Weak security access,
  missing authorisation checks and inadequate lockout behaviour recur across
  suppliers.
- **Reporting quality determines whether findings get fixed.** A finding a
  developer cannot reproduce does not get remediated. Structured documentation and
  direct presentation to the development team, rather than a report thrown over
  the wall, is what closes the loop.
- **Automation pays back across projects.** Reusable test suites in vTESTstudio
  turn a bespoke campaign into a repeatable capability.
