import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * The header every page wears.
 *
 * This used to be a title, a paragraph and a bottom border on a flat
 * background, which is the difference between a tool and a product: nothing on
 * the screen sat on anything. It is now a band - a gradient wash, a dot grid
 * fading out downward, and an abstract mark in the corner - so content below it
 * reads as content on a surface.
 *
 * Everything decorative here is drawn, not photographed. The project ships no
 * images and holds no licence for any, and a layout that depended on stock
 * photography would be a liability rather than a design. All of it is
 * `aria-hidden`: a screen reader hears the title and the description, which is
 * the whole message.
 */

/**
 * Which group in the sidebar this page belongs to.
 *
 * The nav already sorts pages into three: the working surfaces, "Your data",
 * and the developer corner. That grouping was only visible in the sidebar, so
 * a page opened from a link looked like every other page and gave no clue
 * which half of the application you were standing in.
 *
 * Each tone changes the texture in the band and the colour of the eyebrow, and
 * nothing else. It is orientation, not decoration - if a reader cannot tell
 * two tones apart at a glance the prop is not doing its job, and if the tones
 * start carrying meaning beyond "which group", it is doing too much.
 */
export type PageTone = "work" | "data" | "developer"

interface PageProps {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  /** Chat wants a full-height column; list views want normal document flow. */
  fill?: boolean
  /** A small line above the title, in mono caps. */
  eyebrow?: string
  /** Anything that belongs inside the band rather than under it. */
  banner?: ReactNode
  /**
   * Drop the decorative mark. It sits in the top-right corner of every page,
   * which is fine over a single column and lands on top of the content on a
   * page with a right-hand panel.
   */
  plain?: boolean
  /** Which sidebar group this page sits in. Defaults to the working surfaces. */
  tone?: PageTone
  className?: string
}

export function Page({
  title,
  description,
  actions,
  children,
  fill,
  eyebrow,
  banner,
  plain,
  tone = "work",
  className,
}: PageProps) {
  return (
    <div className={cn("flex min-h-dvh flex-col", className)}>
      <header className="relative overflow-hidden border-b bg-gradient-to-b from-card/70 via-card/25 to-transparent">
        <BandColour tone={tone} />
        <BandTexture tone={tone} />
        {plain ? null : <SheetsMark />}

        <div
          className={cn(
            "relative flex flex-wrap items-end justify-between gap-4 px-5 lg:px-8",
            // `plain` marks the developer pages, which carry a right-hand panel
            // and have to fit a screen without scrolling. The band earns its
            // height on a working surface and spends it here.
            plain ? "py-4 lg:py-5" : "py-7 lg:py-8",
          )}
        >
          <div className="min-w-0 max-w-2xl space-y-2">
            {eyebrow ? (
              <p
                className={cn(
                  "font-mono text-[11px] uppercase tracking-[0.2em]",
                  EYEBROW[tone],
                )}
              >
                {eyebrow}
              </p>
            ) : null}
            <h1
              className={cn(
                "font-semibold tracking-tight",
                plain ? "text-xl sm:text-2xl" : "text-2xl sm:text-3xl",
              )}
            >
              {title}
            </h1>
            {description ? (
              <p className="text-sm leading-relaxed text-muted-foreground sm:text-base">
                {description}
              </p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>

        {banner ? <div className="relative px-5 pb-7 lg:px-8">{banner}</div> : null}
      </header>

      <div
        className={cn(
          "px-5 lg:px-8",
          plain ? "py-4" : "py-6",
          fill ? "flex min-h-0 flex-1 flex-col" : "animate-fade-in",
        )}
      >
        {children}
      </div>
    </div>
  )
}

const EYEBROW: Record<PageTone, string> = {
  work: "text-primary",
  data: "text-accent",
  developer: "text-muted-foreground",
}

//: The CSS variable each tone colours itself with. Kept as bare variable names
//: rather than Tailwind classes because the wash needs them inside an
//: `hsl(var(--x) / 0.1)` expression, which a utility class cannot express.
const TONE_VAR: Record<PageTone, string> = {
  work: "--primary",
  data: "--accent",
  developer: "--muted-foreground",
}

/**
 * The band's own colour, and the rule above it.
 *
 * Texture alone turned out not to be enough separation: the three bands were
 * distinguishable side by side in a comparison and not while actually moving
 * between pages, which is the only place it matters. A tinted wash and a 2px
 * rule read instantly and from the corner of the eye.
 *
 * Both are the same hue as the eyebrow and the texture, so each group has one
 * colour saying one thing in four places rather than four decorations.
 */
function BandColour({ tone }: { tone: PageTone }) {
  const variable = TONE_VAR[tone]
  return (
    <>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: `linear-gradient(to bottom, hsl(var(${variable}) / 0.1), transparent 70%)`,
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[2px]"
        style={{ backgroundColor: `hsl(var(${variable}))` }}
      />
    </>
  )
}

/**
 * The texture in the band, chosen by which half of the application you are in.
 *
 * `data` reuses the contour field generated for the home page - the same
 * `topo-mask.webp`, used the same way, as a mask over a themed fill rather than
 * as a picture. Carrying one asset across the pages that hold your material is
 * what makes them read as a set; a second generated image would have been two
 * unrelated textures instead of one motif.
 *
 * `developer` gets ruled lines rather than anything organic, because it is the
 * machine half of the application and should not look inviting.
 */
function BandTexture({ tone }: { tone: PageTone }) {
  const fade = "linear-gradient(to bottom, black, transparent 92%)"

  if (tone === "data") {
    // Two nested elements rather than two mask layers on one. Stacking the
    // contour and the fade as `mask-image: a, b` needs `mask-composite`, whose
    // standard and -webkit- spellings take different keywords; setting both is
    // how the first attempt at this ended up drawing a flat wash with no
    // contours in it at all. Nesting needs no compositing and behaves the same
    // everywhere.
    return (
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ maskImage: fade, WebkitMaskImage: fade }}
      >
        <div
          className="absolute inset-0 bg-accent opacity-[0.28] dark:opacity-[0.22]"
          style={{
            maskImage: "url(/art/topo-mask.webp)",
            WebkitMaskImage: "url(/art/topo-mask.webp)",
            // Sized and pushed off the top-right corner so the contours gather
            // where nothing is written and thin out before they reach the
            // title. A texture centred behind the heading is a texture you have
            // to apologise for with opacity.
            maskSize: "auto 340px",
            WebkitMaskSize: "auto 340px",
            maskPosition: "right -30px top -40px",
            WebkitMaskPosition: "right -30px top -40px",
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
          }}
        />
      </div>
    )
  }

  if (tone === "developer") {
    // Circuit traces, generated by the same script and in the same line style
    // as the contours, placed with the same geometry. Two textures that differ
    // in subject but agree on everything else is what makes them a set rather
    // than two pictures.
    //
    // It is grey rather than coloured on purpose: this is the machine half of
    // the application, and the accent colours belong to the halves a user
    // actually works in.
    return (
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ maskImage: fade, WebkitMaskImage: fade }}
      >
        <div
          className="absolute inset-0 bg-muted-foreground opacity-[0.3] dark:opacity-[0.26]"
          style={{
            maskImage: "url(/art/circuit-mask.webp)",
            WebkitMaskImage: "url(/art/circuit-mask.webp)",
            // Not tiled. Repeating it across the band looks like a printed
            // circuit board and runs the traces straight behind the title;
            // one corner cluster reads as a mark instead of as wallpaper.
            maskSize: "auto 320px",
            WebkitMaskSize: "auto 320px",
            maskPosition: "right -20px top -30px",
            WebkitMaskPosition: "right -20px top -30px",
            maskRepeat: "no-repeat",
            WebkitMaskRepeat: "no-repeat",
          }}
        />
      </div>
    )
  }

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 opacity-40"
      style={{
        backgroundImage:
          "radial-gradient(circle at 1px 1px, hsl(var(--border)) 1px, transparent 0)",
        backgroundSize: "22px 22px",
        maskImage: fade,
        WebkitMaskImage: fade,
      }}
    />
  )
}

/**
 * Three stacked sheets passing into a check: a document going through a review
 * and coming out accepted, which is what this application is for. Geometric on
 * purpose - an illustration of a person would be a stock photo drawn by hand.
 */
function SheetsMark() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 220 180"
      className="pointer-events-none absolute -right-4 -top-6 hidden h-[170px] w-[210px] opacity-[0.13] lg:block"
    >
      <defs>
        <linearGradient id="praxa-sheets" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(var(--accent))" />
        </linearGradient>
      </defs>
      <g stroke="url(#praxa-sheets)" strokeWidth="2" fill="none">
        <rect x="24" y="26" width="92" height="118" rx="10" opacity="0.4" />
        <rect x="44" y="18" width="92" height="118" rx="10" opacity="0.65" />
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
