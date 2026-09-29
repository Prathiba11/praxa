# Cloud Cost and Capacity Engineering

Personal reference summary. Pricing models and instance families change
frequently; treat every figure here as a shape, not a quote.

## Why an engineer is asked about this at all

Cloud spend is one of the few engineering outputs a finance function reads
directly, and the questions that follow — why did this double, what happens if we
grow 3x — are engineering questions with a financial vocabulary. A candidate who
can answer them is unusual, and the answers are not difficult.

The framing that works: **cost is a non-functional requirement like latency.** It
has a target, it regresses without a test, and it is cheapest to fix in design.

## Where the money actually goes

In most estates, in rough order:

1. **Compute** — instances, nodes, serverless invocations. Usually the largest
   line and the most over-provisioned.
2. **Managed data services** — databases, caches, search. Expensive because they
   are always on and rarely rightsized after launch.
3. **Storage** — cheap per gigabyte, enormous in aggregate, and dominated by data
   nobody has looked at in two years.
4. **Egress and cross-zone traffic** — the line people forget. Traffic leaving the
   cloud is charged, and in many providers so is traffic between availability
   zones. A chatty service spread across three AZs for resilience pays for that
   resilience per request.
5. **Observability** — log and metric ingestion billed per gigabyte or per series.
   A debug log left on in production is a recurring invoice.

## The levers, strongest first

- **Turn it off.** Non-production environments running overnight and at weekends
  are roughly 70% waste. A schedule that stops them is the single highest-return
  change in most estates, and it is reversible.
- **Rightsize.** Instances chosen at launch and never revisited. Look at p95
  utilisation over a fortnight, not the peak of the worst day.
- **Commit.** Reserved instances and savings plans trade flexibility for a
  discount. Commit to the floor of your usage, not the average — an unused
  commitment is a worse outcome than on-demand pricing.
- **Use spot or preemptible capacity** for work that can be interrupted: CI
  runners, batch, stateless workers behind a queue. Requires the workload to
  tolerate a two-minute eviction notice, which is a design property.
- **Storage lifecycle.** Tier to infrequent access and archive on a schedule, and
  expire what has no retention requirement. Old snapshots and orphaned volumes
  are pure waste and nobody owns them.
- **Sampling and retention in observability.** Full-fidelity traces at 100% are
  rarely read. Tail sampling keeps the interesting ones.

## Capacity and autoscaling

Horizontal autoscaling on a lagging signal is the common mistake: CPU rises,
scaling begins, instances take ninety seconds to become healthy, and the traffic
spike is over before capacity arrives. What helps:

- Scale on a **leading indicator** where one exists — queue depth, request
  concurrency, connection count — rather than CPU alone.
- **Scale out fast, scale in slow.** The cost of one extra instance for ten
  minutes is trivial; the cost of a flapping scale-in during a rising load is an
  outage.
- Keep **headroom** for the failure you designed for. If the design survives the
  loss of one availability zone, the cluster has to run below the level where two
  thirds of it can carry everything.
- **Warm pools and pre-pulled images** shorten time-to-healthy, which is usually a
  better lever than a more aggressive threshold.

## Kubernetes specifics

- **Requests and limits are the cost model.** The scheduler packs on *requests*,
  so a pod requesting 2 CPU and using 0.1 wastes 1.9 CPU of cluster capacity
  whatever the node graph says. Most cluster overspend is over-requesting.
- **CPU limits cause throttling**, and throttling looks like a latency problem
  rather than a configuration one. Many teams set memory limits and leave CPU
  limits off deliberately.
- **Cluster autoscaler and pod autoscaler have to agree.** An HPA that adds pods
  no node can fit, on a cluster whose autoscaler cannot add nodes of that shape,
  produces pending pods and no capacity.
- **Bin packing beats node count.** A few large nodes at high utilisation usually
  cost less than many small ones, up to the blast radius you are willing to
  accept.

## Making it visible

Nothing is controlled that is not attributed. Practical order:

1. **Tag everything** — owner, environment, service, cost centre — and enforce it
   in policy, because untagged resources become permanently unowned.
2. **Show cost per team or service**, not one total. A single number is nobody's
   problem.
3. **Alert on the derivative, not the level.** "Spend is 40% above the same day
   last week" is actionable; a monthly total is a postmortem.
4. **Put a cost estimate in the pull request** for infrastructure changes.
   Infracost and similar tools do this from a Terraform plan, and it moves the
   conversation to before the merge.

## Practical observations

- **The biggest savings are architectural and the smallest are heroic.** Moving a
  chatty service into one availability zone, or caching a call that was made per
  request, beats months of instance-type tuning.
- **Beware the optimisation that trades cash for reliability.** Removing
  redundancy saves money until the day it does not, and that trade should be made
  explicitly with the people who own the availability target.
- **Measure before and after with the same query.** Cloud bills lag, tags change,
  and "we saved 30%" is unverifiable a quarter later without a saved query.
- **An anomaly alert with no owner is noise.** Route it to the team whose tag is
  on the resource, which only works if step 1 was done properly.
