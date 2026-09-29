# CI/CD Pipelines and GitOps

Personal reference summary, grounded in GitLab CI/CD and GitHub Actions experience.

## The distinction that matters in interviews

- **Continuous Integration** — every change is merged frequently into a shared
  branch and automatically built and tested. The goal is fast feedback and no
  long-lived divergence.
- **Continuous Delivery** — every change that passes the pipeline is *releasable*.
  A human decides when to release.
- **Continuous Deployment** — every change that passes is released automatically,
  with no human gate.

Most organisations that say "CI/CD" have CI plus continuous delivery. Claiming
continuous deployment when a human clicks a button is the kind of imprecision an
interviewer notices.

## Pipeline design principles

**Order stages by cost.** Lint and static type checks take seconds; the full test
suite takes minutes; integration and end-to-end tests take longer still. Run the
cheap checks first and fail fast, so expensive runners are not spent on code that
is not even formatted.

**Every stage must be able to fail the build.** A warning nobody acts on is
noise. If a check should not block, it should not be in the pipeline.

**Make it reproducible.** Pinned dependency versions, containerised build
environments, no reliance on state left by a previous run.

**Cache deliberately.** Know what the cache key is and what invalidates it.
Caching dependencies on a lockfile hash is correct; caching on a branch name
produces stale, confusing builds.

**Require no secrets where possible.** If the test suite needs production
credentials, the tests are integration tests in disguise. Mocking external
services means the pipeline can run on a fork, on a PR from outside the team, and
without a secret-leak risk.

**Artefacts, not rebuilds.** Build once, promote the same artefact through
environments. Rebuilding per environment means the thing you tested is not the
thing you shipped.

## GitLab CI/CD specifics

- **Stages and jobs** — stages run in sequence, jobs within a stage in parallel
- **Parent-child pipelines** — a parent pipeline triggers child pipelines defined
  in separate files. This is the tool for taming complexity: shared stages are
  defined once and included, and each component's pipeline stays readable instead
  of one monolithic `.gitlab-ci.yml` of many hundreds of lines. It also allows
  child pipelines to run only when their component changed.
- **`rules` / `only` / `except`** — control when jobs run: branch, tag, merge
  request, changed paths, manual
- **`extends` and `include`** — template reuse across projects; the mechanism for
  removing duplicated pipeline logic
- **Runners** — shared or project-specific; tags route jobs to capable runners
- **Artifacts and cache** — artifacts pass build outputs between stages and are
  downloadable; cache speeds up repeated dependency installation

Modularising shared stages is where measurable improvement usually comes from —
less duplicated logic, shorter build times, and dramatically lower maintenance
cost when a build step changes.

## GitHub Actions specifics

- **Workflows** in `.github/workflows/*.yml`; jobs run in **parallel by default**
- **`needs:`** creates ordering — this is the equivalent of GitLab stages
- **`strategy.matrix`** runs the same job across multiple versions or platforms
- **`concurrency` with `cancel-in-progress`** cancels superseded runs, so three
  pushes in five minutes do not produce three competing runs
- **`on:`** triggers: push, pull_request, schedule (cron), workflow_dispatch
  (manual), repository_dispatch
- **Caching** via `actions/cache` or the built-in `cache:` in setup actions
- **Secrets** in repository or environment settings; environment protection rules
  can require approval before a deploy job runs

A common inefficiency worth catching: triggering on both `push` and
`pull_request` produces duplicate runs for every push to a branch with an open PR.
Scoping `push` to the default branch fixes it.

## Deployment strategies

| strategy | mechanism | trade-off |
|---|---|---|
| **Rolling** | replace instances gradually | simple, but two versions run concurrently |
| **Blue-green** | full parallel environment, switch traffic | instant rollback, double the infrastructure |
| **Canary** | route a small traffic percentage to the new version | early real-signal detection, needs good metrics and routing |
| **Feature flags** | deploy dormant code, enable per cohort | decouples deploy from release, but flag debt accumulates |

## GitOps

The core idea: **the desired state of the system lives in git, and a controller
running inside the cluster continuously reconciles reality toward it.**

Consequences:

- **Git is the single source of truth.** No manual `kubectl apply`; a change is a
  commit.
- **Pull-based rather than push-based.** The cluster fetches its own desired
  state, so CI needs no cluster credentials — a significant security improvement
  over a pipeline that holds admin access.
- **Drift detection and self-healing.** A manual change is detected and reverted.
- **The audit trail is the git history.** Who changed what, when, reviewed by whom
  — for free.
- **Rollback is `git revert`.**

ArgoCD and Flux are the common controllers. The usual repository split is
application code in one repo, environment manifests in another, with CI updating
an image tag in the manifest repo — which keeps the deployment decision auditable
and separate from the build.

## Practical observations

- **Pipeline maintenance cost is the hidden expense.** A pipeline nobody
  understands becomes a place changes are avoided. Modularisation is as much about
  maintainability as speed.
- **Flaky tests destroy trust faster than slow tests.** Once a red build is
  routinely re-run rather than investigated, the pipeline has stopped working as a
  gate regardless of its coverage.
- **Security belongs in the pipeline, not after it.** Dependency scanning, secret
  scanning, SAST and container image scanning as pipeline stages catch problems
  when they are cheap. In a regulated context (ISO/SAE 21434 process conformity,
  for example) the pipeline is also where evidence is generated automatically
  rather than assembled by hand later.
- **Build-time improvements compound.** A pipeline that takes twenty minutes
  changes developer behaviour; one that takes four does not.
