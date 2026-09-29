import { useCallback, useEffect, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { currentThreadId } from "@/lib/thread"
import type { UsageSummary } from "@/lib/types"
import { onUsageChanged } from "@/lib/usage-bus"
import { cn, formatTokens, formatUsd } from "@/lib/utils"

/**
 * Session spend, read from what OpenRouter actually charged rather than from a
 * local price table. The estimate line is what the next answer is expected to
 * cost with the current settings.
 */
export function UsageMeter() {
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  const refresh = useCallback(() => {
    let cancelled = false
    api
      .usage(currentThreadId())
      .then((value) => {
        if (!cancelled) {
          setUsage(value)
          setUnavailable(false)
        }
      })
      .catch(() => {
        if (!cancelled) setUnavailable(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Once on mount, then again whenever a turn finishes. Polling would ask the
  // server for a number that has usually not changed; waiting for the next
  // page load would show a spend figure that is quietly out of date, which is
  // the one thing a spend figure must never be.
  useEffect(refresh, [refresh])
  useEffect(() => onUsageChanged(refresh), [refresh])

  if (unavailable) {
    return (
      <p className="px-1 font-mono text-[10px] leading-relaxed text-muted-foreground">
        Usage unavailable – API not running
      </p>
    )
  }

  if (!usage) {
    return (
      <div className="space-y-2 px-1">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-2 w-full" />
      </div>
    )
  }

  const spent = usage.sessionCostUsd
  const limit = usage.sessionBudgetUsd
  const fraction = limit > 0 ? Math.min(spent / limit, 1) : null
  const nearLimit = fraction !== null && fraction > 0.8

  return (
    <div className="space-y-2 px-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          This session
        </span>
        <span className="tabular text-xs font-semibold">{formatUsd(spent)}</span>
      </div>

      {fraction !== null ? (
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(fraction * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Budget used"
        >
          <div
            className={cn(
              "h-full rounded-full transition-all",
              nearLimit ? "bg-warning" : "bg-primary",
            )}
            style={{ width: `${fraction * 100}%` }}
          />
        </div>
      ) : null}

      <p className="tabular font-mono text-[10px] leading-relaxed text-muted-foreground">
        {formatTokens(usage.sessionTokens)} tokens
        {limit > 0 ? ` · ${formatUsd(limit)} limit` : " · no limit set"}
        <br />
        {formatUsd(usage.budgetRemainingUsd)} left · about{" "}
        {formatUsd(usage.estimatedCostPerAnswerUsd)} per answer
        {usage.unpricedCalls > 0 ? (
          <>
            <br />
            <span className="text-warning">
              {usage.unpricedCalls} call{usage.unpricedCalls === 1 ? "" : "s"} with no known
              price – this total is a floor
            </span>
          </>
        ) : null}
      </p>
    </div>
  )
}
