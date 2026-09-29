import {
  AlertTriangle,
  Brain,
  Eye,
  Gauge as GaugeIcon,
  MapPin,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { MemoryCategory, MemoryFact, MemoryPreview } from "@/lib/types"
import { formatRelative } from "@/lib/utils"

/**
 * The page exists for the delete button.
 *
 * Everything else here - the list, the origins, the form - is in service of a
 * user being able to see what the assistant believes about them and take any
 * of it away. A memory feature without this page is a system forming opinions
 * about someone in private.
 */

const CATEGORY_LABEL: Record<MemoryCategory, string> = {
  role: "Role",
  location: "Location",
  language: "Language",
  must_have: "Must have",
  deal_breaker: "Deal breaker",
  application: "Application",
  other: "Other",
}

const CATEGORIES = Object.keys(CATEGORY_LABEL) as MemoryCategory[]

export function MemoryRoute() {
  const [facts, setFacts] = useState<MemoryFact[] | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [text, setText] = useState("")
  const [category, setCategory] = useState<MemoryCategory>("other")
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<MemoryPreview | null>(null)
  const [confirming, setConfirming] = useState(false)

  /** The panel is derived from the store, so every change to the store refreshes it. */
  const refreshPreview = useCallback(() => {
    void api.memory
      .preview()
      .then(setPreview)
      // A failed preview must not take the page down with it. The list and the
      // delete buttons are what this page is for; the panel is commentary.
      .catch(() => setPreview(null))
  }, [])

  useEffect(() => {
    let cancelled = false
    api.memory
      .list()
      .then((value) => {
        if (!cancelled) setFacts(value)
      })
      .catch((error: Error) => {
        if (!cancelled) setMessage(error.message)
      })
    refreshPreview()
    return () => {
      cancelled = true
    }
  }, [refreshPreview])

  async function add(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = text.trim()
    if (trimmed.length < 3 || saving) return
    setSaving(true)
    try {
      const fact = await api.memory.add({ text: trimmed, category })
      // The server dedupes: restating something already known returns the
      // existing row rather than a second one, so replace by id.
      setFacts((previous) => [fact, ...(previous ?? []).filter((item) => item.id !== fact.id)])
      setText("")
      setMessage(null)
      refreshPreview()
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function forget(id: number) {
    try {
      await api.memory.remove(id)
      setFacts((previous) => previous?.filter((fact) => fact.id !== id) ?? null)
      refreshPreview()
    } catch (error) {
      setMessage((error as Error).message)
    }
  }

  async function forgetEverything() {
    try {
      await api.memory.clear()
      setFacts([])
      setConfirming(false)
      refreshPreview()
    } catch (error) {
      setMessage((error as Error).message)
    }
  }

  const count = facts?.length ?? 0

  // The title block is capped at a reading measure (~75 characters), which is
  // why a long description wraps into a ragged half-width column under the
  // heading. The fix is a shorter description rather than a wider measure: the
  // detail it used to carry is in the "How this works" card below, where it has
  // room to be laid out properly.
  return (
    <Page
      tone="data"
      title="What it remembers"
      eyebrow="Long-term memory"
      description="What you have told the app about your job search, kept and reused so you never have to say it twice."
      actions={
        count > 0 ? (
          // This used to delete everything on one click, with no undo and no
          // question asked - the most destructive control in the application
          // sitting in a corner behaving like a link. It asks now.
          confirming ? (
            <span className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">
                Delete all {count}? This cannot be undone.
              </span>
              <Button variant="destructive" size="sm" onClick={() => void forgetEverything()}>
                Yes, forget everything
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </span>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
              Forget everything
            </Button>
          )
        ) : null
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-5">
        <form onSubmit={(event) => void add(event)} className="flex flex-wrap gap-2">
          <Input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Tell it something outright – “I will not relocate”"
            aria-label="A fact to remember"
            maxLength={300}
            className="min-w-[16rem] flex-1"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as MemoryCategory)}
            aria-label="Category"
            className="h-9 rounded-md border bg-background px-3 text-sm"
          >
            {CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {CATEGORY_LABEL[value]}
              </option>
            ))}
          </select>
          <Button type="submit" disabled={text.trim().length < 3 || saving}>
            <Plus className="size-4" aria-hidden />
            Remember
          </Button>
        </form>

        {message ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {message}
          </p>
        ) : null}

        {facts === null ? (
          <div className="space-y-2">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : facts.length === 0 ? (
          <EmptyState
            icon={Brain}
            title="Nothing remembered yet"
            description="Durable facts are picked up from your own answers after a turn finishes, and you can add one here yourself."
          />
        ) : (
          <ul className="divide-y rounded-lg border">
            {facts.map((fact) => (
              <li key={fact.id} className="flex items-start gap-3 px-4 py-3">
                <Badge variant="secondary" className="mt-0.5 shrink-0">
                  {CATEGORY_LABEL[fact.category]}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{fact.text}</p>
                  <p className="font-mono text-[10px] text-muted-foreground">
                    {fact.origin === "stated"
                      ? "you said this outright"
                      : "picked up from a conversation"}{" "}
                    · last mentioned {formatRelative(fact.lastSeenAt)}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => void forget(fact.id)}
                  aria-label={`Forget: ${fact.text}`}
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}

        {/* Four facts about how the feature behaves, in a card rather than a
            column of grey prose. Two columns, so they use the width the page
            has instead of running down one side of it. */}
        <div className="rounded-2xl border bg-card/40 p-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
            How this works
          </p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Note
              icon={<Sparkles className="size-4" aria-hidden />}
              title="Where these come from"
              body="After an answer finishes – never before, so it costs you no waiting – the app reads the turn and keeps at most three things you said about yourself. Never what it said, never what a document said. You can add one by hand above."
            />
            <Note
              icon={<GaugeIcon className="size-4" aria-hidden />}
              title="How many are kept"
              body="Thirty in total, six per category, the oldest dropped first. At most eight reach any single answer – the store is a record, the prompt is a budget."
            />
            <Note
              icon={<ShieldCheck className="size-4" aria-hidden />}
              title="What is left out"
              body="Your skills and experience, because those are already in your CVs. And anything that looks like an email address, a phone number or a street is masked before it is written down."
            />
            <Note
              icon={<MapPin className="size-4" aria-hidden />}
              title="Where they apply"
              body="Chat, the Jobs tab, interview practice and document drafting – everything that runs through the agent. The fit score itself reads them too, but only to flag a clash; it never moves the number."
            />
          </div>
        </div>
        </div>

        <aside>
          <div className="xl:sticky xl:top-6">
            <PromptPanel preview={preview} />
          </div>
        </aside>
      </div>
    </Page>
  )
}

/**
 * What memory will actually contribute to the next answer.
 *
 * The rest of this page describes the feature; this shows it. The string below
 * is not assembled here - the server returns whatever `memory.recall.recall_block()`
 * returns, which is the same call the agent makes when it builds a system
 * prompt. A panel that rebuilt the text itself would drift from what is
 * really sent, and a preview that lies is worse than no preview: it would be a
 * page that proves the wrong thing convincingly.
 *
 * It is also the only place the caps stop being a claim. "At most eight reach
 * any one answer" is a sentence; a block with eight lines in it while the list
 * beside it shows twelve is the thing itself.
 */
function PromptPanel({ preview }: { preview: MemoryPreview | null }) {
  if (preview === null) {
    return <Skeleton className="h-64 w-full" />
  }

  const injected = preview.block.trim()
    ? preview.block.trim().split("\n").filter((line) => line.startsWith("- ")).length
    : 0

  return (
    <div className="space-y-3 rounded-2xl border bg-card/40 p-5">
      <div>
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
          <Eye className="size-3.5" aria-hidden />
          What the model will see
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          The exact text added to the next answer&rsquo;s instructions.
        </p>
      </div>

      {!preview.enabled ? (
        <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            Memory is switched off in <code className="font-mono">.env</code>. Facts are still
            stored and still shown here, but nothing below reaches an answer.
          </span>
        </p>
      ) : null}

      {preview.block.trim() ? (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {preview.block.trim()}
        </pre>
      ) : (
        <p className="rounded-lg border border-dashed bg-background/40 p-3 text-sm text-muted-foreground">
          Nothing is added. With no facts stored, the prompt is exactly what it was before this
          feature existed.
        </p>
      )}

      <dl className="space-y-1.5 text-sm">
        <Gauge
          term="Stored"
          value={preview.stored}
          limit={preview.maxStored}
          note={`${preview.maxPerCategory} per category`}
        />
        <Gauge
          term="Reaching one answer"
          value={injected}
          limit={preview.maxPerAnswer}
          note="the store is a record, the prompt is a budget"
        />
      </dl>

      {preview.leastRecentlyMentioned ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground">First to go</span> when its category fills:{" "}
          <span className="italic">&ldquo;{preview.leastRecentlyMentioned}&rdquo;</span> – the one
          that has gone longest without coming up.
        </p>
      ) : null}
    </div>
  )
}

/** One fact about how the feature behaves. Icon, heading, two or three lines. */
function Note({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border border-border/70 bg-background/50 text-primary">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </div>
  )
}

function Gauge({
  term,
  value,
  limit,
  note,
}: {
  term: string
  value: number
  limit: number
  note: string
}) {
  const filled = limit > 0 ? Math.min(1, value / limit) : 0
  return (
    <div className="space-y-1 border-b border-border/40 pb-2 last:border-0">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-muted-foreground">{term}</dt>
        <dd className="font-mono text-xs">
          {value} / {limit}
        </dd>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-border/60">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${Math.max(filled * 100, value > 0 ? 4 : 0)}%` }}
        />
      </div>
      <p className="text-[11px] text-muted-foreground">{note}</p>
    </div>
  )
}
