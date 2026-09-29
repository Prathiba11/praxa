import {
  Activity,
  Brain,
  Briefcase,
  ExternalLink,
  FileCheck,
  FileUser,
  Home,
  Menu,
  MessageSquare,
  Mic,
  Moon,
  Settings,
  Sun,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"

import { AmbientBackdrop } from "@/components/layout/hero"
import { UsageMeter } from "@/components/layout/usage-meter"
import { api } from "@/lib/api"
import type { HealthResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { useTheme } from "@/hooks/use-theme"
import { cn } from "@/lib/utils"

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

// Interview used to be a mode of the chat and nothing more, on the reasoning
// that "a route that could only ever hold one message box would be a second
// front door to the same room". That held right up until someone practised
// with it: chat has no session, so asking for a question twice produced two
// questions instead of a question and a critique, and "I don't know" produced
// a lecture on STAR rather than the interview moving on.
//
// The page is not a message box. It sets up a track, a persona and a
// difficulty, scores each answer on five dimensions, follows up on a weak one
// on the same question, keeps a transcript, and survives a refresh because the
// session lives in the database. None of that fits in a chat turn. The mode
// stays - it is still the quickest way to get one question - and the page is
// where a real practice session happens.
const PRIMARY: NavItem[] = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/jobs", label: "Jobs", icon: Briefcase },
  { to: "/documents", label: "Documents", icon: FileCheck },
  { to: "/interview", label: "Interview", icon: Mic },
]

const SECONDARY: NavItem[] = [
  { to: "/cvs", label: "Your CVs", icon: FileUser },
  { to: "/memory", label: "What it remembers", icon: Brain },
]

// The developer half, kept in its own group at the bottom. The principle
// behind it: model settings separate from the
// experience, because the person using a career assistant is not necessarily
// someone who knows what a temperature is.
const DEVELOPER: NavItem[] = [{ to: "/settings", label: "Model settings", icon: Settings }]

function NavGroup({
  items,
  label,
  onNavigate,
  collapsedLabel,
}: {
  items: NavItem[]
  label?: string
  onNavigate: () => void
  collapsedLabel?: boolean
}) {
  return (
    <div className="space-y-1">
      {label ? (
        <p
          className={cn(
            "px-3 pb-1 pt-5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground",
            collapsedLabel && "lg:hidden",
          )}
        >
          {label}
        </p>
      ) : null}
      {items.map(({ to, label: text, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              // The active item gets three signals, not one: a filled
              // background, a brighter label and a rail down its left edge.
              // Colour alone would leave it invisible to anyone who cannot
              // see the difference.
              "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isActive
                ? "bg-secondary font-medium text-secondary-foreground"
                : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
            )
          }
        >
          {({ isActive }) => (
            <>
              <span
                aria-hidden
                className={cn(
                  "absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-primary transition-opacity duration-200",
                  isActive ? "opacity-100" : "opacity-0",
                )}
              />
              <Icon
                className={cn(
                  "size-4 shrink-0 transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground",
                )}
                aria-hidden
              />
              <span className={cn("truncate", collapsedLabel && "lg:hidden")}>{text}</span>
            </>
          )}
        </NavLink>
      ))}
    </div>
  )
}


/**
 * Whether this turn is being traced, and where to read it.
 *
 * Tracing is the one setting whose effect is invisible from inside the
 * application: everything else that is misconfigured shows up as an error,
 * while tracing being off shows up as an empty LangSmith project an hour later.
 * So it says which, in the corner, permanently.
 *
 * The address is computed by the server from the configured API host rather
 * than written here. `eu.api.smith.langchain.com` is the API; the interface is
 * the same host without the `api.`, and confusing the two is the most common
 * way a LangSmith setup silently fails.
 */
function TracingChip() {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    void api
      .health()
      .then((value) => !cancelled && setHealth(value))
      .catch(() => {
        // The sidebar must not shout because a status probe failed.
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!health) return null

  if (!health.tracing) {
    return (
      <p className="flex items-center gap-2 px-1 py-1 text-xs text-muted-foreground">
        <span className="size-1.5 rounded-full bg-muted-foreground/50" aria-hidden />
        Tracing off
      </p>
    )
  }

  return (
    <a
      href={health.tracingUrl ?? "https://smith.langchain.com"}
      target="_blank"
      rel="noreferrer noopener"
      className="group flex items-center gap-2 rounded-md px-1 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="relative flex size-1.5 shrink-0" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
        <span className="relative inline-flex size-1.5 rounded-full bg-success" />
      </span>
      <Activity className="size-3 shrink-0" aria-hidden />
      <span className="truncate">
        Traced to <span className="font-mono">{health.tracingProject}</span>
      </span>
      <ExternalLink className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
    </a>
  )
}

export function AppShell() {
  const { theme, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()

  // A drawer that survives navigation would cover the page it just opened.
  useEffect(() => setOpen(false), [location.pathname])

  // Escape closes it, because a drawer with no keyboard exit is a trap.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <AmbientBackdrop />
      {/* Mobile bar. The sidebar itself is a drawer below the lg breakpoint. */}
      <div className="flex items-center justify-between border-b px-4 py-3 lg:hidden">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setOpen(true)}
          aria-label="Open the navigation"
          aria-expanded={open}
        >
          <Menu aria-hidden />
        </Button>
        <span className="flex items-baseline gap-2">
          <span className="text-base font-semibold tracking-tight">Praxa</span>
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Career copilot
          </span>
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
        </Button>
      </div>

      {open ? (
        <button
          type="button"
          aria-label="Close the navigation"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 animate-fade-in bg-background/70 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={cn(
          "flex shrink-0 flex-col bg-card/30",
          "lg:sticky lg:top-0 lg:h-dvh lg:w-64 lg:border-r",
          // Off-canvas on small screens, static from lg upward.
          "fixed inset-y-0 left-0 z-50 w-72 border-r transition-all duration-200 lg:static lg:z-auto lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
          collapsed ? "lg:w-[68px]" : "lg:w-64",
        )}
      >
        <div className="flex items-center justify-between gap-1 px-3 py-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => (window.innerWidth >= 1024 ? setCollapsed((v) => !v) : setOpen(false))}
            aria-label={collapsed ? "Expand the navigation" : "Collapse the navigation"}
            aria-expanded={!collapsed}
          >
            <Menu aria-hidden />
          </Button>
          <div className={cn("flex min-w-0 flex-1 items-baseline gap-2", collapsed && "lg:hidden")}>
            <span className="font-display text-lg font-bold tracking-tight">PRAXA</span>
            <span className="truncate font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Career copilot
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            className="hidden lg:inline-flex"
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <Sun aria-hidden /> : <Moon aria-hidden />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setOpen(false)}
            className="lg:hidden"
            aria-label="Close the navigation"
          >
            <X aria-hidden />
          </Button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 pb-3 scrollbar-thin">
          <NavGroup items={PRIMARY} onNavigate={() => setOpen(false)} collapsedLabel={collapsed} />
          <NavGroup
            items={SECONDARY}
            label="Your data"
            onNavigate={() => setOpen(false)}
            collapsedLabel={collapsed}
          />
          <NavGroup
            items={DEVELOPER}
            label="Developer"
            onNavigate={() => setOpen(false)}
            collapsedLabel={collapsed}
          />
        </nav>

        <div className={cn("space-y-2 border-t p-3", collapsed && "lg:hidden")}>
          <UsageMeter />
          <TracingChip />
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  )
}
