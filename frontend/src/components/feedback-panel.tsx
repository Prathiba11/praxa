import { ThumbsDown, ThumbsUp, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import type { FeedbackSummary, Rating } from "@/lib/types"
import { cn, formatRelative } from "@/lib/utils"

/**
 * What the ratings add up to, and which turns they were.
 *
 * A tally on its own is a number with no way back to the answer that earned it,
 * which is why the panel opens onto the turns themselves. The useful reading is
 * almost never "82% approval" - it is "these four answers were wrong, and three
 * of them were in Jobs mode".
 *
 * Only rated turns exist here. The application keeps no transcript, and this
 * feature was not the place to start keeping one.
 */
export function FeedbackPanel({ reloadKey }: { reloadKey: number }) {
  const [summary, setSummary] = useState<FeedbackSummary | null>(null)
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<Rating | null>(null)

  const load = useCallback(async () => {
    try {
      setSummary(await api.feedback.read({ rating: filter ?? undefined, limit: 20 }))
    } catch {
      setSummary(null)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load, reloadKey])

  if (!summary || summary.total === 0) return null

  return (
    <div className="rounded-lg border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="text-xs font-medium">Your ratings</span>
        <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
          <ThumbsUp className="h-3 w-3" aria-hidden />
          {summary.up}
        </span>
        <span className="flex items-center gap-1 text-xs text-destructive">
          <ThumbsDown className="h-3 w-3" aria-hidden />
          {summary.down}
        </span>
        {summary.byMode.length > 1 ? (
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {summary.byMode.map((entry) => `${entry.mode} ${entry.up}/${entry.up + entry.down}`).join(" · ")}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">{open ? "Hide" : "Show"}</span>
      </button>

      {open ? (
        <div className="space-y-3 border-t px-3 py-3">
          <div className="flex items-center gap-2">
            {([null, "down", "up"] as (Rating | null)[]).map((value) => (
              <button
                key={value ?? "all"}
                type="button"
                onClick={() => setFilter(value)}
                className={cn(
                  "rounded px-2 py-0.5 text-xs transition-colors",
                  filter === value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {value === null ? "All" : value === "down" ? "Went wrong" : "Useful"}
              </button>
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto h-7 text-xs text-muted-foreground"
              onClick={() => {
                void api.feedback.clear().then(load)
              }}
            >
              <Trash2 className="mr-1 h-3 w-3" aria-hidden />
              Clear all
            </Button>
          </div>

          {summary.recent.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nothing rated that way yet.</p>
          ) : (
            summary.recent.map((entry) => (
              <div key={entry.id} className="space-y-1 border-l-2 pl-3">
                <div className="flex items-center gap-2">
                  {entry.rating === "up" ? (
                    <ThumbsUp className="h-3 w-3 text-emerald-600 dark:text-emerald-400" aria-hidden />
                  ) : (
                    <ThumbsDown className="h-3 w-3 text-destructive" aria-hidden />
                  )}
                  <Badge variant="outline" className="text-[10px]">
                    {entry.mode}
                  </Badge>
                  <span className="font-mono text-[10px] text-muted-foreground">{entry.model}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    {formatRelative(entry.createdAt)}
                  </span>
                </div>
                <p className="text-xs font-medium">{entry.question}</p>
                <p className="line-clamp-2 text-xs text-muted-foreground">{entry.answer}</p>
              </div>
            ))
          )}

          <p className="text-[10px] text-muted-foreground">
            Ratings are stored so you can see which answers went wrong. Nothing here changes how the
            next answer is written – that is a separate piece of work, not something a stored thumb
            does on its own. The newest {summary.maxStored} are kept.
          </p>
        </div>
      ) : null}
    </div>
  )
}
