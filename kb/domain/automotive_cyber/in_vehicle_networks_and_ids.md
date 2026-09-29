# In-Vehicle Networks and Intrusion Detection

Personal reference summary. Bus specifics and AUTOSAR module names should be
checked against the release in use on a given programme.

## Why the network is the interesting attack surface

An ECU compromised in isolation is a contained problem. An ECU that can put
arbitrary frames on a bus shared with braking, steering and powertrain is a
vehicle-level problem. Most published automotive attacks follow the same shape:
get code execution somewhere weakly defended and reachable — infotainment, a
telematics unit, a tyre-pressure receiver — then use the internal network to
reach something that matters.

That shape is why segmentation and message authentication earn their cost, and
why "the ECU is not internet-facing" is a weak argument on its own.

## CAN and CAN FD

Classical CAN is a broadcast, multi-master bus with priority arbitration by
identifier: the lower the ID, the higher the priority. CAN FD raises the payload
from 8 to 64 bytes and allows a faster data phase.

The security-relevant properties are properties of the design, not defects:

- **No sender authentication.** A frame carries an identifier, not an origin. Any
  node on the bus can emit any ID.
- **Broadcast by default.** Every node sees every frame.
- **Arbitration can be abused.** A node that continuously transmits a
  low-numbered ID starves higher-numbered traffic — a denial of service that
  needs no defect at all, only bus access.
- **Error handling can be abused.** Deliberately induced error frames can push a
  target node into bus-off, silencing it.

None of this is fixable inside CAN. It is mitigated above it, or by not putting
untrusted nodes on the same bus.

## Automotive Ethernet

100BASE-T1 and 1000BASE-T1 carry high-bandwidth traffic — cameras, lidar, zonal
architectures, diagnostics over IP. Switched rather than broadcast, which allows
real segmentation, VLANs and port-level policy. AVB and TSN provide the bounded
latency that control traffic needs.

It also imports the ordinary IP attack surface: ARP and DHCP behaviour, service
discovery, and the SOME/IP middleware used for service-oriented communication.
DoIP diagnostics deserve particular attention, because a diagnostic channel is by
design a way to reach things the normal application layer will not let you reach.

## Gateways and domain separation

The central or zonal gateway is the control point: it routes between buses and
should enforce which messages may cross which boundary, in which direction, at
what rate. A gateway that forwards by default is a network with no segmentation
and an extra hop.

Three rules that hold up in review:

1. **Deny by default across a domain boundary**, with an explicit routing table.
2. **Rate-limit what is allowed through**, so a compromised low-criticality
   domain cannot flood a high-criticality one.
3. **Treat diagnostics as a separate privilege**, gated by authentication and by
   vehicle state, not merely by a session identifier.

## SecOC

**Secure Onboard Communication** is the AUTOSAR mechanism for authenticating
critical bus messages. Each protected message carries a truncated MAC and a
freshness value; receivers verify both and discard frames that fail.

The two design tensions are worth being able to discuss:

- **Truncation.** A full MAC does not fit in a CAN payload alongside the data, so
  the MAC is truncated — often to 24 or 32 bits. That is a deliberate trade of
  forgery resistance against payload space, and it is acceptable only because a
  forgery must also be produced in real time, on the bus, against a moving
  freshness value.
- **Freshness management.** Replay protection depends on sender and receiver
  agreeing on a freshness value. Resynchronisation after reset, after sleep, and
  for a node that joins late is the hard part, and it is where implementations
  diverge and interoperability bugs appear.

Key management is the unglamorous half: per-vehicle keys, provisioning in
production, storage in an HSM, and a rotation story that survives an ECU
replacement in a workshop.

## Hardware security modules

An HSM or Secure Hardware Extension provides key storage that application
software cannot read, cryptographic acceleration, and a root of trust for secure
boot. It is what makes a claim like "the key never leaves the device" mean
something.

Secure boot verifies each stage before executing it, anchored in immutable boot
ROM. Distinguish it from **measured** boot, which records what was loaded for
later attestation without necessarily refusing to run it; the two answer
different questions and are often conflated.

## Intrusion detection in a vehicle

UNECE R155 expects a manufacturer to detect and respond to attacks across the
fleet, which in practice means an **IDPS** on the vehicle feeding a backend.

Detection approaches, roughly in order of maturity:

- **Rate and timing anomalies.** Most CAN traffic is strictly periodic, so a
  message arriving at twice its expected frequency, or an ID appearing that this
  bus has never carried, is a strong and cheap signal.
- **Specification-based checks.** Signals outside their defined range, or state
  transitions the specification forbids.
- **Payload and sequence models.** Learned models of normal traffic. More
  expressive, and considerably harder to defend in an audit when they fire.

Three constraints shape everything here. The ECU has little memory and no spare
CPU. A false positive that disables a function is a safety event of its own, so
in-vehicle detection is usually exactly that — detection, with response taken by
the backend or at the next service. And an event is useless without enough
context to triage it, while a vehicle fleet cannot afford to upload much: the
volume-versus-usefulness trade is the design problem, not a detail.

## Practical observations

- **Ask what shares a bus before asking what is encrypted.** Segmentation
  prevents more than cryptography does, and costs less to argue for.
- **SecOC on every message is neither affordable nor necessary.** Protect the
  messages whose forgery has a safety or security consequence, and write down why
  the others were excluded — that list is what an assessor will ask about.
- **The diagnostic path is the one that gets forgotten.** It is designed to
  bypass normal restrictions, it is present in production, and seed-and-key
  algorithms recovered from one ECU tend to work on the whole fleet.
- **An IDS with no response path is telemetry.** The interesting design question
  is what the backend does with the event, and who is on call.
