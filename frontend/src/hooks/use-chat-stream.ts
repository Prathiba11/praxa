import { useCallback, useEffect, useRef, useState } from "react"

import { streamChat } from "@/lib/api"
import { usageChanged } from "@/lib/usage-bus"
import type {
  AgentPhase,
  ChatMessage,
  Citation,
  EvidenceVerdict,
  Mode,
} from "@/lib/types"

export interface RetrievalRound {
  round: number
  query: string
  verdict: EvidenceVerdict
  sources: number
  /** The grader's one-line justification, when it gave one. */
  reason?: string
}

export interface ChatStreamState {
  messages: ChatMessage[]
  phase: AgentPhase | null
  /** One entry per retrieval round, so a re-query is visible as it happens. */
  rounds: RetrievalRound[]
  toolsUsed: string[]
  streaming: boolean
  error: string | null
}

function makeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * Drives one chat thread over the SSE endpoint.
 *
 * The retrieval rounds are kept separately from the message list because they
 * describe how the answer was reached, not the answer itself – that is what
 * makes the agent loop visible rather than implied.
 */
export function useChatStream(threadId: string, mode: Mode) {
  const [state, setState] = useState<ChatStreamState>({
    messages: [],
    phase: null,
    rounds: [],
    toolsUsed: [],
    streaming: false,
    error: null,
  })

  const abortRef = useRef<(() => void) | null>(null)
  const draftRef = useRef("")

  useEffect(() => () => abortRef.current?.(), [])

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return

      abortRef.current?.()
      draftRef.current = ""

      const userMessage: ChatMessage = {
        id: makeId(),
        role: "user",
        content: trimmed,
        createdAt: new Date().toISOString(),
      }
      const assistantId = makeId()

      setState((previous) => ({
        ...previous,
        messages: [
          ...previous.messages,
          userMessage,
          {
            id: assistantId,
            role: "assistant",
            content: "",
            createdAt: new Date().toISOString(),
          },
        ],
        phase: "moderating",
        rounds: [],
        toolsUsed: [],
        streaming: true,
        error: null,
      }))

      const patchAssistant = (patch: Partial<ChatMessage>) => {
        setState((previous) => ({
          ...previous,
          messages: previous.messages.map((message) =>
            message.id === assistantId ? { ...message, ...patch } : message,
          ),
        }))
      }

      abortRef.current = streamChat({ threadId, mode, message: trimmed }, (event) => {
        switch (event.type) {
          case "status":
            setState((previous) => ({ ...previous, phase: event.phase }))
            break

          case "retrieval":
            setState((previous) => ({
              ...previous,
              rounds: [
                ...previous.rounds.filter((round) => round.round !== event.round),
                {
                  round: event.round,
                  query: event.query,
                  verdict: event.verdict,
                  sources: event.sources,
                  reason: event.reason,
                },
              ].sort((a, b) => a.round - b.round),
            }))
            break

          case "tool":
            if (event.state === "started") {
              setState((previous) =>
                previous.toolsUsed.includes(event.name)
                  ? previous
                  : { ...previous, toolsUsed: [...previous.toolsUsed, event.name] },
              )
            }
            break

          case "token":
            draftRef.current += event.text
            patchAssistant({ content: draftRef.current })
            break

          case "citations":
            patchAssistant({ citations: event.citations as Citation[] })
            break

          case "done":
            // The server's id for this answer, and the model that wrote it.
            // Both were thrown away before there was anything to rate; a
            // rating needs the id to key on and the model to be worth reading
            // back later.
            patchAssistant({ serverId: event.messageId, model: event.usage.model })
            setState((previous) => ({ ...previous, phase: null, streaming: false }))
            // The turn cost something. Tell whoever is displaying the total.
            usageChanged()
            break

          case "error":
            setState((previous) => ({
              ...previous,
              phase: null,
              streaming: false,
              error: event.message,
            }))
            break

          case "end":
            // The server's terminator. A stream that stops without it was cut
            // off; one that stops with it finished on purpose. Either way the
            // spinner has to go – a `done` may never have arrived.
            setState((previous) =>
              previous.streaming ? { ...previous, phase: null, streaming: false } : previous,
            )
            break
        }
      })
    },
    [threadId, mode],
  )

  const stop = useCallback(() => {
    abortRef.current?.()
    setState((previous) => ({ ...previous, streaming: false, phase: null }))
  }, [])

  return { ...state, send, stop }
}
