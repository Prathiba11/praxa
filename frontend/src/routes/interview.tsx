import { ArrowRight, CheckCircle2, Loader2, Mic, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"

import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type {
  AnswerResult,
  Difficulty,
  InterviewOptions,
  InterviewQuestion,
  InterviewSession,
  Profile,
  RubricScore,
} from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * Interview practice as a session, not a conversation.
 *
 * Practice already worked in the chat box - ask for a question in interview
 * mode and one arrives. What chat cannot do is hold a session: each message
 * there is independent, so nothing knows a question is outstanding and that the
 * next thing typed is the answer to it. Asking twice produced two questions
 * rather than a question and a critique.
 *
 * The state that fixes this is NOT held here. It lives in the database, and the
 * session id lives in the URL, so a refresh, a closed tab or a second window all
 * land on the same rows. What this component holds is the one thing that was
 * never stored: the question currently on screen, unanswered.
 */

const PROFILE_LABEL: Record<Profile, string> = {
  automotive_cyber: "Automotive cyber",
  devops: "DevOps",
  ai_eng: "AI engineering",
  general: "General",
}

/** The three tracks you can be interviewed for. General is a CV shelf, not a role. */
const TRACKS: Profile[] = ["automotive_cyber", "devops", "ai_eng"]

const DIFFICULTY_HINT: Record<Difficulty, string> = {
  warmup: "An opener. Forgiving, and a weak answer is less likely to be probed.",
  standard: "A normal question at this persona's usual bar.",
  hard: "A challenge. Expect to be pushed on anything vague.",
}

const DIMENSIONS: { key: keyof RubricScore; label: string; hint: string }[] = [
  { key: "structure", label: "Structure", hint: "Situation, task, action, result - in that order" },
  { key: "specificity", label: "Specificity", hint: "Names, numbers, tools; not generalities" },
  { key: "ownership", label: "Ownership", hint: "What you did, not what the team did" },
  { key: "impact", label: "Impact", hint: "What changed, measured where possible" },
  { key: "relevance", label: "Relevance", hint: "Actually answers the question asked" },
]

const MAX_SCORE = 5

/**
 * A persona portrait, or their initials when there is none.
 *
 * The files are generated once by `scripts/generate_personas.py` and served
 * from `public/personas/`. They are optional on purpose: a fresh clone has not
 * run that script, and a missing face must not leave a broken image icon on the
 * setup screen. `onError` swaps in initials, so the page is complete either way.
 *
 * Labelled an illustration in the alt text, because a generated face shown
 * without comment invites the reader to think there is a person behind it.
 * There is not, and the practice is no worse for it.
 */
function PersonaFace({ personaKey, name }: { personaKey: string; name: string }) {
  const [failed, setFailed] = useState(false)
  const initials = name
    .split(/\s+/)
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()

  if (failed) {
    return (
      <span
        aria-hidden
        className="grid size-12 shrink-0 place-items-center rounded-full border bg-primary/10 font-mono text-xs text-primary"
      >
        {initials}
      </span>
    )
  }

  return (
    <img
      src={`/personas/${personaKey}.webp`}
      alt={`Illustration of an invented ${name.toLowerCase()}`}
      onError={() => setFailed(true)}
      className="size-12 shrink-0 rounded-full border object-cover"
      loading="lazy"
    />
  )
}

/**
 * The two people at the desk: the interviewer on the left, you on the right.
 *
 * The figures are optional in exactly the way `PersonaFace` is - a clone that
 * has not run `scripts/generate_personas.py` shows initials instead, and the
 * page is complete either way. The candidate figure is a generic person, not a
 * likeness of anyone; replacing `public/personas/candidate.webp` with your own
 * photo is the supported way to make it you.
 */
function Seat({
  imageKey,
  label,
  caption,
  align,
}: {
  imageKey: string
  label: string
  caption: string
  align: "left" | "right"
}) {
  const [failed, setFailed] = useState(false)
  // Two letters where there are two words, and the first two otherwise: a lone
  // "Y" for "You" reads as an image that failed rather than a seat nobody has
  // put a face in yet.
  const words = label.split(/\s+/)
  const initials = (
    words.length > 1 ? words.map((word) => word[0]).join("") : label.slice(0, 2)
  )
    .slice(0, 2)
    .toUpperCase()

  return (
    <div
      className={cn(
        "flex w-24 shrink-0 flex-col items-center gap-2 sm:w-32",
        align === "right" && "order-last",
      )}
    >
      {failed ? (
        <span
          aria-hidden
          title="Run scripts/generate_personas.py to put a face here"
          className="grid size-20 place-items-center rounded-2xl border border-dashed bg-primary/5 font-mono text-sm text-primary/70 sm:size-28"
        >
          {initials}
        </span>
      ) : (
        <img
          src={`/personas/${imageKey}.webp`}
          alt={`Illustration of an invented ${label.toLowerCase()}`}
          onError={() => setFailed(true)}
          className={cn(
            "size-20 rounded-2xl border object-cover sm:size-28",
            // Mirrored so the two figures face each other across the question.
            align === "right" && "-scale-x-100",
          )}
          loading="lazy"
        />
      )}
      <span className="text-center text-xs font-medium leading-tight">{label}</span>
      <span className="text-center text-[11px] leading-tight text-muted-foreground">{caption}</span>
    </div>
  )
}

/* ------------------------------------------------------------------- setup */

function SetupStep({
  options,
  busy,
  onStart,
}: {
  options: InterviewOptions | null
  busy: boolean
  onStart: (profile: Profile, persona: string, difficulty: Difficulty, questions: number) => void
}) {
  const [profile, setProfile] = useState<Profile>("devops")
  const [persona, setPersona] = useState<string | null>(null)
  const [difficulty, setDifficulty] = useState<Difficulty>("standard")
  const [questions, setQuestions] = useState(5)

  // The defaults come from the server, so this page holds no copy of a list
  // that would silently disagree the day a persona is added.
  useEffect(() => {
    if (options && persona === null) {
      setPersona(options.defaultPersona)
      setQuestions(options.defaultQuestions)
    }
  }, [options, persona])

  if (!options) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Which track</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {TRACKS.map((track) => (
            <button
              key={track}
              type="button"
              onClick={() => setProfile(track)}
              className={cn(
                "rounded-xl border p-4 text-left transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                track === profile
                  ? "border-primary/50 bg-primary/5"
                  : "bg-card/40 hover:-translate-y-0.5 hover:bg-card/70",
              )}
            >
              <span className="block text-sm font-medium">{PROFILE_LABEL[track]}</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                Questions grounded in this CV
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">Who is interviewing you</h2>
        <div className="grid gap-3 md:grid-cols-3">
          {options.personas.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setPersona(entry.key)}
              className={cn(
                "flex h-full flex-col gap-2 rounded-xl border p-4 text-left transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                entry.key === persona
                  ? "border-primary/50 bg-primary/5"
                  : "bg-card/40 hover:-translate-y-0.5 hover:bg-card/70",
              )}
            >
              <span className="flex items-center gap-3">
                <PersonaFace personaKey={entry.key} name={entry.name} />
                <span className="text-sm font-medium">{entry.name}</span>
              </span>
              {/* Their opening line, not just their title. "Friendly recruiter"
                  means little until you read what they actually say. */}
              <span className="text-xs italic leading-relaxed text-muted-foreground">
                “{entry.opening}”
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="grid gap-6 sm:grid-cols-2">
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">How hard</h2>
          <div className="flex flex-wrap gap-2">
            {options.difficulties.map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => setDifficulty(level)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs transition-colors",
                  level === difficulty
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "text-muted-foreground hover:border-foreground hover:text-foreground",
                )}
              >
                {level}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{DIFFICULTY_HINT[difficulty]}</p>
        </div>

        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">How many questions</h2>
          <div className="flex flex-wrap gap-2">
            {[3, 5, 8].map((count) => (
              <button
                key={count}
                type="button"
                onClick={() => setQuestions(count)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs transition-colors",
                  count === questions
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "text-muted-foreground hover:border-foreground hover:text-foreground",
                )}
              >
                {count}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            A weak answer can earn one follow-up on the same question, which does not count
            against this.
          </p>
        </div>
      </section>

      <Button disabled={busy || !persona} onClick={() => persona && onStart(profile, persona, difficulty, questions)}>
        {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Mic aria-hidden />}
        {busy ? "Starting…" : "Start the interview"}
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ scoring */

function ScoreBar({ label, hint, value }: { label: string; hint: string; value: number }) {
  const percent = (value / MAX_SCORE) * 100
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {value.toFixed(1)} / {MAX_SCORE}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-border/60">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            value >= 3.5 ? "bg-success" : value >= 2.5 ? "bg-primary" : "bg-warning",
          )}
          style={{ width: `${Math.max(percent, 2)}%` }}
        />
      </div>
      <p className="text-[11px] text-muted-foreground">{hint}</p>
    </div>
  )
}

function ScorePanel({ score }: { score: RubricScore }) {
  return (
    <div className="space-y-4 rounded-lg border bg-background/40 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">
          {score.overall.toFixed(1)} / {MAX_SCORE} overall
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          five dimensions, equally weighted
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {DIMENSIONS.map((dimension) => (
          <ScoreBar
            key={dimension.key}
            label={dimension.label}
            hint={dimension.hint}
            value={Number(score[dimension.key])}
          />
        ))}
      </div>

      {score.feedback ? (
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            What was missing
          </p>
          <p className="text-sm leading-relaxed">{score.feedback}</p>
        </div>
      ) : null}

      {score.improvedAnswer ? (
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            The same answer, stronger
          </p>
          {/* Shown as a model to learn from, not as a script: it is built from
              the evidence you gave, so reading it back verbatim in a real
              interview would be claiming someone else's phrasing for your
              own work. */}
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
            {score.improvedAnswer}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------------ the run */

function Transcript({ session }: { session: InterviewSession }) {
  if (session.turns.length === 0) return null
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-muted-foreground">
        Answered so far ({session.turns.length})
      </h2>
      {session.turns.map((turn, index) => (
        <Card key={`${index}-${turn.question}`}>
          <CardHeader className="pb-2">
            <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
              {turn.isProbe ? <Badge variant="secondary">follow-up</Badge> : null}
              {turn.question}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{turn.answer}</p>
            <ScorePanel score={turn.score} />
          </CardContent>
        </Card>
      ))}
    </section>
  )
}

export function InterviewRoute() {
  const [search, setSearch] = useSearchParams()
  const sessionId = search.get("session")

  const [options, setOptions] = useState<InterviewOptions | null>(null)
  const [session, setSession] = useState<InterviewSession | null>(null)
  const [question, setQuestion] = useState<InterviewQuestion | null>(null)
  const [answer, setAnswer] = useState("")
  const [last, setLast] = useState<AnswerResult | null>(null)
  const [busy, setBusy] = useState<null | "starting" | "scoring" | "asking">(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.interview.options().then(setOptions).catch(() => setOptions(null))
  }, [])

  // The session id is in the URL, so this runs on a refresh too. The question
  // that was on screen unanswered is not recovered - it was never stored - so
  // a fresh one is requested. Nothing the candidate produced is lost.
  const resume = useCallback(async (id: string) => {
    setError(null)
    try {
      const restored = await api.interview.resume(id)
      setSession(restored)
      setQuestion(await api.interview.next(id))
    } catch (caught) {
      setError((caught as Error).message)
    }
  }, [])

  useEffect(() => {
    if (sessionId && !session) void resume(sessionId)
  }, [sessionId, session, resume])

  async function start(
    profile: Profile,
    persona: string,
    difficulty: Difficulty,
    questions: number,
  ) {
    setBusy("starting")
    setError(null)
    try {
      const started = await api.interview.start({ profile, persona, difficulty, questions })
      setSession(started)
      setQuestion(started.question)
      setSearch({ session: started.sessionId })
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function submit() {
    if (!session || !question || !answer.trim()) return
    setBusy("scoring")
    setError(null)
    try {
      const result = await api.interview.answer(session.sessionId, {
        question: question.text,
        answer: answer.trim(),
        isProbe: Boolean(question.focus),
      })
      setLast(result)
      setAnswer("")
      // The score is painted first. Whatever comes next is fetched behind it,
      // which is why these are two calls rather than one.
      setSession(await api.interview.resume(session.sessionId))

      if (result.move === "probe" && result.probe) {
        setQuestion(result.probe)
      } else if (result.move === "next") {
        setBusy("asking")
        setQuestion(await api.interview.next(session.sessionId))
      } else {
        setQuestion(null)
      }
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function restart() {
    setSession(null)
    setQuestion(null)
    setLast(null)
    setAnswer("")
    setSearch({})
  }

  const finished = session !== null && question === null && last?.move === "finish"

  return (
    <Page
      eyebrow="Practice"
      title="Interview"
      description="One question at a time, scored against what your CV actually evidences. The session is saved, so a refresh picks it up where you left it."
      tone="work"
      actions={
        session ? (
          <Button variant="outline" size="sm" onClick={restart}>
            <RotateCcw aria-hidden /> New session
          </Button>
        ) : undefined
      }
    >
      <div className="mx-auto w-full max-w-4xl space-y-8 px-5 py-8 lg:px-8">
        {error ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        {!session ? (
          <SetupStep options={options} busy={busy === "starting"} onStart={start} />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <PersonaFace personaKey={session.persona.key} name={session.persona.name} />
              <Badge variant="outline">{PROFILE_LABEL[session.profile]}</Badge>
              <Badge variant="outline">{session.persona.name}</Badge>
              <Badge variant="outline">{session.difficulty}</Badge>
              <span className="font-mono">
                {session.turns.length} of {session.plannedQuestions} answered
              </span>
            </div>

            {question ? (
              <div className="flex items-start gap-3 sm:gap-5">
                <Seat
                  imageKey={session.persona.key}
                  label={session.persona.name}
                  caption={`asking · ${session.difficulty}`}
                  align="left"
                />

                <Card className="min-w-0 flex-1">
                <CardHeader className="pb-3">
                  <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                    {question.focus ? <Badge variant="secondary">follow-up</Badge> : null}
                    {question.text}
                  </CardTitle>
                  {/* Where the question came from. A question grounded in your
                      own material and one invented from a profile name are not
                      the same thing, and the difference should not be invisible. */}
                  <p className="text-xs text-muted-foreground">{question.grounding}</p>
                </CardHeader>
                <CardContent className="space-y-3">
                  <textarea
                    value={answer}
                    onChange={(event) => setAnswer(event.target.value)}
                    rows={8}
                    placeholder="Situation, task, what you did, what changed…"
                    className="w-full resize-y rounded-xl border bg-card/40 px-4 py-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label="Your answer"
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <Button disabled={!answer.trim() || busy !== null} onClick={() => void submit()}>
                      {busy === "scoring" ? (
                        <Loader2 className="animate-spin" aria-hidden />
                      ) : (
                        <ArrowRight aria-hidden />
                      )}
                      {busy === "scoring" ? "Scoring…" : "Submit answer"}
                    </Button>
                    {busy === "asking" ? (
                      <span className="text-xs text-muted-foreground">
                        Writing the next question…
                      </span>
                    ) : null}
                  </div>
                </CardContent>
                </Card>

                <Seat
                  imageKey="candidate"
                  label="You"
                  caption="answering"
                  align="right"
                />
              </div>
            ) : null}

            {finished ? (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <CheckCircle2 className="size-4 text-success" aria-hidden />
                    Session finished
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {last?.summary ? (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{last.summary}</p>
                  ) : null}
                  <Button variant="outline" size="sm" onClick={restart}>
                    <RotateCcw aria-hidden /> Practise again
                  </Button>
                </CardContent>
              </Card>
            ) : null}

            <Transcript session={session} />
          </>
        )}
      </div>
    </Page>
  )
}
