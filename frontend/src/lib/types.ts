/**
 * The API contract, written from the client's side.
 *
 * These types mirror the Pydantic models the FastAPI layer will expose under
 * /api. Keeping them in one file means there is a single place to check when
 * the backend changes shape, and it lets the views be built before the
 * endpoints exist.
 */

/** Which set of tools the agent is allowed to reach on this turn. */
export type Mode = "chat" | "jobs" | "interview"

/* ------------------------------------------------------------------ errors */

/**
 * Every non-2xx response from /api uses this body. The `code` is what the UI
 * branches on; `message` is safe to show to a person as-is.
 */
export interface ApiErrorBody {
  code: ApiErrorCode
  message: string
  /**
   * Eight characters shared with the server's log line for this failure.
   * The technical detail itself is never sent – this is how it is found.
   */
  correlationId?: string
}

export type ApiErrorCode =
  | "budget_exhausted"
  | "rate_limited"
  | "moderation_blocked"
  | "insufficient_evidence"
  | "tool_not_permitted"
  | "invalid_request"
  | "not_found"
  | "upstream_unavailable"
  | "internal_error"

export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly status: number
  readonly correlationId?: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = "ApiError"
    this.code = body.code
    this.status = status
    this.correlationId = body.correlationId
  }
}

/* -------------------------------------------------------------------- chat */

export interface Citation {
  /** 1-based marker as it appears in the answer text. */
  marker: number
  documentId: string
  documentTitle: string
  section?: string
  /** The exact passage the answer drew on. */
  snippet: string
  score?: number
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Citation[]
  createdAt: string
  /**
   * The server's id for this answer, which arrives on the `done` frame. Absent
   * until the turn finishes, and absent forever on a turn that failed - which
   * is exactly right: an answer that never completed is not one you can rate.
   */
  serverId?: string
  /** Which model wrote it. Stored with a rating so "the answer was wrong" can
   * later be read as "this model was wrong on this kind of question". */
  model?: string
}

export interface ChatRequest {
  threadId: string
  mode: Mode
  message: string
}

/**
 * One event on the SSE stream. The retrieval events are what make the agent
 * loop visible: a `retrieval` event per round, with the grader's verdict.
 */
export type ChatStreamEvent =
  | { type: "status"; phase: AgentPhase; detail?: string }
  | {
      type: "retrieval"
      round: number
      verdict: EvidenceVerdict
      query: string
      sources: number
      /** The grader's one-line justification for the verdict. */
      reason?: string
    }
  | { type: "tool"; name: string; state: "started" | "finished" | "error" }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done"; messageId: string; usage: TurnUsage }
  | { type: "error"; code: ApiErrorCode; message: string; correlationId?: string }
  /**
   * The last frame on every stream, success or failure. Without it a stream
   * cut short by a dead server is indistinguishable from one that finished.
   */
  | { type: "end" }

export type AgentPhase =
  | "moderating"
  | "thinking"
  | "searching"
  | "grading"
  | "requerying"
  | "answering"

/** What the retrieval grader decided about the evidence it was given. */
export type EvidenceVerdict = "sufficient" | "weak" | "none"

/* ------------------------------------------------------------------- usage */

export interface TurnUsage {
  promptTokens: number
  completionTokens: number
  costUsd: number
  /** Where `costUsd` came from. Only "openrouter" is a real charge. */
  costSource: CostSource
  model: string
  latencyMs: number
}

/** "mixed" means a turn whose calls were not all priced the same way. */
export type CostSource = "openrouter" | "estimated" | "unknown" | "mixed"

export interface UsageSummary {
  sessionTokens: number
  sessionCostUsd: number
  sessionBudgetUsd: number
  monthToDateUsd: number
  monthlyBudgetUsd: number
  /**
   * The smaller of the two headrooms – the one that will stop the next turn.
   * A client can mint a new thread id and reset its session ceiling; it
   * cannot mint a new month.
   */
  budgetRemainingUsd: number
  /** What one answer is expected to cost with the current settings. */
  estimatedCostPerAnswerUsd: number
  /** Calls with no real price. A total built from these understates spend. */
  unpricedCalls: number
}

/* -------------------------------------------------------------------- jobs */

export type Profile = "automotive_cyber" | "devops" | "ai_eng" | "general"

export type ApplicationStatus =
  | "interested"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn"

/** One row in the list. Enough to decide whether to open it. */
export interface JobSummary {
  id: string
  title: string
  company: string
  location?: string | null
  url?: string | null
  /** Where it came from. Attribution is a licence condition on some boards. */
  source: string
  profile?: Profile | null
  /** 0–100, or null when nobody has scored it yet. */
  fitScore?: number | null
  /** null means untriaged – nobody has looked at it, which is a real state. */
  status?: ApplicationStatus | null
  postedAt?: string | null
  firstSeenAt: string
}

export interface JobDetail extends JobSummary {
  description: string
  language?: string | null
  note?: string | null
  cvPath?: string | null
  letterPath?: string | null
}

export interface FunnelCounts {
  counts: Record<string, number>
  totalJobs: number
}

/** The result of scoring one posting against the CV for its track. */
export interface FitResult {
  profile: Profile
  /** Evidence only, 0–1. Stated preferences never move it; they land in conflicts. */
  score: number
  matched: string[]
  missing: string[]
  blockers: string[]
  conflicts: string[]
  verdict: string
}

export interface JobFilters {
  profile?: Profile
  location?: string
  company?: string
  status?: ApplicationStatus
  query?: string
  minFit?: number
  /** Also return postings the classifier could not place in a profile. */
  includeUnmatched?: boolean
}

export interface PasteJobRequest {
  /** The only required field. Title and company are read out of it when blank. */
  description: string
  title?: string
  company?: string
  location?: string
  url?: string
  profile?: Profile
}

/* The interview shapes live at the bottom of this file, next to the rest of
   the session API. An earlier set stood here - written before the endpoints
   existed, which is the habit this file's own header describes - and it did
   not survive contact with them: it carried a `role` string where the server
   sends a profile and a persona, no grounding on a question, no overall score,
   and no move. Nothing imported it. Two sets of types for one endpoint is
   worse than none, so the speculative one is gone rather than kept for the
   sake of the words already written. */

/* ------------------------------------------------------------------ memory */

export interface CategoryUse {
  category: MemoryCategory
  count: number
}

/** What memory will contribute to the next answer, as the server assembles it. */
export interface MemoryPreview {
  /** The prompt text itself. Empty when memory is off or nothing is stored. */
  block: string
  enabled: boolean
  stored: number
  maxStored: number
  maxPerCategory: number
  maxPerAnswer: number
  perCategory: CategoryUse[]
  leastRecentlyMentioned: string | null
}

export interface MemoryFact {
  /** The database row. Deleting is `DELETE /api/memory/{id}`. */
  id: number
  category: MemoryCategory
  text: string
  /** How it got here: extracted from a finished turn, or stated outright. */
  origin: "extracted" | "stated"
  createdAt: string
  /** Bumped whenever a turn restates it. Recency decides what survives the cap. */
  lastSeenAt: string
}

export interface RememberRequest {
  text: string
  category: MemoryCategory
}

export type MemoryCategory =
  | "role"
  | "location"
  | "language"
  | "must_have"
  | "deal_breaker"
  | "application"
  | "other"

/* ---------------------------------------------------------------- settings */

export interface ModelOption {
  id: string
  label: string
  inputPricePerMTok: number
  outputPricePerMTok: number
}

export interface Settings {
  model: string
  temperature: number
  maxTokens: number
  moderationEnabled: boolean
  tracingEnabled: boolean
}

/* --------------------------------------------------------------- documents */

export type DraftKind = "cv" | "letter"

/**
 * What the reviewing agent found.
 *
 * `unavailable` is a third value on purpose: a draft whose review did not run
 * must not look like a draft that passed. Rendering it as a neutral badge
 * rather than a green one is the whole point of keeping them apart.
 */
export interface DocumentReview {
  verdict: "ok" | "concerns" | "unavailable"
  /** Claims in the draft the source CV does not support, quoted. */
  invented: string[]
  notes: string
}

/** A generated document waiting for a person to approve or discard it. */
export interface DocumentDraft {
  draftId: string
  kind: DraftKind
  profile: Profile
  language: "en" | "de"
  jobLabel: string
  jobId: string | null
  body: string
  /** The "Gaps against this posting" section, lifted out of `body`. */
  gaps: string
  review: DocumentReview
  createdAt: string
}

export interface DraftRequest {
  profile: Profile
  kind: DraftKind
  jobId?: string
  jobText?: string
  language?: "en" | "de"
}

export interface ApprovalResult {
  draftId: string
  files: string[]
  message: string
}

/* ----------------------------------------------------------------- resumes */

/** One of the three CV slots, and whether a real CV is filling it. */
export interface ResumeSlot {
  profile: Profile
  /** Identifies the row. The profile name for a track, the file stem on the shelf. */
  id: string
  /** Taken from the document's first heading, so rows are told apart by name. */
  label: string
  isYours: boolean
  characters: number
  updatedAt: string | null
  /** The General CV that tailoring would read right now. At most one is true. */
  inUse?: boolean
}

export interface ResumeUpload {
  profile: Profile
  filename: string
  content: string
}

export interface IndexResult {
  profile: Profile
  documents: number
  chunks: number
  message: string
}

/* ------------------------------------------------------------- job sources */

export interface SyncRequest {
  source?: string
  limit?: number
  keywords?: string[]
  location?: string
  remoteOnly?: boolean
}

export interface SourceReport {
  source: string
  fetched: number
  added: number
  updated: number
  /** Postings the classifier could not assign a profile to. */
  unclassified: number
  /** Set when that one board could not be reached; the others still ran. */
  error: string | null
}

export interface SyncResult {
  reports: SourceReport[]
  added: number
  message: string
}

/* ---------------------------------------------------------------- health */

export interface HealthResponse {
  status: "ok"
  version: string
  tracing: boolean
  /** Null when tracing is off. */
  tracingProject: string | null
  tracingUrl: string | null
}

/* -------------------------------------------------------------- settings */

export interface ModelOption {
  id: string
  label: string
  provider: string
  /** USD per million tokens - the unit people compare in. */
  inputPerMtok: number
  outputPerMtok: number
  note: string
  /** Working notes for this application, not benchmark scores. */
  strengths: string[]
  caution: string
}

export interface AppSettings {
  chatModel: string
  graderModel: string
  temperature: number
  maxTokens: number
  sessionBudgetUsd: number
  monthlyBudgetUsd: number
  tracing: boolean
  models: ModelOption[]
  /** True when .env names a model that is not one of the offered options. */
  customModel: boolean
}

export interface SettingsUpdate {
  chatModel?: string
  graderModel?: string
  temperature?: number
  maxTokens?: number
}

/* --------------------------------------------------------------- interview */

export type Difficulty = "warmup" | "standard" | "hard"

/** What happens after an answer is scored. */
export type Move = "probe" | "next" | "finish"

export interface Persona {
  key: string
  name: string
  /** Their opening line. Carried because a name alone says little. */
  opening: string
}

export interface InterviewOptions {
  personas: Persona[]
  difficulties: Difficulty[]
  defaultPersona: string
  defaultQuestions: number
}

export interface StartInterviewRequest {
  profile: Profile
  persona: string
  difficulty: Difficulty
  questions: number
  jobId?: string
}

export interface InterviewQuestion {
  text: string
  /** Where it came from. A question grounded in your own material and one
   *  invented from a profile name are different things. */
  grounding: string
  focus: string
}

/** One answer, graded on five dimensions out of five. */
export interface RubricScore {
  structure: number
  specificity: number
  ownership: number
  impact: number
  relevance: number
  overall: number
  feedback: string
  improvedAnswer: string
}

export interface InterviewTurn {
  question: string
  answer: string
  score: RubricScore
  isProbe: boolean
}

export interface AnswerRequest {
  question: string
  answer: string
  isProbe?: boolean
  capturedAs?: string
  durationSeconds?: number
}

export interface AnswerResult {
  score: RubricScore
  move: Move
  probe: InterviewQuestion | null
  summary: string | null
}

export interface InterviewSession {
  sessionId: string
  profile: Profile
  persona: Persona
  difficulty: Difficulty
  plannedQuestions: number
  jobId: string | null
  turns: InterviewTurn[]
  /** Only on a fresh start. A restore carries none: an unanswered question was
   *  never stored, so the page asks for a new one. */
  question: InterviewQuestion | null
}

/* ---------------------------------------------------------------- feedback */

export type Rating = "up" | "down"

export interface FeedbackEntry {
  id: number
  messageId: string
  rating: Rating
  mode: Mode
  model: string
  question: string
  answer: string
  createdAt: string
}

export interface ModeTally {
  mode: Mode
  up: number
  down: number
}

export interface FeedbackSummary {
  up: number
  down: number
  total: number
  /** Null rather than 0 when nothing is rated: "no ratings yet" and "every
   * rating was negative" are opposite readings of the same number. */
  approval: number | null
  maxStored: number
  byMode: ModeTally[]
  recent: FeedbackEntry[]
}

export interface RateRequest {
  messageId: string
  threadId: string
  rating: Rating
  mode: Mode
  model: string
  question: string
  answer: string
}
