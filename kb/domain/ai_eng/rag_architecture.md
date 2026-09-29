# RAG Architecture and Retrieval Techniques

Personal reference summary. This is the material an AI engineering interview will
probe hardest, because it is where most candidates are shallow.

## Why RAG exists

A language model knows what was in its training data. It does not know your
documents, and it cannot cite them. Fine-tuning teaches style and format
effectively but is a poor mechanism for injecting facts: it is expensive, slow to
update, and does not give you provenance.

Retrieval-Augmented Generation instead retrieves relevant passages at query time
and places them in the prompt. The model answers *from the passages*, and you can
show the user where the answer came from. Updating knowledge means re-indexing a
document, not retraining anything.

## The two halves

### Ingestion (offline)

```
load -> clean -> chunk -> embed -> store (with metadata)
```

### Retrieval and generation (per query)

```
query -> analyse -> translate -> search -> fuse -> rerank -> assemble -> generate
```

Naive RAG collapses the second half to `embed query -> nearest neighbours ->
stuff into prompt`. Everything below is what separates that from a system that
actually works.

## Chunking

The most consequential and least glamorous decision. A chunk is the unit that
gets retrieved, so it must be self-contained enough to make sense alone.

| strategy | when |
|---|---|
| **Fixed-size with overlap** | uniform prose; simple baseline. Overlap (10–20%) stops meaning being cut at boundaries. |
| **Recursive character** | respects paragraph then sentence then word boundaries. Good general default. |
| **Structure-aware** | split on markdown headings, code functions, document sections. Best when the document has real structure. |
| **Semantic** | split where embedding similarity between adjacent sentences drops. Expensive; occasionally worth it. |
| **Parent-document / small-to-big** | embed small chunks for precision, return the larger parent for context. Strong technique. |

Rules of thumb: match chunk size to the answer's natural size; never split an
atomic unit (a CV bullet, a table row, a function); attach metadata to every
chunk — source, type, section, date, whatever you will want to filter on later.

**Retrofitting metadata means re-indexing everything.** Decide it up front.

## Embeddings

A model maps text to a vector such that similar meanings land near each other.
Similarity is usually cosine distance.

Things that matter in practice:

- **Dimension is fixed per model** and pinned per collection. Changing model means
  re-embedding the entire corpus — vectors from different models are not
  comparable, and mixing them degrades retrieval silently, with no error.
- **Store the model name in the collection metadata** and refuse to query on a
  mismatch. This bug is invisible otherwise.
- **Multilingual models** matter when the corpus and the queries are in different
  languages. A German document and an English question only land near each other
  if the model puts both languages in one shared space.
- **Model-specific prefixes** — some families (the e5 group, for example) expect
  `query:` on queries and `passage:` on documents. Omitting them costs quality
  with no warning.
- **Local vs API embeddings** — local models are free, offline, and keep sensitive
  text on the machine, which can be the deciding factor under GDPR.

## Query translation

The user's phrasing is one sample from many possible phrasings, and the corpus
may use none of them. Translation generates better search queries before
searching.

- **Multi-query** — generate 3–4 paraphrases, search all, merge results. The
  workhorse.
- **Step-back prompting** — generate a more general question first, so broad
  questions retrieve conceptual context rather than incidental specifics.
- **Decomposition** — split a multi-part question into sub-questions, answer each,
  then compose.
- **HyDE (Hypothetical Document Embeddings)** — have the model write a plausible
  *answer*, then embed that. A question and its answer look different to an
  embedding model; a fake answer and the real answer look similar.

This matters most in a cross-lingual corpus: an English question about "threat
modelling experience" will not match a German passage about
*"Bedrohungsanalyse und Risikobewertung"* on a single phrasing.

## Structured retrieval

Filters, not just similarity. An LLM extracts structured fields from the question
— intent, entity, location, date range, category — and those become metadata
filters on the vector search or predicates in SQL.

Without this, "postings from this week in Stuttgart" is just words in an
embedding, and the search has no concept of dates or places. This is the
difference between a demo and something usable.

## Hybrid search

**BM25** is lexical ranking: term frequency weighted by inverse document
frequency, with saturation and length normalisation. **Dense retrieval** is
embedding similarity.

They fail differently, which is why running both wins:

- Embeddings blur exact strings. Ask for `ISO 21434` and dense search may return
  `ISO 26262` — semantically almost identical, practically a different standard.
  BM25 matches the literal token.
- BM25 has no idea that "threat modelling" and "Bedrohungsanalyse" are related.
  Embeddings do.

### Reciprocal Rank Fusion

The two systems produce incomparable scores (BM25 might say 14.7, cosine 0.83).
RRF ignores scores and uses rank position only:

```
score(doc) = Σ over lists  1 / (k + rank_in_list)      # k typically 60
```

Documents both methods like float to the top. No tuning, few lines of code,
robust.

## Reranking

Retrieve broadly (top 20–50), then rerank precisely and keep the top 3–5. A
**cross-encoder** scores the query and document *together* rather than comparing
two independently computed vectors, which is far more accurate — and far too slow
to run over a whole corpus, which is exactly why it goes second.

Best quality-per-line-of-code improvement available in a RAG pipeline.

## Context assembly and generation

- Deduplicate by source and chunk index
- Budget the context window; more chunks is not better
- **Lost in the middle** — models attend less to the centre of a long context. Put
  the strongest chunks at the beginning and end.
- **Delimit retrieved content explicitly** and state that it is data, not
  instructions. Retrieved documents are untrusted input; this is where prompt
  injection enters a RAG system.
- Return citations alongside the answer. If a claim cannot be traced to a chunk,
  the system should say so rather than filling the gap.

## Failure modes to be able to name

| failure | symptom | cause |
|---|---|---|
| Retrieval miss | confident wrong answer | phrasing mismatch, bad chunking, missing filter |
| Distractor chunks | answer drifts off | top-k too large, no reranking |
| Lost in the middle | ignores supplied evidence | context too long, poor ordering |
| Stale index | outdated answers | no re-ingestion pipeline |
| Embedding mismatch | quality collapse, no error | model changed without re-indexing |
| Chunk fragmentation | truncated, contextless answers | atomic units split |
| Injection via corpus | model follows document instructions | retrieved text not delimited or screened |

## Evaluation

You cannot improve retrieval you do not measure. A golden set of 30–50
question/expected-source pairs, scored on:

- **Faithfulness** — is the answer supported by the retrieved context?
- **Answer relevancy** — does it address the question?
- **Context precision** — are the retrieved chunks relevant?
- **Context recall** — was the necessary information retrieved at all?

The critical diagnostic is separating **retrieval failure** from **generation
failure**. If context recall is low, no prompt engineering will help. RAGAs is the
common framework; a hand-rolled harness with an LLM judge works too.

A/B the pipeline variants — naive vs hybrid vs hybrid+rerank — on the same golden
set, and keep the table. That number is what turns "I built RAG" into "I measured
my retrieval and here is what improved it."
