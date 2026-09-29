import {
  Briefcase,
  CloudDownload,
  ExternalLink,
  FileText,
  Gauge,
  Loader2,
  Plus,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"

import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input, Textarea } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type {
  ApplicationStatus,
  FitResult,
  FunnelCounts,
  JobFilters,
  JobSummary,
  PasteJobRequest,
  Profile,
} from "@/lib/types"
import { STRONG_FIT, cn, fitPercent } from "@/lib/utils"

const PROFILE_LABEL: Record<Profile, string> = {
  automotive_cyber: "Automotive cyber",
  devops: "DevOps",
  ai_eng: "AI engineering",
  general: "General",
}

/** The funnel, in the order an application actually moves through it. */
const STATUSES: ApplicationStatus[] = [
  "interested",
  "applied",
  "screening",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
]

const STATUS_VARIANT: Record<ApplicationStatus, "secondary" | "success" | "destructive"> = {
  interested: "secondary",
  applied: "secondary",
  screening: "secondary",
  interview: "success",
  offer: "success",
  rejected: "destructive",
  withdrawn: "destructive",
}

function Funnel({ funnel }: { funnel: FunnelCounts }) {
  const engaged = STATUSES.reduce((total, status) => total + (funnel.counts[status] ?? 0), 0)
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground">
      <span>
        {funnel.totalJobs} saved · {engaged} triaged
      </span>
      {STATUSES.filter((status) => (funnel.counts[status] ?? 0) > 0).map((status) => (
        <span key={status}>
          {status} {funnel.counts[status]}
        </span>
      ))}
    </div>
  )
}

/**
 * One posting. The status control writes straight to the API rather than
 * asking the agent, because a status is a fact about what the user did – it is
 * not something to be inferred, and there is nothing for a model to add.
 */
/**
 * The score, and the four lists behind it.
 *
 * Shown only after the user asks for it, because it is a model call: several
 * seconds and a fraction of a cent per posting. Scoring every job on fetch
 * would be a bill nobody agreed to.
 *
 * `conflicts` is first and styled as a warning. It is the only section that can
 * overturn the number above it - a posting can evidence every requirement and
 * still be one the candidate has ruled out - and burying it under "Evidenced"
 * would be presenting the flattering half first.
 */
function FitPanel({ fit }: { fit: FitResult }) {
  const percent = fitPercent(fit.score)

  return (
    <div className="space-y-2 rounded-lg border bg-background/40 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{percent}% evidenced</span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          against your {PROFILE_LABEL[fit.profile]} CV
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-border/60">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${Math.max(percent, 2)}%` }}
        />
      </div>

      {fit.verdict ? <p className="text-xs leading-relaxed">{fit.verdict}</p> : null}

      <FitList label="Against what you said you want" items={fit.conflicts} tone="warning" />
      <FitList label="Blockers" items={fit.blockers} tone="warning" />
      <FitList label="Evidenced" items={fit.matched} tone="ok" />
      <FitList label="Missing" items={fit.missing} tone="muted" />
    </div>
  )
}

function FitList({
  label,
  items,
  tone,
}: {
  label: string
  items: string[]
  tone: "ok" | "warning" | "muted"
}) {
  if (items.length === 0) return null
  return (
    <div>
      <p
        className={cn(
          "font-mono text-[10px] uppercase tracking-wider",
          tone === "warning" ? "text-warning" : "text-muted-foreground",
        )}
      >
        {label}
      </p>
      <ul className="mt-0.5 space-y-0.5">
        {items.map((item) => (
          <li
            key={item}
            className={cn(
              "text-xs leading-relaxed",
              tone === "ok" ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

function JobCard({ job, onChanged }: { job: JobSummary; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)

  const [fit, setFit] = useState<FitResult | null>(null)
  const [scoring, setScoring] = useState(false)
  const [fitError, setFitError] = useState<string | null>(null)

  async function score() {
    setScoring(true)
    setFitError(null)
    try {
      setFit(await api.jobs.score(job.id))
      // The score is cached on the row, so the list should reflect it.
      onChanged()
    } catch (error) {
      setFitError((error as Error).message)
    } finally {
      setScoring(false)
    }
  }

  async function move(status: ApplicationStatus) {
    setBusy(true)
    try {
      await api.jobs.setStatus(job.id, status)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base">{job.title}</CardTitle>
          {job.fitScore != null ? (
            <Badge variant={job.fitScore >= STRONG_FIT ? "success" : "secondary"}>
              {fitPercent(job.fitScore)}% fit
            </Badge>
          ) : null}
        </div>
        <p className="text-sm text-muted-foreground">
          {job.company}
          {job.location ? ` · ${job.location}` : ""}
        </p>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {job.profile ? <Badge variant="outline">{PROFILE_LABEL[job.profile]}</Badge> : null}
          <Badge variant="outline">{job.source}</Badge>
          {job.status ? (
            <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
          ) : (
            <span className="font-mono text-[11px] text-muted-foreground">not triaged</span>
          )}
          {job.url ? (
            <a
              href={job.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              posting <ExternalLink className="size-3" aria-hidden />
            </a>
          ) : null}
        </div>

        {fit ? <FitPanel fit={fit} /> : null}
        {fitError ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {fitError}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => void score()} disabled={scoring}>
            {scoring ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Gauge className="size-3.5" aria-hidden />
            )}
            {scoring ? "Scoring\u2026" : fit ? "Score again" : "Score against my CV"}
          </Button>
          {/* The way out of this page. Scoring tells you whether a posting is
              worth the effort; this is what you do about it. Carrying the id
              means Documents opens on this posting with its own track already
              chosen, rather than at the start of a flow you just began here. */}
          <Link
            to={`/documents?job=${encodeURIComponent(job.id)}`}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-primary transition-colors hover:bg-primary/10"
          >
            <FileText className="size-3.5" aria-hidden />
            Tailor a CV
          </Link>
          {!fit && job.fitScore !== null && job.fitScore !== undefined ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              last scored {fitPercent(job.fitScore)}%
            </span>
          ) : null}
        </div>

        <div className="flex flex-wrap gap-1">
          {STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              disabled={busy || job.status === status}
              onClick={() => void move(status)}
              className={cn(
                "rounded border px-2 py-0.5 font-mono text-[10px] transition-colors",
                job.status === status
                  ? "border-primary text-primary"
                  : "text-muted-foreground hover:border-foreground hover:text-foreground",
                busy && "opacity-50",
              )}
            >
              {status}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function PasteForm({ onSaved }: { onSaved: () => void }) {
  const empty: PasteJobRequest = { description: "" }
  const [draft, setDraft] = useState<PasteJobRequest>(empty)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

  // The text alone is enough. Everything else is read out of it and can be
  // corrected afterwards, so nothing else gates the button.
  const ready = draft.description.trim().length >= 20

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.jobs.paste(draft)
      setDraft(empty)
      onSaved()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Could not save that posting.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Paste a posting</CardTitle>
        <p className="text-xs text-muted-foreground">
          Paste the whole posting. The role, the employer and the track are read from it.
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          placeholder="Paste the whole posting here…"
          className="min-h-[160px]"
          aria-label="Posting text"
        />

        <button
          type="button"
          onClick={() => setShowDetails((open) => !open)}
          className="text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          {showDetails ? "Hide" : "Set the title, employer or location myself"}
        </button>

        {showDetails ? (
          <div className="space-y-2 rounded-lg border bg-background/40 p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                value={draft.title ?? ""}
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                placeholder="Title"
                aria-label="Job title"
              />
              <Input
                value={draft.company ?? ""}
                onChange={(event) => setDraft({ ...draft, company: event.target.value })}
                placeholder="Company"
                aria-label="Company"
              />
            </div>
            <Input
              value={draft.location ?? ""}
              onChange={(event) => setDraft({ ...draft, location: event.target.value })}
              placeholder="Location"
              aria-label="Location"
            />
            <p className="text-xs text-muted-foreground">
              Anything left blank is read from the text above.
            </p>
          </div>
        ) : null}

        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button size="sm" disabled={!ready || busy} onClick={() => void save()}>
          <Plus aria-hidden /> Save posting
        </Button>
      </CardContent>
    </Card>
  )
}

export function JobsRoute() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)
  const [funnel, setFunnel] = useState<FunnelCounts | null>(null)
  const [filters, setFilters] = useState<JobFilters>({})
  const [message, setMessage] = useState<string | null>(null)
  const [pasting, setPasting] = useState(false)
  const [fetching, setFetching] = useState(false)

  const load = useCallback(() => {
    setMessage(null)
    api.jobs
      .list(filters)
      .then(setJobs)
      .catch((problem: Error) => setMessage(problem.message))
    api.jobs.funnel().then(setFunnel).catch(NOOP)
  }, [filters])

  useEffect(load, [load])

  /**
   * Pull live postings from the job boards.
   *
   * Slow on purpose - it is HTTP to someone else's server - so the button says
   * so rather than looking broken. One board being down still returns whatever
   * the other one found, which is why the result carries a message instead of
   * just a count.
   */
  async function fetchJobs() {
    setFetching(true)
    setMessage(null)
    try {
      const result = await api.jobs.sync({ limit: 30 })
      setMessage(result.message)
      load()
    } catch (problem) {
      setMessage((problem as Error).message)
    } finally {
      setFetching(false)
    }
  }

  return (
    <Page
      title="Jobs"
      description="Postings found for your three tracks: automotive cyber, DevOps, AI engineering. Score one against your CV here; tailored CVs and cover letters are made on the Documents page."
      actions={
        <>
          <Button size="sm" onClick={fetchJobs} disabled={fetching}>
            {fetching ? <Loader2 className="animate-spin" aria-hidden /> : <CloudDownload aria-hidden />}
            {fetching ? "Fetching…" : "Fetch jobs"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setPasting((open) => !open)}>
            <Plus aria-hidden /> Paste
          </Button>
        </>
      }
    >
      {funnel ? (
        <div className="mb-4">
          <Funnel funnel={funnel} />
        </div>
      ) : null}

      {pasting ? <PasteForm onSaved={load} /> : null}

      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        <Input
          value={filters.query ?? ""}
          onChange={(event) => setFilters({ ...filters, query: event.target.value })}
          placeholder="Words in the posting…"
          aria-label="Search postings"
        />
        <select
          value={filters.profile ?? ""}
          onChange={(event) =>
            setFilters({ ...filters, profile: (event.target.value || undefined) as Profile })
          }
          aria-label="Profile"
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">Any tracked profile</option>
          {Object.entries(PROFILE_LABEL)
            // `general` is excluded because no posting is ever assigned to it -
            // offering it would be a filter guaranteed to return nothing.
            .filter(([value]) => value !== "general")
            .map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
        </select>
        <select
          value={filters.status ?? ""}
          onChange={(event) =>
            setFilters({
              ...filters,
              status: (event.target.value || undefined) as ApplicationStatus,
            })
          }
          aria-label="Status"
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">Any status</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>

      {/* Postings the classifier could not place are stored but hidden. The
          count is shown rather than the rows: a silent filter is how you end up
          wondering where a job you saw yesterday went. */}
      <label className="mb-4 flex w-fit cursor-pointer items-center gap-2 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={filters.includeUnmatched ?? false}
          onChange={(event) =>
            setFilters({ ...filters, includeUnmatched: event.target.checked || undefined })
          }
          className="size-3.5 accent-primary"
        />
        Include postings that match none of your tracks
      </label>

      {message ? (
        <EmptyState icon={Briefcase} title="Could not load postings" description={message} />
      ) : jobs === null ? (
        <div className="grid gap-3 md:grid-cols-2">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-40 w-full" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="Nothing matches"
          description="Clear the filters, or paste a posting to get started."
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} onChanged={load} />
          ))}
        </div>
      )}

      <p className="mt-6 text-xs text-muted-foreground">
        Job data from Arbeitnow and Remotive. Remotive attribution is a condition of its licence
        and stays displayed.
      </p>
    </Page>
  )
}

/** The funnel is decoration; failing to load it must not blank the page. */
function NOOP() {}
