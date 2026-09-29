# UNECE R155 and R156 — Cybersecurity and Software Update Regulation

Personal reference summary. Verify dates, applicability and annex content against
the current regulation text before using it in a customer deliverable.

## Why these matter more than the standards

ISO/SAE 21434 is voluntary. **UN Regulation No. 155 is law** in the contracting
parties to the UNECE 1958 Agreement — which includes the EU, Japan, South Korea
and the UK. Without conformity, a manufacturer does not get vehicle type approval,
and without type approval the vehicle cannot be sold. This is the commercial
pressure behind every automotive cybersecurity project.

## R155 — Cyber Security and Cyber Security Management System

Two distinct approvals are involved, and confusing them is a common error:

**1 · CSMS certificate of compliance.** An organisational approval. The
manufacturer must demonstrate a Cyber Security Management System — processes for
managing cyber risk across development, production and post-production, including
risk assessment, mitigation, testing, monitoring of cyber attacks and threats,
incident response, and the ability to analyse and respond to new vulnerabilities.
The CSMS is audited and certified, and must be periodically re-assessed.

**2 · Vehicle type approval.** Per vehicle type, the manufacturer must show that
the risks identified for that type have been assessed and appropriately managed,
that the vehicle is protected against the threats listed in the regulation's
annex, and that monitoring and response capability covers it.

So: the CSMS proves the organisation is competent; type approval proves a specific
vehicle was engineered accordingly.

## The threat annex

R155 includes an annex enumerating vulnerabilities, threats and corresponding
mitigations, organised by target — back-end servers, communication channels,
update procedures, unintended human actions, external connectivity, vehicle data
and code, and potential vulnerabilities that could be exploited if insufficiently
protected.

Practically, this annex functions as a **checklist that a TARA must demonstrably
cover.** A TARA that produces excellent analysis but cannot be mapped to the
annex categories creates avoidable work during approval. Building the mapping into
the TARA template from the start is worth the effort.

## R156 — Software Update and Software Update Management System

The companion regulation, covering software updates including over-the-air
updates. Also two-part:

**1 · SUMS certificate of compliance.** Processes for managing software updates:
configuration and version identification, verifying an update's compatibility
with the target vehicle, recording target vehicles, assessing whether an update
affects type-approved systems, informing users, and documenting the update.

**2 · Type approval**, showing the vehicle type's update mechanism meets the
requirements — including that updates cannot be applied unsafely (for example,
while driving, or with insufficient battery), that a failed update leaves the
vehicle in a safe state, and that RXSWIN identifiers track approval-relevant
software versions.

**RXSWIN** — Regulation X Software Identification Number — is the mechanism
linking a software version to a specific regulatory approval. If an update
changes approval-relevant software, the RXSWIN changes, and approval implications
must be assessed. This is the concept most teams underestimate.

## Applicability timeline

Within the EU, R155 and R156 applied to new vehicle *types* from July 2022, and
to all newly registered vehicles from July 2024. The practical consequence was a
compliance rush in 2021–2024 and a shift afterwards from initial certification
work toward maintaining CSMS and SUMS operations and handling post-production
vulnerability management.

Timelines differ per contracting party; check the specific market.

## How R155 relates to the Cyber Resilience Act

The **EU Cyber Resilience Act (CRA)** sets horizontal cybersecurity requirements
for products with digital elements sold in the EU, with obligations including
security-by-design, vulnerability handling and reporting duties, and a support
period. The automotive sector's relationship to CRA is shaped by the existence of
the R155/R156 regime and sector-specific legislation, so which obligations bite
in which combination is genuinely intricate — verify current interpretation rather
than assuming, particularly for suppliers of components rather than whole
vehicles.

For adjacent sectors — agricultural and construction machinery, medical devices —
the picture differs again, which is why customers in those sectors often need
help mapping automotive-derived practice onto their own regulatory frame.

## Practical observations from project work

- **The CSMS audit and the engineering work run on different clocks.** Teams
  often have good technical analysis and thin process evidence, or vice versa.
  Both are assessed.
- **Evidence quality beats analysis quality at approval time.** An assessor cannot
  credit reasoning that was not recorded. Work products, traceability and version
  history are what gets examined.
- **Suppliers are pulled into a regime designed around OEMs.** Component
  suppliers must produce CSMS-conformant work products without holding the type
  approval, which makes the Cybersecurity Interface Agreement the pivotal
  document.
- **Post-production is the sustained cost.** Monitoring, triage and reporting
  obligations continue for the vehicle's support life, long after the development
  team disbands. Organisations consistently under-resource this.
- **"Compliant" is not a state, it is an ongoing activity.** A certificate lapses
  without maintained monitoring and re-assessment.
