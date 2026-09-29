# Marek Duvall

Stuttgart, Germany · marek.duvall@example.invalid · +49 000 0000000

_Sample CV. Marek Duvall is not a real person and none of the employers below
exist. This file ships with the repository so that a reviewer who clones it can
run the whole application without needing anyone's real CV._

## Summary

Platform engineer, seven years, mostly on the boundary between application
teams and the infrastructure they deploy onto. Comfortable owning a CI system
end to end and unpicking why a deployment that worked in staging does not work
in production. Prefers making the slow thing measurable before making it fast.

## Senior Platform Engineer — Nordwerk Mobility GmbH

_Stuttgart · March 2022 – present_

- Migrated 34 services from a hand-rolled Jenkins estate to GitLab CI with a
  shared pipeline template. Median build time fell from 19 minutes to 6, and the
  number of pipeline definitions teams maintained themselves went from 34 to 1.
- Introduced progressive delivery with Argo Rollouts. Two releases were rolled
  back automatically on error-rate breach in the first quarter, neither of which
  reached more than 5% of traffic.
- Owned the Kubernetes upgrade path across three clusters, 1.24 through 1.28,
  with no unplanned downtime. Wrote the deprecation-scan step that now blocks a
  merge if a manifest uses an API version removed in the next release.
- Cut observability spend 38% by sampling traces by route rather than uniformly,
  after showing that 71% of the volume came from two health-check endpoints.
- Ran the on-call handbook rewrite. Median time-to-acknowledge fell from 14
  minutes to 4 once alerts carried a runbook link and a named owner.

## DevOps Engineer — Talstrom Logistik AG

_Karlsruhe · August 2019 – February 2022_

- Built the Terraform module library the platform team still uses: networking,
  RDS, IAM roles, each with a golden-path example and a policy test.
- Replaced overnight snapshot restores with continuous replication to a warm
  standby, taking the tested recovery point from 24 hours to 15 minutes.
- Containerised a Java monolith that had been deployed by hand for six years.
  Deployment went from a two-person, ninety-minute ritual to a merge.
- Set up the first SLOs the company had: availability and latency for the four
  customer-facing services, with error budgets reviewed monthly.

## Systems Administrator — Halbmond Verlag

_Mannheim · September 2017 – July 2019_

- Ran the VMware estate and the backup regime for a 200-person publisher.
- Automated user provisioning with Ansible, removing a recurring two-day task
  from every onboarding week.
- First exposure to infrastructure as code, and the reason for the move to
  platform work.

## Skills

**Orchestration** Kubernetes, Helm, Argo CD, Argo Rollouts
**CI/CD** GitLab CI, GitHub Actions, Jenkins (legacy estates)
**Infrastructure as code** Terraform, Ansible, Pulumi (evaluation only)
**Cloud** AWS (EKS, RDS, IAM, S3), some Azure
**Observability** Prometheus, Grafana, OpenTelemetry, Loki
**Languages** Go, Python, Bash

## Education

**BSc Computer Science** — Hochschule Ravensburg-Weingarten, 2017

## Certifications

- Certified Kubernetes Administrator (CKA), 2021
- AWS Solutions Architect – Associate, 2020

## Languages

German (native), English (C1)
