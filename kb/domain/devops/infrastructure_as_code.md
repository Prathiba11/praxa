# Infrastructure as Code

Personal reference summary. Provider behaviour changes between versions; check
against the version pinned on the project.

## The claim, and what it actually buys

Infrastructure as code means the desired state of infrastructure lives in version
control and is applied by a tool rather than by a person in a console. The
benefits people list — repeatability, review, audit trail — all reduce to one:
**the infrastructure has a diff.** You can see what changed, who changed it, and
why, and you can review it before it happens rather than reconstruct it
afterwards.

What it does not buy is correctness. Code that provisions a badly designed
network provisions it reliably, in three regions, on every deploy.

## Declarative versus imperative

- **Declarative** (Terraform, OpenTofu, CloudFormation, Pulumi, Kubernetes
  manifests) — you describe the end state; the tool computes the actions.
- **Imperative** (shell, most Ansible playbooks in practice) — you describe the
  actions; the end state is whatever they produce.

Declarative tools are preferred for provisioning because the same file applied
twice converges to the same place. Configuration management inside a machine is
where imperative tools still earn their keep, though immutable images have taken
most of that work.

## State, which is where the real complexity lives

Terraform keeps a **state file** mapping resources in the configuration to real
resource identifiers. Nearly every hard Terraform problem is a state problem.

- **Remote state with locking** is not optional on a team. Two applies against the
  same local state produce a state file describing neither reality nor intent. S3
  with DynamoDB locking, Terraform Cloud, or GitLab's managed state all solve it;
  a state file in Git does not, because Git has no lock.
- **State contains secrets.** Generated passwords, connection strings and keys are
  stored in plain text in state regardless of how the value was marked in the
  configuration. State needs the same protection as a secrets store: encryption
  at rest, tight access, and never a public bucket.
- **Drift** is reality moving away from state — someone changed something in the
  console. `plan` shows it; the decision is whether to import it, revert it, or
  accept it. A scheduled plan that only reports drift, without applying, is a
  cheap and useful control.
- **Import and move** bring existing resources under management and rename them
  without destroying them. `moved` blocks make a refactor reviewable, which is
  the difference between renaming a module and deleting a database.

## Modules and structure

A module is a reusable unit with inputs, outputs and a single responsibility. The
failure mode is the module that takes forty variables because it tries to be
every environment at once; at that point the abstraction costs more than the
duplication it replaced.

For environments, the two common shapes:

- **Workspaces** — one configuration, several state files. Cheap, and it
  encourages environments that differ only by variables, which is usually what
  you want and occasionally a lie.
- **Directory per environment** — more duplication, more freedom, and a much
  clearer diff when production genuinely differs from staging.

Prefer the second when environments differ structurally. Pretending otherwise
puts the difference into conditionals, which is where it stops being visible.

## Pipelines for infrastructure

The standard shape, and the reasons for it:

1. `fmt` and `validate` — syntax and basic sanity, fast
2. **static analysis** — tfsec, Checkov, Terrascan for misconfiguration
3. `plan` on a pull request, with the plan **posted as a comment**
4. **policy check** against the plan — OPA/Conftest or Sentinel
5. `apply` on merge, from the saved plan file

Two details that matter more than they look. The plan must be *saved and reused*
by the apply, or the apply computes a fresh plan and you approved something else.
And policy runs against the plan, not the code, because the plan is what will
actually happen.

## Policy as code

Rules that a human would otherwise have to remember in review: no public S3
buckets, encryption on every volume, mandatory tags, no security group open to
0.0.0.0/0 on management ports, approved regions only.

Introduce them in warn mode first. A policy set that blocks every pipeline on day
one gets an exemption mechanism, and the exemption mechanism becomes the process.

## Secrets

Never in the repository, and never in plain variables files. A managed store —
Vault, AWS Secrets Manager, GCP Secret Manager, SOPS with a KMS key for a
file-based workflow — with short-lived credentials for the pipeline itself,
ideally via OIDC federation so the pipeline holds no long-lived cloud key at all.

Remember the state-file exposure above: keeping a secret out of the repository
does not keep it out of state.

## Testing infrastructure code

- **Static** — `validate`, linters, security scanners. Cheap, run on every commit.
- **Plan assertions** — check the planned actions against expectations. Catches
  "this change would destroy the database" before a human has to spot it.
- **Ephemeral environment tests** — Terratest or `terraform test` provisioning
  real resources, asserting, destroying. Slow and not free, so reserve them for
  modules that are widely reused.

The highest-value test is the cheapest one: fail the pipeline when a plan
proposes destroying a stateful resource unless the change is explicitly
annotated.

## Practical observations

- **`terraform destroy` on the wrong workspace is the classic incident.** Prevent
  it structurally — separate credentials per environment, deletion protection on
  stateful resources, and no unattended apply to production.
- **Pin provider and module versions.** An unpinned provider means a pipeline that
  passed yesterday can fail today with no commit in between, and the change is
  invisible in the diff.
- **A long-lived feature branch of infrastructure code is a liability.** The
  longer it lives, the further state drifts from it, and the plan on merge stops
  resembling the plan that was reviewed.
- **Write the runbook for the manual step you did not automate.** Every estate has
  one; the problem is when it lives in one person's memory.
