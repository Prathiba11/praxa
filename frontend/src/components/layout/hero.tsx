import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * The visual weight this application was missing.
 *
 * Everything here is drawn rather than photographed: layered radial gradients,
 * a dot grid, and one abstract SVG. That is a constraint, not a shortcut - the
 * project ships no images and has no licence for any, and a page built on stock
 * photography it does not own would be a liability rather than a design.
 *
 * What it buys: the top of the page stops being a heading on a flat background
 * and becomes a surface. Everything below it then reads as content sitting on
 * something, which is most of what separates a product from a form.
 *
 * All of it is `aria-hidden` and none of it carries meaning. A screen reader
 * hears the heading and the description, which is the whole of the message.
 */

/** Layered radial washes, fixed behind the whole application. */
export function AmbientBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        className="absolute -left-32 -top-32 size-[38rem] rounded-full opacity-[0.28] blur-[100px]"
        style={{ background: "radial-gradient(circle, hsl(var(--primary)) 0%, transparent 70%)" }}
      />
      <div
        className="absolute -right-24 top-16 size-[34rem] rounded-full opacity-[0.22] blur-[100px]"
        style={{ background: "radial-gradient(circle, hsl(var(--accent)) 0%, transparent 70%)" }}
      />
      <div
        className="absolute bottom-[-6rem] left-1/3 size-[32rem] rounded-full opacity-[0.16] blur-[100px]"
        style={{ background: "radial-gradient(circle, hsl(var(--success)) 0%, transparent 70%)" }}
      />
    </div>
  )
}

/**
 * A banded header with a dot grid, a gradient wash and an abstract mark.
 *
 * `eyebrow` is the small line above the title; `children` is anything that
 * should sit inside the band rather than under it, such as an action row.
 */
export function PageHero({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}: {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <section
      className={cn(
        "relative overflow-hidden border-b bg-gradient-to-b from-card/60 via-card/20 to-transparent",
        className,
      )}
    >
      {/* Dot grid. A repeating radial gradient, so it costs no request and
          scales with the device rather than pixelating. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, hsl(var(--border)) 1px, transparent 0)",
          backgroundSize: "22px 22px",
          maskImage: "linear-gradient(to bottom, black, transparent 85%)",
          WebkitMaskImage: "linear-gradient(to bottom, black, transparent 85%)",
        }}
      />

      <FlowMark />

      <div className="relative px-5 py-10 lg:px-8 lg:py-12">
        <div className="mx-auto w-full max-w-6xl">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0 max-w-2xl space-y-3">
              {eyebrow ? (
                <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-primary">
                  {eyebrow}
                </p>
              ) : null}
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
              {description ? (
                <p className="text-base leading-relaxed text-muted-foreground">{description}</p>
              ) : null}
            </div>
            {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
          </div>
          {children ? <div className="mt-8">{children}</div> : null}
        </div>
      </div>
    </section>
  )
}

/**
 * The abstract mark in the corner of the hero.
 *
 * Three stacked sheets and a check - a document passing through a review and
 * coming out accepted, which is what this application does. Deliberately
 * geometric: an illustration of a person or a workplace would be a stock photo
 * drawn by hand, with the same problem of describing something that is not here.
 */
function FlowMark() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 220 180"
      className="pointer-events-none absolute -right-6 -top-4 hidden h-[190px] w-[230px] opacity-[0.16] lg:block"
    >
      <defs>
        <linearGradient id="praxa-flow" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(var(--accent))" />
        </linearGradient>
      </defs>
      <g stroke="url(#praxa-flow)" strokeWidth="2" fill="none">
        <rect x="24" y="26" width="92" height="118" rx="10" opacity="0.45" />
        <rect x="44" y="18" width="92" height="118" rx="10" opacity="0.7" />
        <rect x="64" y="10" width="92" height="118" rx="10" />
        <line x1="80" y1="40" x2="140" y2="40" strokeLinecap="round" />
        <line x1="80" y1="58" x2="126" y2="58" strokeLinecap="round" opacity="0.7" />
        <line x1="80" y1="76" x2="136" y2="76" strokeLinecap="round" opacity="0.5" />
        <circle cx="168" cy="118" r="26" />
        <path d="M156 118l9 9 18-19" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  )
}
