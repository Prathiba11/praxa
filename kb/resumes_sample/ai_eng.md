# Tobias Wehrle

Munich, Germany · tobias.wehrle@example.invalid · +49 000 0000000

_Sample CV. Tobias Wehrle is not a real person and none of the employers below
exist. This file ships with the repository so that a reviewer who clones it can
run the whole application without needing anyone's real CV._

## Summary

AI engineer, five years, most of it spent getting retrieval systems to be
right rather than impressive. Has taken two LLM applications from a notebook to
something on call at 3am. Believes an evaluation set you actually maintain beats
a model upgrade you cannot measure.

## Senior AI Engineer — Lichtform Analytics GmbH

_Munich · June 2023 – present_

- Rebuilt a customer-support retrieval system that answered from a single dense
  index. Added BM25 with reciprocal rank fusion and a cross-encoder reranker;
  answer accuracy on the 240-question evaluation set went from 61% to 84%.
- Introduced query translation — multi-query for vague questions, step-back for
  narrow ones. Recall@10 improved 14 points on the subset where the question
  used different vocabulary from the documents.
- Cut inference cost 45% by routing classification-shaped requests to a smaller
  model and reserving the large one for generation, after measuring that 62% of
  traffic never needed the larger model.
- Built the offline evaluation harness the team now gates releases on: golden
  questions, retrieval metrics, an LLM judge with a human-scored calibration
  sample, all in CI.
- Handled the prompt-injection work after a support document containing
  "ignore previous instructions" reached production. Retrieved content is now
  delimited and labelled as data, and tools are allow-listed per mode.

## Machine Learning Engineer — Brennweite Data AG

_Nuremberg · February 2021 – May 2023_

- Owned the feature store and the training pipeline for a demand-forecasting
  model serving 1,100 retail locations.
- Moved model deployment from a monthly manual push to a versioned pipeline with
  automatic rollback on drift. Two rollbacks fired in a year, both correctly.
- Added monitoring for training-serving skew after an incident where a
  preprocessing change reached serving before training and degraded MAPE by 8
  points for eleven days before anyone noticed.
- Mentored two junior engineers, both of whom now own services.

## Data Scientist — Weißbach Institut für Angewandte Forschung

_Munich · September 2019 – January 2021_

- NLP research on German-language clinical text: named-entity recognition and
  de-identification.
- Published one workshop paper on de-identification under low-resource
  conditions.
- Learned the hard way that a model which works on the research corpus and not
  on the hospital's actual exports is not a working model.

## Skills

**LLM applications** RAG, hybrid retrieval, reranking, query translation,
tool calling, structured output, evaluation
**Frameworks** LangChain, LlamaIndex, Hugging Face, PyTorch
**Vector stores** Chroma, Qdrant, pgvector, FAISS
**MLOps** MLflow, DVC, Docker, Kubernetes, GitHub Actions
**Languages** Python, SQL, some Go

## Education

**MSc Data Science** — Technische Universität München, 2019
**BSc Statistics** — Universität Augsburg, 2017

## Publications

- Wehrle, T. (2020). "De-identification of German clinical notes under
  low-resource conditions." Workshop on Clinical NLP. _(fictional, as is the
  rest of this document)_

## Languages

German (native), English (C2)
