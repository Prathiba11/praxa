import {
  ArrowLeft,
  Check,
  ChevronDown,
  Copy,
  Download,
  FileText,
  FileUp,
  Loader2,
  Mail,
  RotateCw,
  Sparkles,
  Trash2,
} from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"

import { PageHero } from "@/components/layout/hero"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { DocumentDraft, DraftKind, JobSummary, Profile, ResumeSlot } from "@/lib/types"
import { Markdown } from "@/components/ui/markdown"
import { headings } from "@/lib/markdown"
import { STRONG_FIT, cn, fitPercent, formatRelative } from "@/lib/utils"

/**
 * Profile → job → generate → read → decide.
 *
 * The page is built around one property that is easy to lose and expensive to
 * get wrong: **nothing is written until a person approves it.** A tailored CV
 * is the only thing this application produces that leaves the machine with the
 * user's name on it, so generation and saving are separate calls in the API and
 * separate actions here. Discard leaves no file, and that is the behaviour the
 * page keeps saying out loud rather than assuming the user will guess it.
 *
 * Everything shown is something the backend actually returned. The alignment
 * score appears only on postings that have really been scored; the insights
 * panel is the reviewing agent's own output, not a decorative summary. Nothing
 * on this page is invented to fill a space - an interface that shows a
 * confident number nobody computed is worse than one that shows nothing.
 */

const PROFILE_LABEL: Record<Profile, string> = {
  automotive_cyber: "Automotive cybersecurity",
  devops: "DevOps",
  ai_eng: "AI engineering",
  general: "General",
}

const PROFILE_TAGLINE: Record<Profile, string> = {
  automotive_cyber: "Vehicle security · standards · testing",
  devops: "Platform · delivery · reliability",
  ai_eng: "Retrieval · pipelines · model safety",
  general: "Anything the three tracks do not cover",
}

const PROFILE_SKILLS: Record<Profile, string[]> = {
  automotive_cyber: ["ISO 21434", "UNECE R155", "TARA", "ECU testing"],
  devops: ["Kubernetes", "CI/CD", "GitOps", "DORA"],
  ai_eng: ["RAG", "MLOps", "LLMOps", "Evaluation"],
  general: ["CV structure", "Evidence", "Interviews"],
}

const STEPS = [
  { key: "profile", index: "01", title: "Profile", hint: "Choose your CV" },
  { key: "job", index: "02", title: "Job", hint: "Choose or paste a posting" },
  { key: "create", index: "03", title: "Generate", hint: "Create your document" },
] as const

type StepKey = (typeof STEPS)[number]["key"]

export function DocumentsRoute() {
  const [step, setStep] = useState<StepKey>("profile")
  const [slots, setSlots] = useState<ResumeSlot[] | null>(null)
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)

  // The Jobs page can send a posting straight here: /documents?job=<id>.
  // Without this the link would drop you on step 1 with nothing selected,
  // which is the same as no link at all.
  const [search] = useSearchParams()
  const handedOver = search.get("job")

  const [profile, setProfile] = useState<Profile | null>(null)
  const [jobId, setJobId] = useState<string | null>(handedOver)
  const [jobText, setJobText] = useState("")
  const [kind, setKind] = useState<DraftKind>("cv")
  const [language, setLanguage] = useState<"en" | "de">("en")

  const [draft, setDraft] = useState<DocumentDraft | null>(null)
  const [busy, setBusy] = useState<"generating" | "saving" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [uploading, setUploading] = useState<Profile | null>(null)

  const say = useCallback((text: string) => {
    setToast(text)
    window.setTimeout(() => setToast(null), 3200)
  }, [])

  useEffect(() => {
    let cancelled = false
    void api.resumes
      .list()
      .then((value) => !cancelled && setSlots(value))
      .catch(() => !cancelled && setSlots([]))
    return () => {
      cancelled = true
    }
  }, [])

  // Arriving from the Jobs page with ?job=<id>: adopt that posting's own track
  // and open on the step after it, so the link lands where the person expects
  // rather than at the start of a flow they already began on the other page.
  useEffect(() => {
    if (!handedOver || jobs === null) return
    const match = jobs.find((job) => job.id === handedOver)
    if (match?.profile) setProfile(match.profile)
    setStep((current) => (current === "profile" ? "job" : current))
  }, [handedOver, jobs])

  // Jobs are loaded for the track that was chosen, not once at mount. They
  // used to be fetched unfiltered before step 1 had even happened, so after
  // picking "DevOps" you were offered automotive postings to tailor a DevOps
  // CV against. The General shelf is the exception: nothing classifies as
  // general, so filtering by it would show an empty list - it sees everything.
  useEffect(() => {
    let cancelled = false
    setJobs(null)
    const filters = profile && profile !== "general" ? { profile } : {}
    void api.jobs
      .list(filters)
      .then((value) => !cancelled && setJobs(value))
      .catch(() => !cancelled && setJobs([]))
    return () => {
      cancelled = true
    }
  }, [profile])

  const jobChosen = jobId !== null || jobText.trim().length > 40
  const done: Record<StepKey, boolean> = {
    profile: profile !== null,
    job: jobChosen,
    create: draft !== null,
  }

  /** Uploading replaces the CV for that slot and rebuilds the search index. */
  async function uploadCv(target: Profile, file: File) {
    setUploading(target)
    setError(null)
    try {
      const content = await file.text()
      await api.resumes.upload({ profile: target, filename: file.name, content })
      setSlots(await api.resumes.list())
      say("CV replaced and re-indexed")
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setUploading(null)
    }
  }

  async function generate() {
    if (!profile || !jobChosen || busy) return
    setBusy("generating")
    setError(null)
    try {
      const result = await api.documents.draft({
        profile,
        kind,
        language,
        ...(jobId ? { jobId } : { jobText: jobText.trim() }),
      })
      setDraft(result)
      say("Draft ready – nothing saved yet")
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function approve() {
    if (!draft || busy) return
    setBusy("saving")
    try {
      const result = await api.documents.approve(draft.draftId)
      setDraft(null)
      say(`Approved – saved as ${result.files.join(" and ")}`)
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function discard() {
    if (!draft || busy) return
    setBusy("saving")
    try {
      await api.documents.discard(draft.draftId)
      setDraft(null)
      say("Discarded – nothing was written")
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="min-h-dvh">
      <PageHero
        eyebrow="Praxa · application studio"
        title="Turn a posting into an application"
        description="Pick the CV that fits, drop in the job, and read what comes back before anything is saved."
        actions={
          <Button variant="outline" size="sm" onClick={() => setStep("profile")}>
            <FileUp aria-hidden />
            Upload a CV
          </Button>
        }
      >
        <StepBar current={step} done={done} onGo={setStep} />
      </PageHero>

      <div className="mx-auto w-full max-w-6xl space-y-8 px-5 py-8 lg:px-8">

        {error ? (
          <ErrorPanel
            message={error}
            onRetry={() => {
              setError(null)
              void generate()
            }}
            onBack={() => {
              setError(null)
              setStep("job")
            }}
          />
        ) : null}

        {draft ? (
          <Workspace
            draft={draft}
            busy={busy}
            onApprove={approve}
            onDiscard={discard}
            onRegenerate={() => {
              setDraft(null)
              void generate()
            }}
            onCopied={() => say("Document copied")}
            onDownloaded={() => say("Downloaded")}
          />
        ) : (
          <>
            {step === "profile" ? (
              <ProfileStep
                slots={slots}
                chosen={profile}
                uploading={uploading}
                onUpload={uploadCv}
                onChoose={(value) => {
                  setProfile(value)
                  setStep("job")
                }}
              />
            ) : null}

            {step === "job" ? (
              <JobStep
                jobs={jobs}
                jobId={jobId}
                jobText={jobText}
                onPick={(id) => {
                  setJobId(id)
                  setJobText("")
                  setStep("create")
                }}
                onPaste={(text) => {
                  setJobText(text)
                  setJobId(null)
                }}
                onNext={() => setStep("create")}
              />
            ) : null}

            {step === "create" ? (
              <CreateStep
                kind={kind}
                language={language}
                busy={busy === "generating"}
                ready={Boolean(profile) && jobChosen}
                onKind={setKind}
                onLanguage={setLanguage}
                onGenerate={generate}
              />
            ) : null}
          </>
        )}

        <HowItWorks />
      </div>

      {toast ? (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 animate-fade-in rounded-full border bg-card px-4 py-2 text-sm shadow-lg"
        >
          {toast}
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------- steps */

function StepBar({
  current,
  done,
  onGo,
}: {
  current: StepKey
  done: Record<StepKey, boolean>
  onGo: (key: StepKey) => void
}) {
  return (
    <ol className="relative grid gap-3 sm:grid-cols-3">
      {STEPS.map((step, index) => {
        const isCurrent = step.key === current
        const isDone = done[step.key] && !isCurrent
        return (
          <li key={step.key} className="relative">
            {/* A connector that lives in the GAP between two cards, not behind
                them. It used to be one full-width line under all three, which
                worked until you looked at it: the cards are translucent, so the
                line showed straight through the middle of the active one. */}
            {index > 0 ? (
              <span
                aria-hidden
                className="absolute -left-3 top-[38px] hidden h-px w-3 bg-border sm:block"
              />
            ) : null}
            <button
              type="button"
              onClick={() => onGo(step.key)}
              aria-current={isCurrent ? "step" : undefined}
              className={cn(
                "group w-full rounded-2xl border px-5 py-4 text-left transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                isCurrent
                  ? "border-primary/50 bg-gradient-to-br from-primary/15 via-primary/5 to-transparent shadow-lg shadow-primary/5"
                  : "border-border/70 bg-card/50 backdrop-blur-sm hover:-translate-y-0.5 hover:border-border hover:bg-card/80",
              )}
            >
              <span className="flex items-center gap-3">
                <span
                  className={cn(
                    "grid size-8 shrink-0 place-items-center rounded-full border text-xs font-mono transition-all duration-200",
                    isDone
                      ? "border-success/50 bg-success/15 text-success"
                      : isCurrent
                        ? "border-primary/60 bg-primary/20 text-primary shadow-sm shadow-primary/20"
                        : "border-border text-muted-foreground",
                  )}
                >
                  {isDone ? <Check className="size-4" aria-label="done" /> : step.index}
                </span>
                <span
                  className={cn(
                    "text-base font-semibold tracking-tight transition-colors",
                    isCurrent ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {step.title}
                </span>
              </span>
              <span className="mt-2 block pl-11 text-sm text-muted-foreground">{step.hint}</span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

/* ----------------------------------------------------------------- profile */

function ProfileStep({
  slots,
  chosen,
  onChoose,
  onUpload,
  uploading,
}: {
  slots: ResumeSlot[] | null
  chosen: Profile | null
  onChoose: (profile: Profile) => void
  onUpload: (profile: Profile, file: File) => void
  uploading: Profile | null
}) {
  if (slots === null) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-52 w-full" />
        <Skeleton className="h-52 w-full" />
        <Skeleton className="h-52 w-full" />
      </div>
    )
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">Choose your profile</h2>
        <p className="text-xs text-muted-foreground">
          Not your field? Upload your own CV into any slot.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {slots.map((slot) => (
          <ProfileCard
            key={slot.profile}
            slot={slot}
            selected={slot.profile === chosen}
            uploading={uploading === slot.profile}
            onChoose={() => onChoose(slot.profile)}
            onUpload={(file) => onUpload(slot.profile, file)}
          />
        ))}
      </div>
    </section>
  )
}

function ProfileCard({
  slot,
  selected,
  uploading,
  onChoose,
  onUpload,
}: {
  slot: ResumeSlot
  selected: boolean
  uploading: boolean
  onChoose: () => void
  onUpload: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)

  return (
    <div
      className={cn(
        "group relative flex h-full flex-col overflow-hidden rounded-2xl border transition-all duration-200",
        selected
          ? "border-primary/50 bg-gradient-to-br from-primary/10 via-card/60 to-card/40 shadow-lg shadow-primary/5"
          : "border-border/70 bg-card/40 hover:-translate-y-1 hover:border-border hover:bg-card/70 hover:shadow-lg hover:shadow-black/20",
      )}
    >
      {/* A hairline that lights up on the chosen card. Cheaper than a glow and
          it survives a light theme, where a glow just looks like a smudge. */}
      <span
        aria-hidden
        className={cn(
          "absolute inset-x-0 top-0 h-px transition-opacity duration-200",
          selected
            ? "bg-gradient-to-r from-transparent via-primary to-transparent opacity-100"
            : "opacity-0",
        )}
      />

      <button
        type="button"
        onClick={onChoose}
        aria-pressed={selected}
        className="flex flex-1 flex-col gap-4 p-6 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex items-start justify-between gap-3">
          <span className="space-y-1">
            <span className="block text-lg font-semibold leading-tight tracking-tight">
              {PROFILE_LABEL[slot.profile]}
            </span>
            <span className="block text-sm text-muted-foreground">
              {PROFILE_TAGLINE[slot.profile]}
            </span>
          </span>
          {slot.isYours ? (
            <Badge variant="success">Yours</Badge>
          ) : (
            <Badge variant="warning">Sample</Badge>
          )}
        </span>

        <span className="flex flex-wrap gap-1.5">
          {PROFILE_SKILLS[slot.profile].map((skill) => (
            <span
              key={skill}
              className={cn(
                "rounded-md border px-2 py-0.5 text-xs transition-colors",
                selected
                  ? "border-primary/30 bg-primary/10 text-foreground"
                  : "border-border/60 bg-secondary/40 text-muted-foreground",
              )}
            >
              {skill}
            </span>
          ))}
        </span>

        <span className="mt-auto flex items-center gap-2 text-xs text-muted-foreground">
          {slot.isYours ? (
            <>
              <span className="size-1.5 rounded-full bg-success" aria-hidden />
              {`${slot.characters.toLocaleString()} characters${
                slot.updatedAt ? ` · updated ${formatRelative(slot.updatedAt)}` : ""
              }`}
            </>
          ) : (
            <>
              <span className="size-1.5 rounded-full bg-warning" aria-hidden />
              This one describes an invented person
            </>
          )}
        </span>
      </button>

      <div className="border-t border-border/60 bg-background/30 px-6 py-3">
        <input
          ref={input}
          type="file"
          accept=".md,.markdown,.txt,text/plain,text/markdown"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUpload(file)
            event.target.value = ""
          }}
        />
        <Button
          variant="ghost"
          size="sm"
          className="h-auto w-full justify-start px-0 py-0 text-muted-foreground hover:bg-transparent hover:text-primary"
          onClick={() => input.current?.click()}
          disabled={uploading}
        >
          {uploading ? <Loader2 className="animate-spin" aria-hidden /> : <FileUp aria-hidden />}
          {uploading ? "Indexing…" : slot.isYours ? "Replace this CV" : "Upload your CV"}
        </Button>
        {/*
          Said out loud, because the picker greys out everything else and a
          dialog that closes with nothing selected looks like a broken button.
          A .docx here would be read as text and stored as binary noise.
        */}
        <p className="mt-1 text-xs text-muted-foreground">
          Markdown or plain text (.md, .txt). Export a Word CV to one of those first.
        </p>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------- job */

function JobStep({
  jobs,
  jobId,
  jobText,
  onPick,
  onPaste,
  onNext,
}: {
  jobs: JobSummary[] | null
  jobId: string | null
  jobText: string
  onPick: (id: string) => void
  onPaste: (text: string) => void
  onNext: () => void
}) {
  // A job you moved into the funnel on the Jobs page is one you already
  // decided about. Those come first here, because "I marked this interested"
  // is a far stronger signal of what you want to write for than "this was
  // fetched recently". Nothing is hidden - the rest follow underneath.
  const shortlisted = (jobs ?? []).filter((job) => job.status !== null && job.status !== undefined)
  const untriaged = (jobs ?? []).filter((job) => job.status === null || job.status === undefined)
  const shown = [...shortlisted, ...untriaged].slice(0, 8)

  return (
    <section className="space-y-6">
      {jobs === null ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : jobs.length > 0 ? (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            {shortlisted.length > 0 ? "From your shortlist" : "Choose a job"}
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {shown.map((job) => (
              <button
                key={job.id}
                type="button"
                onClick={() => onPick(job.id)}
                className={cn(
                  "flex flex-col gap-1.5 rounded-xl border p-4 text-left transition-all duration-200",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  job.id === jobId
                    ? "border-primary/60 bg-primary/5"
                    : "bg-card/40 hover:-translate-y-0.5 hover:bg-card/70",
                )}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{job.title}</span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {job.company}
                      {job.location ? ` · ${job.location}` : ""}
                    </span>
                  </span>
                  {/* Shown only when something actually scored it. */}
                  {typeof job.fitScore === "number" ? (
                    <Badge
                      variant={job.fitScore >= STRONG_FIT ? "success" : "outline"}
                      title="How much of this posting your CV evidences"
                    >
                      {fitPercent(job.fitScore)}%
                    </Badge>
                  ) : null}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {job.status ? (
                    <span className="rounded-full border border-primary/40 px-1.5 py-px font-mono text-primary">
                      {job.status}
                    </span>
                  ) : null}
                  Added {formatRelative(job.firstSeenAt)}
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <h2 className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-muted-foreground">
          <span>
            {jobs && jobs.length > 0 ? "Or paste a job description" : "Paste a job description"}
          </span>
          <Link
            to="/jobs"
            className="text-xs font-normal text-primary underline-offset-2 hover:underline"
          >
            Find and triage postings on the Jobs page
          </Link>
        </h2>
        <textarea
          value={jobText}
          onChange={(event) => onPaste(event.target.value)}
          rows={9}
          placeholder="Paste the complete job description here…"
          className="w-full resize-y rounded-xl border bg-card/40 px-4 py-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <p className="text-xs text-muted-foreground">
          Include the requirements section – it is what the gaps are measured against.
        </p>
      </div>

      <Button onClick={onNext} disabled={!jobId && jobText.trim().length <= 40}>
        Continue
      </Button>
    </section>
  )
}

/* ------------------------------------------------------------------ create */

function CreateStep({
  kind,
  language,
  busy,
  ready,
  onKind,
  onLanguage,
  onGenerate,
}: {
  kind: DraftKind
  language: "en" | "de"
  busy: boolean
  ready: boolean
  onKind: (kind: DraftKind) => void
  onLanguage: (language: "en" | "de") => void
  onGenerate: () => void
}) {
  const options = [
    {
      key: "cv" as const,
      title: "Tailored CV",
      blurb: "Reorder and re-word your existing CV for this role. No new facts.",
      Icon: FileText,
    },
    {
      key: "letter" as const,
      title: "Cover letter",
      blurb: "A focused letter for this application, grounded only in your CV.",
      Icon: Mail,
    },
  ]

  return (
    <section className="space-y-6">
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Create your application</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {options.map(({ key, title, blurb, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onKind(key)}
              aria-pressed={key === kind}
              className={cn(
                "flex items-start gap-4 rounded-xl border p-5 text-left transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                key === kind
                  ? "border-primary/60 bg-primary/5 shadow-sm"
                  : "bg-card/40 hover:-translate-y-0.5 hover:bg-card/70",
              )}
            >
              <Icon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
              <span>
                <span className="block font-medium">{title}</span>
                <span className="mt-1 block text-sm text-muted-foreground">{blurb}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {kind === "letter" ? (
        <div className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground">Language</h2>
          <div className="flex gap-2">
            {(["en", "de"] as const).map((value) => (
              <Button
                key={value}
                variant={value === language ? "default" : "outline"}
                size="sm"
                onClick={() => onLanguage(value)}
              >
                {value === "en" ? "English" : "Deutsch"}
              </Button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            German postings usually expect a German letter.
          </p>
        </div>
      ) : null}

      <div className="space-y-2">
        <Button size="lg" onClick={onGenerate} disabled={!ready || busy} className="w-full sm:w-auto">
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
          {busy ? "Generating your application…" : "Generate tailored application"}
        </Button>
        <p className="text-xs text-muted-foreground">Nothing is saved until you approve it.</p>
      </div>

      {busy ? <GeneratingSkeleton /> : null}
    </section>
  )
}

function GeneratingSkeleton() {
  return (
    <div className="space-y-3 rounded-xl border bg-card/40 p-6">
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-11/12" />
      <Skeleton className="h-3 w-4/5" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  )
}

/* --------------------------------------------------------------- workspace */

const VERDICT = {
  ok: {
    label: "Every claim traces to your CV",
    tone: "border-success/40 bg-success/5",
    badge: "success" as const,
  },
  concerns: {
    label: "Check these before you send it",
    tone: "border-warning/40 bg-warning/5",
    badge: "warning" as const,
  },
  unavailable: {
    label: "Not reviewed",
    tone: "border-border bg-muted/20",
    badge: "outline" as const,
  },
}

function Workspace({
  draft,
  busy,
  onApprove,
  onDiscard,
  onRegenerate,
  onCopied,
  onDownloaded,
}: {
  draft: DocumentDraft
  busy: "generating" | "saving" | null
  onApprove: () => void
  onDiscard: () => void
  onRegenerate: () => void
  onCopied: () => void
  onDownloaded: () => void
}) {
  const verdict = VERDICT[draft.review.verdict]
  const anchor = useRef<HTMLAnchorElement>(null)
  // The nav has to exist before anything renders, so the headings are read
  // from the source rather than from the rendered tree. `headings()` and the
  // renderer use the same slugger, walked in the same order, which is what
  // makes these anchors land.
  const sections = headings(draft.body)

  function download() {
    const blob = new Blob([draft.body], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = anchor.current
    if (!link) return
    link.href = url
    link.download = `${draft.kind}_${draft.profile}.md`
    link.click()
    URL.revokeObjectURL(url)
    onDownloaded()
  }

  return (
    <section className="animate-fade-in space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold">
            {draft.kind === "cv" ? "Tailored CV" : "Cover letter"}
          </h2>
          <p className="truncate text-sm text-muted-foreground">{draft.jobLabel}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(draft.body).then(onCopied)
            }}
            aria-label="Copy the document"
          >
            <Copy aria-hidden />
            Copy
          </Button>
          <Button variant="ghost" size="sm" onClick={download} aria-label="Download as Markdown">
            <Download aria-hidden />
            Download
          </Button>
          <Button variant="ghost" size="sm" onClick={onRegenerate} disabled={busy !== null}>
            <RotateCw aria-hidden />
            Regenerate
          </Button>
          <Button variant="outline" size="sm" onClick={onDiscard} disabled={busy !== null}>
            <Trash2 aria-hidden />
            Discard
          </Button>
          <Button onClick={onApprove} disabled={busy !== null}>
            {busy === "saving" ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
            Approve &amp; save
          </Button>
        </div>
        <a ref={anchor} className="hidden" aria-hidden />
      </div>

      <div className="grid gap-5 xl:grid-cols-[190px_minmax(0,1fr)_320px]">
        {/* Section navigation, built from the document's own headings rather
            than a fixed list - a cover letter has different sections from a CV,
            and inventing headings it does not have would be a lie about it. */}
        <nav className="hidden xl:block">
          <p className="px-3 pb-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Sections
          </p>
          <ul className="space-y-0.5">
            {sections.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="block truncate rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {section.text}
                </a>
              </li>
            ))}
            {sections.length === 0 ? (
              <li className="px-3 text-sm text-muted-foreground">No headings</li>
            ) : null}
          </ul>
        </nav>

        {/* A page, not a textarea. The thing being judged is a document, and it
            should be readable as one before anyone decides to send it. */}
        <article className="rounded-xl border bg-background/60 px-7 py-9 shadow-sm sm:px-10 lg:px-14">
          <Markdown>{draft.body}</Markdown>
        </article>

        <aside className="space-y-4">
          <div className={cn("space-y-2 rounded-xl border p-4", verdict.tone)}>
            <p className="flex items-center justify-between gap-2 text-sm font-medium">
              Review
              <Badge variant={verdict.badge}>{draft.review.verdict}</Badge>
            </p>
            <p className="text-sm text-muted-foreground">{verdict.label}</p>
            {draft.review.invented.length > 0 ? (
              <ul className="space-y-1 pt-1 text-sm">
                {draft.review.invented.map((claim) => (
                  <li key={claim} className="flex gap-2">
                    <span aria-hidden>•</span>
                    <span>{claim}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {draft.review.notes ? (
              <p className="text-xs text-muted-foreground">{draft.review.notes}</p>
            ) : null}
            <p className="pt-1 text-xs text-muted-foreground">
              A second agent read this against your CV. It advises – you decide.
            </p>
          </div>

          {draft.gaps ? (
            <div className="space-y-2 rounded-xl border bg-card/40 p-4">
              <p className="text-sm font-medium">Gaps against this posting</p>
              <div className="text-sm text-muted-foreground">
                <Markdown compact>{draft.gaps}</Markdown>
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  )
}

/* The Markdown renderer lives in `components/ui/markdown.tsx` - one renderer,
   used by this page and by the chat bubble. It is `react-markdown` with
   `remark-gfm` and raw HTML left disabled; the hand-written parser it replaced
   could not render code blocks, tables or links, which is most of what a
   DevOps or AI-engineering answer is made of. */

function ErrorPanel({
  message,
  onRetry,
  onBack,
}: {
  message: string
  onRetry: () => void
  onBack: () => void
}) {
  return (
    <div className="space-y-3 rounded-xl border border-destructive/40 bg-destructive/5 p-5">
      <h2 className="font-medium">We couldn&apos;t generate the document</h2>
      <p className="text-sm text-muted-foreground">{message}</p>
      <p className="text-sm text-muted-foreground">Your existing data is safe – nothing was saved.</p>
      <div className="flex gap-2">
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
        <Button size="sm" variant="outline" onClick={onBack}>
          <ArrowLeft aria-hidden />
          Back to the job
        </Button>
      </div>
    </div>
  )
}

function HowItWorks() {
  const [open, setOpen] = useState(false)
  const steps = [
    "Your CV and the posting are read as separate documents",
    "The posting is treated as data, never as instructions",
    "A writing agent reorders and re-words what your CV already says",
    "A second agent checks every claim against your CV",
    "You approve – and only then is anything written",
  ]

  return (
    <div className="rounded-xl border bg-card/30">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-5 py-3 text-sm font-medium transition-colors hover:bg-card/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        How it works
        <ChevronDown
          className={cn("size-4 transition-transform duration-200", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? (
        <ol className="animate-fade-in space-y-2 border-t px-5 py-4 text-sm text-muted-foreground">
          {steps.map((text, index) => (
            <li key={text} className="flex gap-3">
              <span className="font-mono text-xs text-primary">{`0${index + 1}`}</span>
              {text}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  )
}
