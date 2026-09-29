# ATS and CV Optimisation Guide

Reference material for scoring a CV against a job posting and for producing a
tailored CV. Written for the German and wider European engineering job market.

## What an ATS actually is

An Applicant Tracking System is primarily a **database and workflow tool for
recruiters**, not a scoring engine. Common systems in Germany include Workday,
SAP SuccessFactors, Personio, softgarden, Greenhouse and Lever.

Its core functions are:

1. Receive applications and parse them into structured fields
2. Store candidates and their documents
3. Let recruiters search and filter the stored pool
4. Move candidates through pipeline stages

The widespread belief that "an AI rejected my CV before a human saw it" is mostly
folklore. Fully automated rejection based on CV content is legally fraught in the
EU under GDPR Article 22 and the AI Act's rules on automated decision-making in
recruitment. What actually happens is more mundane and, for a candidate, worse.

## How candidates are really filtered out, in order of frequency

### 1. Parse failure

The single most common self-inflicted problem. The ATS converts the document into
fields; when it cannot, the record is incomplete or garbled.

Causes, in rough order of damage:

- **Multi-column layouts** — text is read left-to-right across columns and comes
  out as word salad
- **Contact details in a Word header or footer** — frequently not extracted at
  all, so the recruiter has the CV but no way to make contact
- **Tables, text boxes, and graphical elements** — often parse as nothing
- **Skill "rating bars" and icons** — carry no text, so the skill is invisible
- **Image-only PDFs** (exported from design tools, or scanned) — parse as an
  empty document
- **Non-standard section headings** — "My Journey" instead of "Experience"
  breaks field mapping
- **Photos** — harmless to parsing but consume space and are unwanted by many
  international employers

### 2. Missing the literal keyword

Recruiters search the stored pool with boolean queries:
`("Kubernetes" OR "K8s") AND Terraform AND Stuttgart`. **If the CV does not
contain the exact string searched for, the candidate is invisible** — not
rejected, invisible. This is the real mechanism behind "the ATS filtered me out",
and it is why synonym choice matters more than prose quality.

### 3. Knockout questions

Explicit filters answered by the candidate in the application form: work
authorisation, years of experience, language level, willingness to relocate,
notice period, salary expectation. These *can* auto-reject, and they are the most
common genuine automated rejection.

### 4. Volume

400 applicants, 40 CVs read. Nothing was wrong with the document.

## Rules for a parse-safe CV

- Single column throughout
- No tables, text boxes, images, icons or skill bars
- Nothing in headers or footers; contact details in the body, at the top
- Standard section headings: `Experience` / `Berufserfahrung`, `Education` /
  `Ausbildung`, `Skills` / `Kenntnisse`, `Certifications`, `Languages`
- Dates as `MM/YYYY – MM/YYYY`; never "Summer '23"
- Job title on its own line, then company, then location, then dates
- A standard font; avoid display faces with heavy ligatures
- `.docx` unless the posting explicitly asks for PDF; if PDF, export text-based,
  never "print to image"
- Verify by selecting all text in the exported file and pasting it into a plain
  text editor. If the result is scrambled, that is what the recruiter sees.

### German market conventions

Some German employers still expect a photo, address and date of birth in a
*Lebenslauf*; many international firms explicitly do not want them. Match the
employer rather than a universal rule. When a posting is in German, apply in
German.

## Keyword strategy

- **Mirror the posting's exact vocabulary.** If the posting says "CI/CD", write
  "CI/CD" even if you would naturally write "continuous integration".
- **Spell out and abbreviate together on first use**: `Kubernetes (K8s)`,
  `Threat Analysis and Risk Assessment (TARA)`,
  `Cybersecurity Management System (CSMS)`.
- **Include bilingual terms** where both are used in the market:
  `TARA (Bedrohungsanalyse und Risikobewertung)`.
- **Put critical keywords in both the Skills section and an Experience bullet.**
  A skill that appears only in a list reads as familiarity; a skill inside an
  achievement reads as experience.
- **Match the seniority language** of the posting — "led", "owned", "designed"
  versus "supported", "contributed to". Do not inflate; do not undersell.
- Do not keyword-stuff. Invisible white text and keyword walls are detectable,
  and a human reads the document at the end.

## Scoring a CV against a posting

A defensible fit score combines four signals. It is a heuristic proxy for
recruiter search behaviour, not a simulation of any real ATS.

1. **Hard-requirement keyword coverage** — which explicitly required
   technologies, standards and tools appear literally in the CV
2. **Semantic similarity** — embedding similarity between the posting's
   requirements and the CV's experience section, catching paraphrase and
   cross-language matches
3. **Knockout criteria** — language level, years of experience, work
   authorisation, on-site expectation. A single unmet knockout should dominate
   the score, because in reality it does.
4. **Parse safety of the generated document** — extract the text back out of the
   produced file and verify that contact details, job titles and dates survived

Report a gap list rather than only a number. "Missing: Terraform, AWS. Present
but weak: Kubernetes (mentioned once, no achievement)" is actionable; "62%" is
not.

## Rules for tailoring a CV

- **Rewrite only claims already present in the source CV.** Never introduce a
  technology, certification, employer or metric that is not there.
- Reorder and re-emphasise: move the most relevant experience up, expand the
  bullets that match the posting, compress the ones that do not.
- Adopt the posting's terminology for skills the candidate genuinely has.
- Where a required skill is genuinely absent, say so in the gap list rather than
  writing round it.
- Surface a diff of what changed and require explicit confirmation before export.
  Automated CV rewriting carries a real fabrication risk, and the mitigation is
  human review, not a better prompt.

## Cover letter guidance

- Address the specific role and company; a letter that could be sent anywhere
  reads as such
- Lead with the strongest concrete match between the candidate's achievements and
  the posting's central requirement
- Include two or three specific, quantified achievements from the CV — never
  generic enthusiasm
- Acknowledge one genuine gap and say how it is being closed, when a gap is
  obvious. This reads as self-awareness rather than weakness
- One page maximum; four to five short paragraphs
- Match the posting's language (German posting, German letter)
