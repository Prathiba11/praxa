# MLOps Lifecycle

Personal reference summary. Relevant to AI engineering roles even where the work
is LLM-centred, because the operational discipline is what distinguishes an
engineer from a notebook author.

## Why ML systems need their own operational discipline

Conventional software is deterministic: given the same input, the same code
produces the same output, and behaviour changes only when someone changes the
code. Machine-learning systems break both assumptions.

- **Three things can change independently** — code, data, and model. All three need
  versioning, and a result is only reproducible if all three are pinned.
- **Behaviour degrades without any change to the system**, because the world moves
  and the training distribution stops matching reality.
- **Correctness is statistical**, not binary. "It works" becomes "accuracy is
  0.87 on this evaluation set", which is only meaningful if the set is fixed and
  representative.
- **Testing is different.** You test data quality and model performance against
  thresholds, not just function outputs.

## The lifecycle

### 1 · Data

- **Collection and validation** — schema checks, range checks, null rates, class
  balance. Bad data silently produces a bad model; there is no exception raised.
- **Versioning** — a dataset version is part of the reproducibility triple. Tools
  such as DVC or LakeFS version data alongside git-tracked code.
- **Labelling** — provenance, inter-annotator agreement, and a process for
  correcting labels. Label noise caps achievable performance.
- **Splitting** — train/validation/test, split correctly for the problem. Random
  splits on time-series data leak the future into training, which is the most
  common invisible mistake in ML projects.

### 2 · Feature engineering

- Transformations must be **identical in training and serving**, or you get
  training–serving skew: a model that performs well offline and badly in
  production, for no visible reason.
- A **feature store** solves this by computing features once and serving the same
  definitions to both paths. Worth it at scale; overhead below it.

### 3 · Training and experimentation

- **Experiment tracking** — every run records its parameters, code version, data
  version, metrics and artefacts. MLflow and Weights & Biases are common. Without
  this, "which configuration produced the good model?" is unanswerable within a
  week.
- **Reproducibility** — fixed seeds, pinned dependencies, containerised
  environments.
- **Hyperparameter search** — grid, random, or Bayesian; log everything.

### 4 · Evaluation

- **Held-out test set**, used sparingly. Every decision informed by the test set
  leaks it.
- **Metrics matched to the problem** — accuracy is misleading on imbalanced data;
  precision, recall, F1, AUC, or a domain-specific cost function are usually more
  honest.
- **Slice analysis** — performance per subgroup, not only in aggregate. Aggregate
  metrics hide systematic failure on minority cases, which is both an engineering
  and a fairness problem.
- **A baseline.** A model that cannot beat "predict the majority class" or a
  simple heuristic is not a result.

### 5 · Model registry and governance

Versioned models with stage transitions (staging → production → archived),
lineage back to the data and code that produced them, and an approval record.
In a regulated setting this is the audit trail.

### 6 · Deployment

- **Batch** — scheduled scoring into a table. Simplest, and sufficient more often
  than teams assume.
- **Online / real-time** — a service behind an API. Latency budget, autoscaling,
  and a fallback for when the model is unavailable.
- **Streaming** — scoring on an event stream.
- **Edge** — on-device; quantisation and model size dominate.

Patterns worth naming: **shadow deployment** (run the new model alongside, compare
outputs, serve the old one), **canary** (a small traffic slice), **champion–
challenger** (continuous comparison in production).

### 7 · Monitoring

The part most projects skip and then regret.

- **Operational** — latency, throughput, error rate, saturation. Same as any
  service.
- **Data drift** — the input distribution has moved away from training. Detect with
  population stability index, KL divergence, or Kolmogorov–Smirnov tests per
  feature.
- **Concept drift** — the relationship between inputs and the target has changed.
  Harder: you need labels, which usually arrive late.
- **Prediction drift** — the output distribution has shifted. A useful early
  proxy when labels are delayed.
- **Data quality in production** — schema violations, sudden null spikes, a
  feature pipeline that silently started returning zeros.

### 8 · Retraining

- **Triggered** by a monitoring threshold, or **scheduled**, or **manual**
- Automated retraining needs automated validation, or you will promote a worse
  model. A gate that compares the candidate against the incumbent on a fixed set
  is not optional.
- **CT — Continuous Training** is the third leg alongside CI and CD in mature
  setups.

## Testing an ML system

| layer | what it checks |
|---|---|
| Unit | feature transformations, preprocessing functions |
| Data | schema, distributions, null rates, expected ranges |
| Model | performance above a threshold on a fixed set; no regression against the incumbent |
| Behavioural | invariance (irrelevant changes should not change the prediction), directional expectations, minimum functionality on known cases |
| Integration | the whole pipeline runs end to end on sample data |
| Infrastructure | the serving path returns valid responses under load |

## Practical observations

- **The model is a small fraction of the system.** Data pipelines, validation,
  serving, monitoring and retraining are the bulk of the work, and the bulk of the
  failures.
- **Most production ML failures are data failures**, not model failures. An
  upstream schema change is far more likely than a model spontaneously getting
  worse.
- **Reproducibility is the discipline that pays back most.** Being able to
  regenerate a result six months later is what makes a system maintainable, and
  in a regulated setting it is a requirement rather than a nicety.
- **The transferable insight from safety- and security-critical engineering**:
  traceability from requirement to implementation to test to evidence is exactly
  what an ML system needs from data to model to metric to deployment decision. It
  is the same discipline applied to a probabilistic artefact.
