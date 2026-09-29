# SRE Practices and DORA Metrics

Personal reference summary. These are the vocabulary and measurement frameworks
DevOps and platform interviews assume.

## Site Reliability Engineering: the core idea

Reliability is a feature with a cost, and perfect reliability is the wrong target
because the last fraction of a percent costs more than it is worth. So you set an
explicit reliability target, measure against it, and spend the remainder on
change.

### SLI, SLO, SLA

- **SLI — Service Level Indicator.** A measurement of behaviour users care about.
  Good SLIs are user-facing: request success rate, latency at the 95th or 99th
  percentile, freshness of data. Bad SLIs measure the system rather than the
  experience — CPU utilisation tells you nothing about whether users are served.
- **SLO — Service Level Objective.** The target for an SLI, internal. "99.9% of
  requests succeed over a rolling 30 days."
- **SLA — Service Level Agreement.** A contractual promise to a customer, with
  consequences for breach. Always set looser than the SLO, so you notice trouble
  before it costs money.

Percentile matters. A mean latency of 200 ms can hide a p99 of eight seconds,
which is the experience of your most active users.

### Error budget

The inverse of the SLO. A 99.9% target over 30 days permits roughly 43 minutes of
unavailability. That allowance is the **error budget**, and it turns reliability
from an argument into arithmetic:

- Budget remaining → ship features, take risks, deploy faster
- Budget exhausted → change freeze, reliability work only, until it recovers

This is the mechanism that stops "move fast" and "be reliable" being a permanent
political fight between product and operations.

### Toil

Manual, repetitive, automatable work that scales linearly with service growth and
carries no enduring value. Restarting a service by hand, applying the same
configuration fix weekly, copying numbers into a report. SRE practice caps the
proportion of time spent on toil (commonly 50%) so that automation actually gets
built rather than perpetually deferred.

Distinguishing toil from genuine engineering work is a useful interview
discussion — not all manual work is toil, and not all automation is worth
building.

### Blameless postmortems

After an incident, a written analysis focused on the systemic causes, not the
individual who typed the command. The premise: competent people acting reasonably
within a system produced a bad outcome, so the system is what needs changing.
Blame suppresses information, and suppressed information means the next incident
is a surprise too.

A useful postmortem contains: timeline, user impact, contributing causes,
what went well, what was luck rather than design, and dated action items with
owners. "Human error" as a root cause is a sign the analysis stopped too early.

### On-call

Sustainable rotations, alerts that are actionable (an alert nobody can act on is
a bug), runbooks for known conditions, and escalation paths. Alert fatigue is a
reliability risk in itself: a team that has learned to ignore pages will ignore
the important one.

## DORA metrics

From the DevOps Research and Assessment programme — the four measures that
correlate with software delivery performance. They are useful because they are
hard to game individually: optimising one at the expense of another shows up.

**Throughput**

1. **Deployment frequency** — how often you release to production. Elite
   performers deploy on demand, multiple times per day.
2. **Lead time for changes** — commit to running in production. Elite: under an
   hour.

**Stability**

3. **Change failure rate** — the percentage of deployments causing degraded
   service requiring remediation. Elite: 0–15%.
4. **Time to restore service** — how long recovery takes. Elite: under an hour.

Later research added **reliability** as a fifth measure, covering the extent to
which operational performance meets user expectations.

*(Elite/high/medium/low thresholds shift between annual reports — cite them as
approximate rather than fixed.)*

### The insight worth stating in an interview

The intuition is that speed trades against stability. The DORA finding is the
opposite: **the same practices improve both.** Small batches, automated testing,
trunk-based development, loose coupling and fast feedback make deployments both
more frequent and less likely to break — because a small change is easier to
verify, easier to reason about, and easier to revert.

### How they get misused

- **Measuring teams against each other.** Contexts differ; the metrics are for a
  team's own trend line.
- **Optimising deployment frequency alone.** Deploying more often while the
  failure rate climbs is not improvement.
- **Treating them as a maturity score** rather than a diagnostic. The value is in
  asking *why* lead time is long, not in the number itself.

## Observability

Distinguish **monitoring** — watching known failure modes with predefined
dashboards and alerts — from **observability**, the ability to answer questions
about the system you did not anticipate needing to ask.

The three pillars:

- **Metrics** — numeric time series, cheap to store, good for alerting and trends.
  Prometheus is the common choice; Grafana the common visualisation layer.
- **Logs** — discrete events with detail. Expensive at volume. Structured (JSON)
  logs are queryable; free-text logs are not.
- **Traces** — a request's path across services, with timing per hop. The tool for
  latency problems in distributed systems.

Correlation is what makes them useful: a trace ID or correlation ID carried
through logs, metrics labels and traces means an alert leads to the specific
failing request rather than to a dashboard you then have to interpret.

## Practical observations

- **Dashboards nobody looks at are wasted work.** A dashboard should answer a
  specific question someone actually asks.
- **The first useful SLO is usually availability of the main user-facing path.**
  Starting with a comprehensive SLO framework rarely survives contact with
  reality.
- **Metrics used for internal engineering analysis are as valuable as alerting
  metrics** — build durations, queue times, failure rates by stage. That is how you
  find out where delivery actually slows down, rather than guessing.
- **In regulated environments, observability data doubles as evidence.** Build
  provenance, deployment records and monitoring history are exactly what a process
  audit asks for, and generating them automatically beats reconstructing them.
