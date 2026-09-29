# Kubernetes and Containers

Personal reference summary for DevOps and platform interviews.

## Why containers

A container packages an application with its dependencies and runs it as an
isolated process on a shared kernel. Compared with a virtual machine it starts in
milliseconds rather than seconds and carries no guest OS, at the cost of weaker
isolation — containers share the host kernel, so a kernel vulnerability crosses
the boundary.

The engineering value is **reproducibility**: the image that passed CI is the
artefact that runs in production, so "works on my machine" stops being a class of
bug.

### Docker essentials worth knowing precisely

- **Image vs container** — an image is the immutable filesystem and metadata; a
  container is a running instance of it.
- **Layers and caching** — each Dockerfile instruction creates a layer. Order
  instructions from least to most frequently changing (dependencies before source
  code) so cached layers are reused.
- **Multi-stage builds** — compile in a build stage, copy only the artefact into a
  slim runtime stage. Smaller images, smaller attack surface, no build tools in
  production.
- **Security basics** — run as a non-root user, pin base image versions rather
  than `latest`, scan images for known vulnerabilities, never bake secrets into
  layers (they persist in image history even if a later layer deletes the file).

## Kubernetes: what it actually is

A declarative orchestration system. You describe the desired state; controllers
continuously reconcile actual state toward it. Almost everything else follows from
that one idea, including why "just restart it" is rarely the right fix — the
controller will recreate whatever you deleted.

### Control plane

- **API server** — the single front door; everything goes through it
- **etcd** — the cluster's state store
- **Scheduler** — assigns pods to nodes based on resource requests, affinity
  rules, taints and tolerations
- **Controller manager** — runs the reconciliation loops

### Node components

- **kubelet** — the agent that starts and supervises containers on the node
- **kube-proxy** — routes service traffic
- **Container runtime** — containerd or similar

### Workload objects

| object | purpose |
|---|---|
| **Pod** | the smallest deployable unit; one or more containers sharing network and storage |
| **ReplicaSet** | maintains a specified number of pod replicas |
| **Deployment** | manages ReplicaSets to give rolling updates and rollback |
| **StatefulSet** | stable identities and persistent storage per replica, for databases and similar |
| **DaemonSet** | one pod per node, for agents such as log or metric collectors |
| **Job / CronJob** | run-to-completion and scheduled work |

### Networking and configuration

- **Service** — a stable virtual IP and DNS name in front of a changing set of
  pods. `ClusterIP` internal, `NodePort` and `LoadBalancer` external.
- **Ingress** — HTTP routing, host and path based, with TLS termination
- **ConfigMap / Secret** — non-sensitive and sensitive configuration injected as
  environment variables or mounted files. Secrets are base64-encoded, *not*
  encrypted by default; enable encryption at rest and use RBAC.
- **Namespace** — a scope for names and a boundary for quotas and policy
- **NetworkPolicy** — pod-level firewalling. Default is "all traffic allowed", so
  a deny-by-default policy is a deliberate act.

### Resources, health and scaling

- **Requests and limits** — requests drive scheduling, limits cap consumption.
  Exceeding a memory limit means the container is killed (`OOMKilled`); exceeding
  a CPU limit means throttling, which is much harder to diagnose because the pod
  looks healthy while running slowly.
- **Probes** — `liveness` (restart if failing), `readiness` (remove from service
  endpoints if failing), `startup` (allow slow initialisation without the liveness
  probe killing it). Misconfigured liveness probes cause restart loops in
  otherwise healthy applications.
- **HorizontalPodAutoscaler** — scales replica count on CPU, memory or custom
  metrics. Requires resource requests to be set, or it has no baseline.

## Diagnosing the common failures

| symptom | usual cause |
|---|---|
| `CrashLoopBackOff` | the application exits on start — check `kubectl logs --previous` |
| `OOMKilled` | memory limit too low, or a leak |
| `ImagePullBackOff` | wrong image name or tag, or missing registry credentials |
| `Pending` | no node satisfies the resource requests, or an unbound volume claim |
| Slow but "healthy" | CPU throttling from a limit set too low |
| Intermittent 5xx | readiness probe wrong, so traffic reaches pods that are not ready |

Diagnostic order that works: `kubectl get pods` → `kubectl describe pod` (events
are at the bottom and usually contain the answer) → `kubectl logs`, with
`--previous` for a crashed container → check resource usage → check the service
endpoints actually resolve to pods.

## Security in a cluster

- **RBAC** — least privilege for both humans and service accounts; audit for
  cluster-admin bindings
- **Pod security** — no privileged containers, no host network or host path
  mounts unless genuinely necessary, read-only root filesystem where possible,
  drop unneeded Linux capabilities
- **Image provenance** — trusted registries, signed images, admission control to
  reject unscanned or unsigned images
- **Secrets** — external secret managers rather than plain Kubernetes Secrets for
  anything sensitive; never in `git` unencrypted
- **Network** — default-deny NetworkPolicies, so a compromised pod cannot
  freely reach the rest of the cluster

## Practical observations

- **Most production incidents come from resource limits and probes**, not from
  exotic distributed-systems problems.
- **The declarative model is the thing to internalise.** Manual `kubectl` changes
  drift from the manifests in git and are silently reverted or overwritten —
  which is precisely the problem GitOps exists to solve.
- **Introducing Kubernetes is an organisational change as much as a technical
  one.** It moves responsibility for deployment, resource sizing and observability
  onto the teams that own the services.
