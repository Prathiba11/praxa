import { ArrowRight, FileCheck, Maximize2, MessageSquare, Sparkles, X } from "lucide-react"
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { buttonVariants } from "@/components/ui/button-variants"
import { cn } from "@/lib/utils"

/**
 * The front door.
 *
 * Every other screen in this application is a working surface - a conversation,
 * a funnel, a document under review. None of them say what the thing is, which
 * is fine for the person who built it and useless for anyone opening it for the
 * first time. This page answers that in one screen, then gets out of the way.
 *
 * The diagram is the part worth keeping honest: it draws the pipeline that
 * actually runs, not a marketing simplification of it. The re-query arrow is
 * there because retrieval really does loop; the review step is there because a
 * second agent really does read the draft. If the pipeline changes, this has to
 * change with it, which is the price of drawing something true.
 */

export function HomeRoute() {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative isolate flex h-dvh flex-col justify-center overflow-hidden">
      <ArtBackdrop />
      <section className="relative shrink-0 overflow-hidden">
        <HeroWatermark />

        <div className="relative mx-auto w-full max-w-5xl px-6 pb-6 pt-8 text-center xl:pt-12">
          <p className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card/60 px-3 py-1 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground backdrop-blur-sm">
            <Sparkles className="size-3 text-primary" aria-hidden />
            Career copilot
          </p>

          <h1 className="mt-5 font-display text-6xl font-extrabold tracking-[-0.055em] sm:text-7xl xl:text-8xl">
            <span className="bg-gradient-to-br from-foreground via-foreground to-foreground/55 bg-clip-text text-transparent">
              PRAXA
            </span>
          </h1>

          <p className="mx-auto mt-4 max-w-2xl text-lg leading-snug sm:text-2xl">
            Your platform to{" "}
            <span className="bg-gradient-to-r from-primary via-accent to-success bg-clip-text font-semibold text-transparent">
              apply and prepare
            </span>{" "}
            for your next career, easily.
          </p>

          <p className="mx-auto mt-3 hidden max-w-xl text-sm leading-relaxed text-muted-foreground sm:block">
            It reads your real CVs, searches what it actually has, tells you when the evidence is
            thin, and never saves a document until you have read it.
          </p>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Link to="/documents" className={cn(buttonVariants({ size: "lg" }))}>
              <FileCheck aria-hidden />
              Create an application
              <ArrowRight aria-hidden />
            </Link>
            <Link
              to="/chat"
              className={cn(buttonVariants({ size: "lg", variant: "outline" }))}
            >
              <MessageSquare aria-hidden />
              Ask about your CV
            </Link>
          </div>
        </div>
      </section>

      <section className="relative mx-auto w-full max-w-5xl shrink-0 px-6 pb-8">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-haspopup="dialog"
          aria-label="Open the pipeline diagram"
          className="group w-full rounded-2xl border border-border/70 bg-card/40 p-5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-border hover:bg-card/70 hover:shadow-xl hover:shadow-black/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
                How it works
              </p>
              <p className="mt-1 text-balance text-lg font-medium">
                One step, end to end – see the working structure
              </p>
            </div>
            <span
              aria-hidden
              className="grid size-9 shrink-0 place-items-center rounded-lg border border-border/70 text-muted-foreground transition-all duration-200 group-hover:border-primary/50 group-hover:bg-primary/10 group-hover:text-primary"
            >
              <Maximize2 className="size-4" />
            </span>
          </div>

          <div className="mt-4 overflow-hidden rounded-xl border border-border/60 bg-background/40 p-3">
            <PipelineDiagram compact />
          </div>
        </button>

        <div className="mt-4 hidden gap-3 sm:grid sm:grid-cols-3">
          <Feature
            title="Searches, then judges"
            body="Retrieval is a loop. It grades its own evidence and searches again when it comes back thin."
          />
          <Feature
            title="Two agents, one decision"
            body="A writer drafts; a second agent checks every claim against your CV. Neither of them decides."
          />
          <Feature
            title="Nothing saved silently"
            body="A document reaches your disk only when you press approve. Discard leaves no trace."
          />
        </div>
      </section>

      {open ? <DiagramDialog onClose={() => setOpen(false)} /> : null}
    </div>
  )
}


/**
 * The watermark behind the wordmark.
 *
 * Concentric arcs opening outward, a scatter of nodes, and three sheets - a
 * career widening rather than a decorative swirl. Drawn rather than
 * photographed, like everything else here: the project ships no images and
 * holds no licence for any, and a page leaning on stock art it does not own
 * would be a liability rather than a design.
 *
 * Kept under 10% opacity on purpose. A watermark that competes with the
 * headline is not a watermark, it is a background image with ambitions.
 */
/**
 * The only two generated images in the project, and why they are used this way.
 *
 * `scripts/generate_art.py` produced both through the OpenRouter key this
 * application already uses. Neither is dropped in as a picture:
 *
 * **The contour field** is not an image element at all - it is a mask. The
 * generated PNG was violet lines on a near-black field, which would have looked
 * correct in dark mode and like a black rectangle in light mode. It was
 * converted to white-on-transparent and is used as a CSS mask over a `primary`
 * fill, so the lines take whatever the theme's primary colour currently is and
 * the background behind them stays the page background. One asset, both themes,
 * and it follows the accent colour if that ever changes again.
 *
 * **The aurora** cannot be treated that way - its colour *is* the content - so
 * it is shown in dark mode only, where a luminous wash reads as depth. In light
 * mode it would be a dark smear across a white page, and `dark:` is a cheaper
 * answer than pretending otherwise.
 *
 * Both are deliberately faint. A landing page whose background competes with
 * its headline has a background image with ambitions, not a watermark. They
 * also replaced the dot grid rather than joining it: three decorative layers
 * behind one word is two too many.
 */
function ArtBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div
        className="absolute inset-0 bg-primary opacity-[0.10] dark:opacity-[0.16]"
        style={{
          maskImage: "url(/art/topo-mask.webp)",
          WebkitMaskImage: "url(/art/topo-mask.webp)",
          maskSize: "1100px",
          WebkitMaskSize: "1100px",
          maskPosition: "center",
          WebkitMaskPosition: "center",
        }}
      />
      {/* A second mask over the first, clearing the middle so the contours
          never run behind the wordmark - the headline has to win. */}
      <div
        className="absolute inset-0 bg-background"
        style={{
          maskImage: "radial-gradient(ellipse 42% 46% at 50% 44%, black 35%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 42% 46% at 50% 44%, black 35%, transparent 75%)",
        }}
      />
      <img
        src="/art/hero-bloom.webp"
        alt=""
        loading="lazy"
        decoding="async"
        className="absolute inset-x-0 top-0 hidden h-[62%] w-full object-cover opacity-30 blur-[2px] dark:block"
        style={{
          maskImage: "radial-gradient(ellipse 70% 100% at 50% 0%, black 10%, transparent 72%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 100% at 50% 0%, black 10%, transparent 72%)",
        }}
      />
    </div>
  )
}

function HeroWatermark() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 900 460"
      preserveAspectRatio="xMidYMid slice"
      className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.09] dark:opacity-[0.13]"
    >
      <defs>
        <linearGradient id="praxa-wm-a" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(var(--accent))" />
        </linearGradient>
        <linearGradient id="praxa-wm-b" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--success))" />
          <stop offset="100%" stopColor="hsl(var(--primary))" />
        </linearGradient>
        <radialGradient id="praxa-wm-fade" cx="50%" cy="42%" r="62%">
          <stop offset="0%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </radialGradient>
        <mask id="praxa-wm-mask">
          <rect width="900" height="460" fill="url(#praxa-wm-fade)" />
        </mask>
      </defs>

      <g mask="url(#praxa-wm-mask)" fill="none" strokeLinecap="round">
        {/* arcs opening to the right - a path widening, not a target */}
        <g stroke="url(#praxa-wm-a)" opacity="0.5">
          <path d="M120 430 A 330 330 0 0 1 450 100" strokeWidth="1.5" />
          <path d="M120 430 A 250 250 0 0 1 370 180" strokeWidth="1.5" opacity="0.75" />
          <path d="M120 430 A 170 170 0 0 1 290 260" strokeWidth="1.5" opacity="0.5" />
        </g>
        <g stroke="url(#praxa-wm-b)" opacity="0.5">
          <path d="M780 40 A 330 330 0 0 0 450 370" strokeWidth="1.5" />
          <path d="M780 40 A 250 250 0 0 0 530 290" strokeWidth="1.5" opacity="0.75" />
        </g>

        {/* three sheets, echoing the mark used in the page headers */}
        <g stroke="url(#praxa-wm-a)" strokeWidth="1.5" opacity="0.55">
          <rect x="648" y="252" width="92" height="120" rx="10" opacity="0.45" />
          <rect x="668" y="242" width="92" height="120" rx="10" opacity="0.7" />
          <rect x="688" y="232" width="92" height="120" rx="10" />
          <line x1="706" y1="264" x2="762" y2="264" />
          <line x1="706" y1="284" x2="748" y2="284" opacity="0.7" />
        </g>

        {/* scattered nodes, the small connected-graph texture */}
        <g fill="hsl(var(--primary))" opacity="0.55">
          <circle cx="212" cy="132" r="3" />
          <circle cx="322" cy="86" r="2.5" />
          <circle cx="158" cy="252" r="2.5" />
          <circle cx="596" cy="126" r="3" />
          <circle cx="742" cy="176" r="2.5" />
          <circle cx="470" cy="398" r="2.5" />
        </g>
        <g stroke="hsl(var(--primary))" strokeWidth="1" opacity="0.28">
          <line x1="212" y1="132" x2="322" y2="86" />
          <line x1="212" y1="132" x2="158" y2="252" />
          <line x1="596" y1="126" x2="742" y2="176" />
        </g>
      </g>
    </svg>
  )
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-card/40 p-4">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</p>
    </div>
  )
}

function DiagramDialog({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    // A dialog that leaves the page behind it scrollable is a dialog you lose.
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      window.removeEventListener("keydown", onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close the diagram"
        onClick={onClose}
        className="absolute inset-0 animate-fade-in bg-background/80 backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pipeline-title"
        className="relative z-10 max-h-[90dvh] w-full max-w-4xl animate-fade-in overflow-y-auto rounded-2xl border bg-card p-6 shadow-2xl sm:p-8"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="pipeline-title" className="text-xl font-semibold tracking-tight">
              What happens when you ask
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              The pipeline as it really runs – including the step where it goes back.
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </Button>
        </div>

        <div className="mt-6 rounded-xl border bg-background/50 p-4 sm:p-6">
          <PipelineDiagram />
        </div>

        <dl className="mt-6 space-y-3 text-sm">
          <Step
            term="Retrieve"
            detail="Dense vectors and keyword search together, fused, then reranked by a cross-encoder."
          />
          <Step
            term="Grade"
            detail="A second model reads what came back and returns sufficient, weak or none – with a reason."
          />
          <Step
            term="Search again"
            detail="On weak or none it rewrites the query and goes back out, once. That loop is the whole point."
          />
          <Step
            term="Draft"
            detail="A writing agent reorders and re-words what your CV already says. It adds no facts."
          />
          <Step
            term="Review"
            detail="A separate agent checks every claim against the source CV. It cannot rewrite anything."
          />
          <Step term="You decide" detail="Approve writes the files. Discard leaves nothing behind." />
        </dl>
      </div>
    </div>
  )
}

function Step({ term, detail }: { term: string; detail: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 font-medium">{term}</dt>
      <dd className="text-muted-foreground">{detail}</dd>
    </div>
  )
}

/**
 * The pipeline, drawn. Two rows: the retrieval loop on top, the document path
 * below it, joined by the fact that both end at a person.
 */
function PipelineDiagram({ compact }: { compact?: boolean }) {
  // Both modes use the same type size; only the box the drawing is allowed to
  // fill changes. The compact card used to cap at 132px, which scaled an 11px
  // label down to about 6px on screen - visible, not readable. At 190px a 13px
  // label lands near 9.5px and the longest node text ("Answer, with sources")
  // still clears its box. 14 does not: it touches the edges.
  const label = 13
  return (
    <svg
      viewBox="0 0 860 260"
      className={cn("h-auto w-full", compact && "max-h-[190px]")}
      role="img"
      aria-label="Your question is retrieved, graded, and re-queried when the evidence is thin; your CV and a job posting are drafted, reviewed by a second agent, and saved only when you approve."
    >
      <defs>
        <linearGradient id="praxa-pipe" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(var(--accent))" />
        </linearGradient>
        <marker id="praxa-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="hsl(var(--muted-foreground))" />
        </marker>
        <marker id="praxa-arrow-warn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="hsl(var(--warning))" />
        </marker>
      </defs>

      {/* row one: the retrieval loop */}
      <Node x={10} y={20} w={150} label="Your question" tone="muted" size={label} />
      <Edge from={160} to={210} y={44} />
      <Node x={210} y={20} w={150} label="Retrieve + rerank" size={label} />
      <Edge from={360} to={410} y={44} />
      <Node x={410} y={20} w={150} label="Grade the evidence" size={label} />
      <Edge from={560} to={610} y={44} />
      <Node x={610} y={20} w={150} label="Answer, with sources" tone="muted" size={label} />

      {/* the loop back, in the warning colour because it is the unhappy path */}
      <path
        d="M485 68 L485 104 L285 104 L285 68"
        fill="none"
        stroke="hsl(var(--warning))"
        strokeWidth="1.5"
        strokeDasharray="5 4"
        markerEnd="url(#praxa-arrow-warn)"
      />
      <text
        x={385}
        y={122}
        textAnchor="middle"
        fontSize={label}
        fill="hsl(var(--warning))"
        fontFamily="ui-monospace, monospace"
      >
        weak → search again
      </text>

      {/* row two: the document path */}
      <Node x={10} y={166} w={150} label="Your CV + a job" tone="muted" size={label} />
      <Edge from={160} to={210} y={190} />
      <Node x={210} y={166} w={150} label="Writing agent" size={label} />
      <Edge from={360} to={410} y={190} />
      <Node x={410} y={166} w={150} label="Reviewing agent" size={label} />
      <Edge from={560} to={610} y={190} />
      <Node x={610} y={166} w={150} label="You approve" tone="accent" size={label} />

      <text
        x={685}
        y={232}
        textAnchor="middle"
        fontSize={label}
        fill="hsl(var(--muted-foreground))"
        fontFamily="ui-monospace, monospace"
      >
        only then is anything saved
      </text>
    </svg>
  )
}

function Node({
  x,
  y,
  w,
  label,
  tone,
  size,
}: {
  x: number
  y: number
  w: number
  label: string
  tone?: "muted" | "accent"
  size: number
}) {
  const stroke =
    tone === "accent"
      ? "hsl(var(--success))"
      : tone === "muted"
        ? "hsl(var(--muted-foreground))"
        : "url(#praxa-pipe)"
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={48}
        rx={10}
        fill="hsl(var(--card))"
        stroke={stroke}
        strokeWidth={tone === "muted" ? 1.75 : 2}
      />
      <text
        x={x + w / 2}
        y={y + 29}
        textAnchor="middle"
        fontSize={size}
        fill="hsl(var(--foreground))"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
      >
        {label}
      </text>
    </g>
  )
}

function Edge({ from, to, y }: { from: number; to: number; y: number }) {
  return (
    <line
      x1={from}
      y1={y}
      x2={to}
      y2={y}
      stroke="hsl(var(--muted-foreground))"
      strokeWidth="1.5"
      markerEnd="url(#praxa-arrow)"
    />
  )
}
