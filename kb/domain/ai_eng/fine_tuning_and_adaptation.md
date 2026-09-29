# Adapting a Model: Prompting, RAG, Fine-Tuning

Personal reference summary. Provider limits and prices change; the decision
structure does not.

## The question this answers

"The base model is not good enough at our task." There are four responses, and
choosing between them is most of the engineering:

1. **Better prompting** — clearer instructions, examples, structured output
2. **Retrieval** — give the model the facts at request time
3. **Fine-tuning** — change the model's weights on your data
4. **A different model** — sometimes the whole answer

They are not alternatives on one scale. They fix different problems, and picking
the wrong one is expensive in a way that is hard to reverse.

## The diagnosis that decides it

Ask what the model is failing at:

- **It does not know the fact.** → Retrieval. Facts change, and a fine-tune bakes
  in the state of the world on the day you trained.
- **It knows, but formats or behaves wrongly.** → Prompting first, then
  fine-tuning. Tone, structure, house style and consistent refusals are exactly
  what fine-tuning is good at.
- **It cannot do the task at all.** → A stronger model. Fine-tuning sharpens a
  capability that is present; it rarely creates one that is absent.
- **It is right but too slow or expensive.** → Fine-tune a smaller model on the
  larger one's outputs, or route easy cases to the cheap model.

The rule of thumb that survives contact with reality: **RAG for knowledge,
fine-tuning for behaviour.** A surprising number of failed fine-tuning projects
were retrieval problems.

## Why RAG is usually tried first

- Facts can be updated by re-indexing, not retraining
- Answers can cite a source, which a fine-tune cannot
- Access control stays possible, because documents remain documents
- Wrong information can be **deleted**; a fine-tune has to be redone

That last point is underrated. If a customer asks you to remove their data from a
system, deleting rows from an index is a procedure. Removing their influence from
a set of weights is not.

## Fine-tuning approaches

- **Full fine-tuning** — every weight updated. Expensive, needs real
  infrastructure, and risks catastrophic forgetting of general ability.
- **LoRA / QLoRA** — train small low-rank adapter matrices and leave the base
  frozen. Orders of magnitude cheaper, adapters are megabytes not gigabytes,
  several can be swapped against one base model. This is what "fine-tuning"
  usually means in practice now.
- **Instruction tuning** — supervised training on instruction/response pairs, to
  change how the model behaves rather than what it knows.
- **Preference optimisation** (RLHF, DPO and relatives) — train on *comparisons*
  rather than answers. Appropriate when quality is easier to judge than to
  demonstrate, and heavier than most applications need.

## The data is the project

Everything else is logistics. What matters:

- **Quality over quantity.** A few hundred carefully checked examples usually beat
  tens of thousands of scraped ones. Errors in training data are learned
  faithfully.
- **Match the serving format exactly.** If production sends a system prompt and a
  user turn, train on that shape. A mismatch between training and serving format
  is the most common cause of a fine-tune that "did nothing".
- **Hold out a test set before you start**, and never look at it while iterating.
- **Check for contamination.** If evaluation examples leaked into training, the
  numbers are fiction.
- **Watch the distribution.** A dataset that is 80% one category produces a model
  that answers everything as that category.

## Evaluating an adaptation

You need a baseline and a decision rule *before* training, or the result will be
judged by whether it feels better.

- Fix an evaluation set, and score the base model on it first
- Measure the specific thing you tried to fix, and **also** a general set, to
  catch capability lost elsewhere
- Compare against the honest alternative — a better prompt on the base model, not
  the original bad prompt
- Include cost and latency, since those are often the actual motivation

A fine-tune that improves the target metric by two points and loses five on
general reasoning is a regression, and only a second evaluation set reveals it.

## Serving considerations

- A fine-tuned open-weight model means you now operate a model: GPUs, capacity,
  scaling, upgrades. That is an ongoing cost, not a one-off.
- Provider-hosted fine-tuning avoids that but ties you to the provider and their
  deprecation schedule.
- **Base models get deprecated.** An adapter is trained against a specific base;
  when that base retires, the work is repeated. Budget for it.
- Multiple LoRA adapters over one base is efficient, and only works if they share
  a base.

## Practical observations

- **Do the prompt work properly before concluding it is insufficient.** A
  significant share of fine-tuning projects are rescuing a prompt that had no
  examples in it.
- **Fine-tuning does not remove the need for retrieval.** A model tuned to your
  house style still needs today's facts.
- **Combine them in the obvious order:** retrieval supplies the facts, tuning
  supplies the behaviour. They are not competitors.
- **Write down the rollback.** Serving a previous adapter version has to be a
  configuration change, not a retraining run.
- **The strongest argument for fine-tuning is usually economic** — matching a
  large model's quality on one narrow task with a small model. That is a
  measurable claim, which makes it a good one to make.
