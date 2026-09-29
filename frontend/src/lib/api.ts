import {
  ApiError,
  type ApiErrorBody,
  type AnswerRequest,
  type AnswerResult,
  type ApprovalResult,
  type AppSettings,
  type ChatRequest,
  type ChatStreamEvent,
  type DocumentDraft,
  type DraftRequest,
  type FeedbackSummary,
  type FitResult,
  type FunnelCounts,
  type HealthResponse,
  type IndexResult,
  type InterviewOptions,
  type InterviewQuestion,
  type InterviewSession,
  type JobDetail,
  type JobFilters,
  type JobSummary,
  type PasteJobRequest,
  type Rating,
  type RateRequest,
  type MemoryFact,
  type MemoryPreview,
  type RememberRequest,
  type StartInterviewRequest,
  type SyncRequest,
  type SettingsUpdate,
  type SyncResult,
  type ResumeSlot,
  type ResumeUpload,
  type UsageSummary,
} from "@/lib/types"

/**
 * Same-origin by construction: in production FastAPI serves this bundle, and in
 * development Vite proxies /api to uvicorn. There is no base-URL setting to get
 * wrong and no CORS to configure.
 */
const BASE = "/api"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError(0, {
      code: "upstream_unavailable",
      message: "Could not reach the Praxa API. Is the server running?",
    })
  }

  if (!response.ok) {
    let body: ApiErrorBody = {
      code: "internal_error",
      message: `Request failed with status ${response.status}.`,
    }
    try {
      const parsed = (await response.json()) as Partial<ApiErrorBody>
      if (parsed && typeof parsed.code === "string" && typeof parsed.message === "string") {
        body = parsed as ApiErrorBody
      }
    } catch {
      // A non-JSON error body is itself the useful signal; keep the default.
    }
    throw new ApiError(response.status, body)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/* -------------------------------------------------------------------- chat */

/**
 * Opens the SSE stream for one chat turn.
 *
 * EventSource cannot POST, so the turn is created with a POST that returns a
 * stream id, and the stream is then read from a GET. `onEvent` receives every
 * parsed event in order; the returned function aborts the stream.
 */
export function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
): () => void {
  const controller = new AbortController()

  void (async () => {
    try {
      const response = await fetch(`${BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok || !response.body) {
        onEvent({
          type: "error",
          code: "upstream_unavailable",
          message: "The API did not return a stream.",
        })
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line.
        let split = buffer.indexOf("\n\n")
        while (split !== -1) {
          const frame = buffer.slice(0, split)
          buffer = buffer.slice(split + 2)
          const payload = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("")
          if (payload) {
            try {
              onEvent(JSON.parse(payload) as ChatStreamEvent)
            } catch {
              // A malformed frame should not kill the stream.
            }
          }
          split = buffer.indexOf("\n\n")
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return
      onEvent({
        type: "error",
        code: "upstream_unavailable",
        message: "The connection to the API was lost.",
      })
    }
  })()

  return () => controller.abort()
}

/* ------------------------------------------------------------------ routes */

export const api = {
  usage: (threadId?: string) =>
    request<UsageSummary>(
      threadId ? `/usage?threadId=${encodeURIComponent(threadId)}` : "/usage",
    ),

  health: () => request<HealthResponse>("/health"),

  /** Developer settings. Process-wide, and reverts on restart. */
  settings: {
    read: () => request<AppSettings>("/settings"),
    update: (body: SettingsUpdate) =>
      request<AppSettings>("/settings", { method: "POST", body: JSON.stringify(body) }),
  },

  /**
   * Ratings the user gave individual answers. Nothing here feeds back into how
   * the next answer is produced - see `routes/feedback.py` for why that is a
   * separate piece of work rather than an omission.
   */
  feedback: {
    read: (params?: { rating?: Rating; limit?: number }) => {
      const search = new URLSearchParams()
      if (params?.rating) search.set("rating", params.rating)
      if (params?.limit) search.set("limit", String(params.limit))
      const query = search.toString()
      return request<FeedbackSummary>(`/feedback${query ? `?${query}` : ""}`)
    },
    rate: (body: RateRequest) =>
      request<unknown>("/feedback", { method: "POST", body: JSON.stringify(body) }),
    unrate: (messageId: string) =>
      request<unknown>(`/feedback/${encodeURIComponent(messageId)}`, { method: "DELETE" }),
    clear: () => request<{ removed: number }>("/feedback", { method: "DELETE" }),
  },

  jobs: {
    list: (filters?: JobFilters) => {
      const search = new URLSearchParams()
      for (const [key, value] of Object.entries(filters ?? {})) {
        if (value !== undefined && value !== "") search.set(key, String(value))
      }
      const qs = search.toString()
      return request<JobSummary[]>(`/jobs${qs ? `?${qs}` : ""}`)
    },
    get: (id: string) => request<JobDetail>(`/jobs/${encodeURIComponent(id)}`),
    funnel: () => request<FunnelCounts>("/jobs/funnel"),
    /** Costs a model call and takes seconds. The caller shows a pending state. */
    score: (id: string) =>
      request<FitResult>(`/jobs/${encodeURIComponent(id)}/score`, { method: "POST" }),
    setStatus: (id: string, status: string, note?: string) =>
      request<JobDetail>(`/jobs/${encodeURIComponent(id)}/status`, {
        method: "POST",
        body: JSON.stringify({ status, note }),
      }),
    sources: () => request<string[]>("/jobs/sources"),
    /** Pull live postings from the job boards. Slow – it calls someone else's API. */
    sync: (body: SyncRequest = {}) =>
      request<SyncResult>("/jobs/sync", { method: "POST", body: JSON.stringify(body) }),
    paste: (posting: PasteJobRequest) =>
      request<JobDetail>("/jobs/paste", {
        method: "POST",
        body: JSON.stringify(posting),
      }),
  },

  /**
   * Generating a document and saving it are two calls on purpose: nothing
   * reaches the disk until `approve`. See `api/routes/documents.py`.
   */
  documents: {
    pending: () => request<DocumentDraft[]>("/documents/drafts"),
    draft: (body: DraftRequest) =>
      request<DocumentDraft>("/documents/draft", { method: "POST", body: JSON.stringify(body) }),
    approve: (id: string) =>
      request<ApprovalResult>(`/documents/${encodeURIComponent(id)}/approve`, { method: "POST" }),
    discard: (id: string) =>
      request<void>(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },

  /**
   * Replacing a CV rebuilds the whole index, so these calls are slow on
   * purpose and the UI says so rather than pretending otherwise.
   */
  resumes: {
    list: () => request<ResumeSlot[]>("/resumes"),
    upload: (body: ResumeUpload) =>
      request<IndexResult>("/resumes", { method: "POST", body: JSON.stringify(body) }),
    remove: (profile: string) =>
      request<IndexResult>(`/resumes/${encodeURIComponent(profile)}`, { method: "DELETE" }),
    /** One CV off the General shelf, addressed by its own id rather than by track. */
    removeGeneral: (id: string) =>
      request<IndexResult>(`/resumes/general/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },

  /**
   * Scoring and asking are two calls on purpose. Doing both in one request
   * meant several seconds of nothing before anything appeared; split, the
   * score - the part the candidate is waiting for - arrives first and the next
   * question loads behind it.
   */
  interview: {
    options: () => request<InterviewOptions>("/interview/options"),
    start: (body: StartInterviewRequest) =>
      request<InterviewSession>("/interview/sessions", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    /** Rebuild a session from the stored rows, after a refresh or in a new tab. */
    resume: (id: string) =>
      request<InterviewSession>(`/interview/sessions/${encodeURIComponent(id)}`),
    answer: (id: string, body: AnswerRequest) =>
      request<AnswerResult>(`/interview/sessions/${encodeURIComponent(id)}/answers`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    next: (id: string) =>
      request<InterviewQuestion>(`/interview/sessions/${encodeURIComponent(id)}/next`, {
        method: "POST",
      }),
  },

  memory: {
    list: () => request<MemoryFact[]>("/memory"),
    /** The prompt block memory will contribute, straight from `recall_block`. */
    preview: () => request<MemoryPreview>("/memory/preview"),
    /** Stated outright by the user, which the server records as `stated`. */
    add: (body: RememberRequest) =>
      request<MemoryFact>("/memory", { method: "POST", body: JSON.stringify(body) }),
    remove: (id: number) => request<void>(`/memory/${id}`, { method: "DELETE" }),
    clear: () => request<{ removed: number }>("/memory", { method: "DELETE" }),
  },
}
