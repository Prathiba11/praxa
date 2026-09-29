import { AlertTriangle, Check, Cpu, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"

import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { AppSettings, ModelOption, SettingsUpdate } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * The developer half of the application, kept away from the working half.
 *
 * Somebody using a career assistant does not necessarily know what a
 * temperature is, and a model picker in the chat header is one mis-click away
 * from changing the thing answering you mid-conversation. So it lives on its
 * own page, reached deliberately.
 *
 * The list is closed rather than a text box, and that is a scar. An earlier
 * version accepted any model id; one that the account could not reach was set,
 * every grading call returned 404, and because grading fails open the
 * application kept answering while retrieval grading was quietly dead for days.
 * A free-text field here would be that bug with better styling.
 */

export function SettingsRoute() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void api.settings
      .read()
      .then((value) => !cancelled && setSettings(value))
      .catch((error: Error) => !cancelled && setMessage(error.message))
    return () => {
      cancelled = true
    }
  }, [])

  /**
   * One writer for every change on this page.
   *
   * `busy` is keyed by what is being changed rather than being a bare boolean,
   * so choosing a model does not grey out the temperature slider and vice
   * versa – and two changes cannot race.
   */
  async function apply(key: string, patch: SettingsUpdate) {
    if (busy) return
    setBusy(key)
    setMessage(null)
    try {
      const updated = await api.settings.update(patch)
      setSettings(updated)
      setMessage("Saved for this session. It reverts to .env when the server restarts.")
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function choose(id: string) {
    void apply(id, { chatModel: id })
  }

  return (
    <Page
      tone="developer"
      plain
      eyebrow="Developer settings"
      title="Model configuration"
      description="Which model answers, and what it costs. Separate from the rest of the app on purpose."
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-4">
        {message ? (
          <p className="rounded-lg border bg-card/50 px-4 py-3 text-sm text-muted-foreground">
            {message}
          </p>
        ) : null}

        {settings === null ? (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <>
            {settings.customModel ? (
              <p className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                <span>
                  <span className="font-medium">
                    <code className="font-mono">{settings.chatModel}</code> was set by hand
                  </span>{" "}
                  in <code className="font-mono">.env</code> and is not one of the options below.
                  Choosing one here replaces it for this session.
                </span>
              </p>
            ) : null}

            <section className="space-y-3">
              <h2 className="text-sm font-medium text-muted-foreground">
                Model that writes the answers
              </h2>
              <div className="space-y-2">
                {settings.models.map((model) => (
                  <ModelRow
                    key={model.id}
                    model={model}
                    selected={model.id === settings.chatModel}
                    busy={busy === model.id}
                    onChoose={() => choose(model.id)}
                  />
                ))}
              </div>
            </section>

            <section className="space-y-4 rounded-xl border bg-card/40 px-4 py-3">
              <h2 className="text-sm font-medium">How the answer is written</h2>

              <NumberField
                label="Temperature"
                hint="0 is repeatable, 2 is erratic. A CV generator wants the low end."
                value={settings.temperature}
                min={0}
                max={2}
                step={0.1}
                format={(value) => value.toFixed(2)}
                busy={busy === "temperature"}
                onCommit={(value) => void apply("temperature", { temperature: value })}
              />

              <NumberField
                label="Max tokens per answer"
                hint="The ceiling on one answer. Too low truncates a tailored CV mid-sentence; too high lets one turn eat the session budget."
                value={settings.maxTokens}
                min={256}
                max={8000}
                step={100}
                format={(value) => Math.round(value).toLocaleString()}
                busy={busy === "maxTokens"}
                onCommit={(value) => void apply("maxTokens", { maxTokens: Math.round(value) })}
              />

              <dl className="space-y-1.5 text-sm">
                <Row term="Monthly ceiling" value={`$${settings.monthlyBudgetUsd.toFixed(2)}`} />
              </dl>
              <p className="text-xs leading-relaxed text-muted-foreground">
                These change the running server until it restarts – nothing on this page edits a
                file. The monthly ceiling is deliberately not editable here: a budget you can raise
                from inside the application it is meant to restrain is not a budget.
              </p>
            </section>

            {/* Kept in this column rather than beside the prices it talks
                about. The right-hand panel is already the taller of the two, so
                anything added there is what pushes the page past one screen;
                this column ends here and has the room. */}
            <p className="text-xs leading-relaxed text-muted-foreground">
              Prices are estimates for comparison; the usage meter reports what OpenRouter actually
              charged. Before relying on a model you have not used, run{" "}
              <code className="font-mono">python scripts/check_models.py</code> – it sends one
              token to each and says which answered.
            </p>
          </>
        )}
        </div>

        <aside>
          {settings ? (
            <div className="xl:sticky xl:top-6">
              <ModelDetail settings={settings} />
            </div>
          ) : (
            <Skeleton className="h-[460px] w-full" />
          )}
        </aside>
      </div>
    </Page>
  )
}

/**
 * What the chosen model actually reaches.
 *
 * The space was empty, and the honest thing to put in it is the one fact a
 * person cannot get from a price list: this setting does not change every model
 * call in the application. Two operations - grading retrieved evidence, and
 * extracting durable facts after a turn - run on `CC_GRADER_MODEL` instead,
 * because judging relevance is a classification job and paying writing rates
 * for a three-way verdict on every turn would be waste repeated forever.
 *
 * Every operation named here is a real `operation=` value passed to
 * `core.llm.chat`, so this panel is a map of the code rather than an
 * illustration of it. If an operation moves between models, this has to move
 * with it.
 */
function ModelDetail({ settings }: { settings: AppSettings }) {
  const chosen = settings.models.find((model) => model.id === settings.chatModel)
  const grader = settings.models.find((model) => model.id === settings.graderModel)

  const writes = [
    "Answering a question",
    "Query analysis and translation",
    "Writing a tailored CV",
    "Writing a cover letter",
    "Reviewing a draft",
    "Scoring a job against a CV",
    "Interview questions and scoring",
  ]

  return (
    <div className="space-y-3 rounded-2xl border bg-card/40 p-5">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
          What this model runs
        </p>
        <p className="mt-1 text-lg font-medium">{chosen?.label ?? settings.chatModel}</p>
      </div>

      <ReachDiagram label={chosen?.label ?? "Selected model"} />

      {chosen ? (
        <>
          <ul className="space-y-1.5 text-sm">
            {chosen.strengths.map((item) => (
              <li key={item} className="flex items-start gap-2 text-muted-foreground">
                <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                {item}
              </li>
            ))}
          </ul>

          <p className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm leading-relaxed text-muted-foreground">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
            {chosen.caution}
          </p>
        </>
      ) : null}

      <details className="group rounded-lg border border-border/60 bg-background/30">
        <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium transition-colors hover:text-primary">
          The {writes.length} steps it runs
        </summary>
        <ul className="space-y-1 border-t px-3 py-2 text-sm text-muted-foreground">
          {writes.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>

      <div className="space-y-1 rounded-xl border border-border/60 bg-background/40 p-3">
        <p className="text-sm font-medium">Two steps do not use it</p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Grading evidence and extracting memory run on{" "}
          <span className="font-mono text-xs">{grader?.label ?? settings.graderModel}</span> –
          judging relevance is classification, not writing.
        </p>
      </div>

      {chosen ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          At ${chosen.inputPerMtok.toFixed(2)} in and ${chosen.outputPerMtok.toFixed(2)} out per
          million tokens, a turn of roughly 4,000 in and 500 out costs about{" "}
          <span className="font-mono">
            ${((4000 * chosen.inputPerMtok + 500 * chosen.outputPerMtok) / 1_000_000).toFixed(4)}
          </span>
          . That is arithmetic on a typical turn, not a measurement – the usage meter reports what
          OpenRouter actually charged.
        </p>
      ) : null}
    </div>
  )
}

/** The model in the middle, the parts of the app that call it around it. */
function ReachDiagram({ label }: { label: string }) {
  // A 60-wide node at x=282 ends at 342 in a 320-wide viewBox, so "Review" was
  // drawn off the right edge and clipped. Every x below is held between 8 and
  // 252 (= 320 - 60 - 8) and the rows are mirrored about the centre at 160.
  const spokes = [
    { x: 46, y: 22, text: "Chat" },
    { x: 214, y: 22, text: "Documents" },
    { x: 8, y: 96, text: "Retrieval" },
    { x: 252, y: 96, text: "Review" },
    { x: 130, y: 170, text: "Interview" },
  ]

  return (
    <svg viewBox="0 0 320 200" className="h-auto w-full" role="img" aria-label={`${label} is called by chat, documents, retrieval, review and interview practice.`}>
      <defs>
        <linearGradient id="praxa-reach" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(var(--accent))" />
        </linearGradient>
      </defs>

      {spokes.map((spoke) => (
        <line
          key={spoke.text}
          x1={160}
          y1={100}
          x2={spoke.x + 30}
          y2={spoke.y + 12}
          stroke="hsl(var(--border))"
          strokeWidth="1"
        />
      ))}

      {spokes.map((spoke) => (
        <g key={`${spoke.text}-node`}>
          <rect
            x={spoke.x}
            y={spoke.y}
            width={60}
            height={24}
            rx={7}
            fill="hsl(var(--card))"
            stroke="hsl(var(--border))"
          />
          <text
            x={spoke.x + 30}
            y={spoke.y + 16}
            textAnchor="middle"
            fontSize="10"
            fill="hsl(var(--muted-foreground))"
            fontFamily="ui-sans-serif, system-ui, sans-serif"
          >
            {spoke.text}
          </text>
        </g>
      ))}

      <circle cx={160} cy={100} r={34} fill="hsl(var(--card))" stroke="url(#praxa-reach)" strokeWidth="1.5" />
      <text
        x={160}
        y={97}
        textAnchor="middle"
        fontSize="10"
        fill="hsl(var(--foreground))"
        fontFamily="ui-monospace, monospace"
      >
        model
      </text>
      <text
        x={160}
        y={110}
        textAnchor="middle"
        fontSize="9"
        fill="hsl(var(--muted-foreground))"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
      >
        in use
      </text>
    </svg>
  )
}

function ModelRow({
  model,
  selected,
  busy,
  onChoose,
}: {
  model: ModelOption
  selected: boolean
  busy: boolean
  onChoose: () => void
}) {
  return (
    <button
      type="button"
      onClick={onChoose}
      aria-pressed={selected}
      disabled={busy}
      className={cn(
        "flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left transition-all duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary/50 bg-primary/5 shadow-sm"
          : "border-border/70 bg-card/40 hover:-translate-y-0.5 hover:border-border hover:bg-card/70",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border",
          selected ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground",
        )}
      >
        {busy ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : selected ? (
          <Check className="size-4" aria-hidden />
        ) : (
          <Cpu className="size-4" aria-hidden />
        )}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{model.label}</span>
          <Badge variant="outline">{model.provider}</Badge>
          {selected ? <Badge>In use</Badge> : null}
        </span>
        <span className="mt-0.5 block font-mono text-xs text-muted-foreground">{model.id}</span>
        <span className="mt-1 block text-sm text-muted-foreground">{model.note}</span>
      </span>

      <span className="shrink-0 text-right text-xs text-muted-foreground">
        <span className="block">${model.inputPerMtok.toFixed(2)} in</span>
        <span className="block">${model.outputPerMtok.toFixed(2)} out</span>
        <span className="mt-0.5 block opacity-70">per M tokens</span>
      </span>
    </button>
  )
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/40 pb-1.5">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="truncate font-mono text-xs">{value}</dd>
    </div>
  )
}

/**
 * A slider and a number, committing on release rather than on every pixel.
 *
 * Each commit is a request that clears the settings cache server-side, so a
 * slider that saved while it was being dragged would fire dozens of them for
 * one decision.
 */
function NumberField({
  label,
  hint,
  value,
  min,
  max,
  step,
  format,
  busy,
  onCommit,
}: {
  label: string
  hint: string
  value: number
  min: number
  max: number
  step: number
  format: (value: number) => string
  busy: boolean
  onCommit: (value: number) => void
}) {
  const [local, setLocal] = useState(value)

  // The server is the source of truth: a rejected or adjusted value has to win
  // over whatever the slider is showing.
  useEffect(() => setLocal(value), [value])

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`field-${label}`} className="text-sm text-muted-foreground">
          {label}
        </label>
        <span className="font-mono text-xs">
          {format(local)}
          {busy ? <Loader2 className="ml-1.5 inline h-3 w-3 animate-spin" aria-hidden /> : null}
        </span>
      </div>
      <input
        id={`field-${label}`}
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        disabled={busy}
        onChange={(event) => setLocal(Number(event.target.value))}
        onPointerUp={() => local !== value && onCommit(local)}
        onKeyUp={() => local !== value && onCommit(local)}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-border accent-primary disabled:opacity-50"
      />
      <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
    </div>
  )
}
