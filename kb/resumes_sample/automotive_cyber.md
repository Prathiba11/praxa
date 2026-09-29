# Ines Rothgeb

Böblingen, Germany · ines.rothgeb@example.invalid · +49 000 0000000

_Sample CV. Ines Rothgeb is not a real person and none of the employers below
exist. This file ships with the repository so that a reviewer who clones it can
run the whole application without needing anyone's real CV._

## Summary

Automotive cybersecurity engineer, six years, split between building the
process side of a CSMS and doing the hands-on testing that proves it means
something. Has taken two ECU programmes through TARA and into type approval.
Reads a standard as a set of obligations to evidence, not a document to cite.

## Cybersecurity Engineer — Auerbach Fahrzeugtechnik GmbH

_Böblingen · January 2023 – present_

- Ran the TARA for a body-domain controller under ISO/SAE 21434: 41 damage
  scenarios, 63 threat scenarios, attack-feasibility rated with the attack-
  potential method. Nine of the resulting requirements changed the architecture
  rather than being closed with a note.
- Wrote the cybersecurity interface agreement with two tier-2 suppliers, which
  was the first time the programme had a written split of who evidences what.
- Built the ECU security test bench: CAN fuzzing over a Vector-style interface,
  UDS service enumeration, secure-boot fault injection with a glitcher. Found a
  diagnostic session that stayed unlocked after a reset — reported, fixed, and
  added as a regression case.
- Prepared the UNECE R155 evidence pack for type approval. The audit closed with
  no major findings; the two minors were both documentation, not technical.
- Introduced a monthly vulnerability triage covering the SBOM for four ECUs,
  replacing an ad-hoc process that had missed a known OpenSSL advisory by five
  weeks.

## Security Test Engineer — Kernfeld Systems GmbH

_Ingolstadt · April 2020 – December 2022_

- Penetration testing of infotainment and telematics units: Bluetooth pairing
  flows, Wi-Fi provisioning, the OTA update path.
- Demonstrated a downgrade attack on an OTA client that accepted an older signed
  bundle. The fix — a monotonic version counter in secure storage — became a
  platform requirement across the product line.
- Built the automated regression suite for secure diagnostics, 180 cases, run
  nightly against three ECU variants.
- Wrote the internal training on ASPICE and its relationship to cybersecurity
  work products, delivered to about 40 engineers.

## Junior Embedded Engineer — Steinlach Elektronik

_Reutlingen · October 2018 – March 2020_

- AUTOSAR Classic development on a gateway ECU, mostly CAN and LIN stack work.
- Moved into security after taking on the secure-boot integration nobody else
  wanted, which turned out to be the interesting part of the job.

## Skills

**Standards** ISO/SAE 21434, UNECE R155/R156, ISO 26262 (interfaces), ASPICE
**Analysis** TARA, attack trees, attack-potential rating, SBOM and CVE triage
**Testing** CAN/LIN fuzzing, UDS enumeration, secure-boot fault injection,
side-channel basics
**Embedded** AUTOSAR Classic, C, HSM integration, secure storage
**Tooling** CANoe-style bus tooling, Ghidra, custom Python harnesses

## Education

**MSc Embedded Systems Engineering** — Universität Freiburg, 2018
**BEng Electrical Engineering** — Hochschule Esslingen, 2016

## Certifications

- ISO/SAE 21434 Cybersecurity Engineer (TÜV-style training certificate), 2022
- OSCP, 2021

## Languages

German (native), English (C1), French (B1)
