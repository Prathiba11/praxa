import { ThumbsDown, ThumbsUp } from "lucide-react"
import { useState } from "react"

import { api } from "@/lib/api"
import type { Mode, Rating } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * Two thumbs under a finished answer.
 *
 * Deliberately the narrow half of the feedback task. A rating is recorded, kept
 * and shown back; nothing here changes how the next answer is written. An agent
 * that learns from feedback is a different piece of work, and a thumb in a
 * database is not evidence of one.
 *
 * Clicking the thumb already chosen withdraws the rating. Without that, a
 * mis-click is permanent, and a tally nobody can correct stops being worth
 * reading.
 */
export function AnswerRating({
  messageId,
  threadId,
  mode,
  model,
  question,
  answer,
  onChange,
}: {
  messageId: string
  threadId: string
  mode: Mode
  model: string
  question: string
  answer: string
  onChange?: () => void
}) {
  const [rating, setRating] = useState<Rating | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function choose(next: Rating) {
    if (busy) return
    setBusy(true)
    setFailed(false)
    const previous = rating
    const withdrawing = previous === next

    // Optimistic, then reverted on failure. The alternative is a thumb that
    // waits on a round trip, which reads as a dead button.
    setRating(withdrawing ? null : next)
    try {
      if (withdrawing) {
        await api.feedback.unrate(messageId)
      } else {
        await api.feedback.rate({
          messageId,
          threadId,
          rating: next,
          mode,
          model,
          question,
          answer,
        })
      }
      onChange?.()
    } catch {
      setRating(previous)
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-1 border-t pt-2">
      <Thumb
        icon={ThumbsUp}
        label="This answer was useful"
        active={rating === "up"}
        activeClass="text-emerald-600 dark:text-emerald-400"
        disabled={busy}
        onClick={() => void choose("up")}
      />
      <Thumb
        icon={ThumbsDown}
        label="This answer was wrong or unhelpful"
        active={rating === "down"}
        activeClass="text-destructive"
        disabled={busy}
        onClick={() => void choose("down")}
      />
      {failed ? (
        <span className="ml-1 text-xs text-destructive">Not saved – try again.</span>
      ) : rating ? (
        <span className="ml-1 text-xs text-muted-foreground">Saved. Click again to undo.</span>
      ) : null}
    </div>
  )
}

function Thumb({
  icon: Icon,
  label,
  active,
  activeClass,
  disabled,
  onClick,
}: {
  icon: typeof ThumbsUp
  label: string
  active: boolean
  activeClass: string
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={active}
      title={label}
      className={cn(
        "rounded p-1 text-muted-foreground transition-colors hover:text-foreground",
        active && activeClass,
        disabled && "opacity-50",
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
    </button>
  )
}
