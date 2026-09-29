import { Check, Loader2, RotateCw, SearchX } from "lucide-react"

import type { RetrievalRound } from "@/hooks/use-chat-stream"
import type { AgentPhase } from "@/lib/types"
import { cn } from "@/lib/utils"

const PHASE_LABEL: Record<AgentPhase, string> = {
  moderating: "Checking the question",
  thinking: "Deciding what to do",
  searching: "Searching the knowledge base",
  grading: "Grading the evidence",
  requerying: "Evidence was thin – searching again",
  answering: "Writing the answer",
}

const VERDICT_LABEL = {
  sufficient: "enough evidence",
  weak: "thin evidence",
  none: "nothing relevant",
} as const

/**
 * The visible half of the agent loop: which phase it is in, and what the
 * retrieval grader decided on each round. A re-query shows up here as a second
 * row, which is the whole point of agentic retrieval being agentic.
 */
export function AgentTrace({
  phase,
  rounds,
  toolsUsed,
}: {
  phase: AgentPhase | null
  rounds: RetrievalRound[]
  toolsUsed: string[]
}) {
  if (!phase && rounds.length === 0 && toolsUsed.length === 0) return null

  return (
    <div className="space-y-2 rounded-md border bg-card/60 px-3 py-2.5">
      {phase ? (
        <p className="flex items-center gap-2 text-xs font-medium">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" aria-hidden />
          {PHASE_LABEL[phase]}
        </p>
      ) : null}

      {rounds.map((round) => {
        const Icon =
          round.verdict === "sufficient" ? Check : round.verdict === "weak" ? RotateCw : SearchX
        return (
          <p
            key={round.round}
            className="flex items-start gap-2 font-mono text-[11px] leading-relaxed text-muted-foreground"
          >
            <Icon
              className={cn(
                "mt-0.5 size-3 shrink-0",
                round.verdict === "sufficient" ? "text-success" : "text-warning",
              )}
              aria-hidden
            />
            <span className="min-w-0">
              Round {round.round}: “{round.query}” – {round.sources} sources,{" "}
              {VERDICT_LABEL[round.verdict]}
              {round.reason ? (
                <span className="block text-muted-foreground/70">{round.reason}</span>
              ) : null}
            </span>
          </p>
        )
      })}

      {toolsUsed.length > 0 ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          Tools: {toolsUsed.join(", ")}
        </p>
      ) : null}
    </div>
  )
}
