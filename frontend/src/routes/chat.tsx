import { MessageSquare, Send, Square } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { AgentTrace } from "@/components/agent-trace"
import { AnswerRating } from "@/components/answer-rating"
import { FeedbackPanel } from "@/components/feedback-panel"
import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Textarea } from "@/components/ui/input"
import { useChatStream } from "@/hooks/use-chat-stream"
import { currentThreadId } from "@/lib/thread"
import type { ChatMessage, Mode } from "@/lib/types"
import { Markdown } from "@/components/ui/markdown"
import { cn } from "@/lib/utils"

/**
 * What the agent may reach on a turn.
 *
 * Each mode owns a different blast radius, and the server enforces it – the
 * tool registry refuses anything outside the current mode, so this control
 * chooses a permission set rather than merely relabelling a prompt. It is here
 * because the interesting tools (scoring a posting, tailoring a CV, writing a
 * cover letter, running STAR practice) exist already and are otherwise
 * unreachable from the browser.
 */
const MODES: { value: Mode; label: string; tools: string; hint: string }[] = [
  {
    value: "chat",
    label: "Chat",
    tools: "1 tool",
    hint: "Answers about your CVs, the standards, ATS and interview technique. Read-only.",
  },
  {
    value: "jobs",
    label: "Jobs",
    tools: "6 tools",
    hint: "Search saved postings, score fit, tailor a CV, write a cover letter, move an application.",
  },
  {
    value: "interview",
    label: "Interview",
    tools: "3 tools",
    hint: "STAR practice: one question at a time, critiqued against your real evidence.",
  },
]

function Bubble({
  message,
  question,
  threadId,
  mode,
  onRated,
}: {
  message: ChatMessage
  /** The question this answer replied to. Stored with a rating, because a
   * verdict on an answer is unreadable later without the thing it answered. */
  question: string
  threadId: string
  mode: Mode
  onRated: () => void
}) {
  const isUser = message.role === "user"
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[46rem] space-y-3 rounded-lg px-4 py-3 text-sm leading-relaxed",
          isUser ? "bg-primary text-primary-foreground" : "border bg-card",
        )}
      >
        {/*
          Rendered, not printed. The answer arrives as Markdown - numbered
          lists, bold, the occasional heading - and this used to be one <p>
          with `whitespace-pre-wrap`, so a five-step answer appeared as a wall
          reading `1. **Collaboration**: ...` with the asterisks visible. The
          renderer is the one the Documents page uses; there is no second
          implementation.
        */}
        {message.content ? (
          <Markdown compact>{message.content}</Markdown>
        ) : (
          <span className="text-muted-foreground">…</span>
        )}

        {message.citations && message.citations.length > 0 ? (
          <div className="space-y-1.5 border-t pt-2.5">
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Sources
            </p>
            {message.citations.map((citation) => (
              <p key={citation.marker} className="text-xs text-muted-foreground">
                <span className="mr-1.5 font-mono text-[10px]">[{citation.marker}]</span>
                {citation.documentTitle}
                {citation.section ? ` · ${citation.section}` : ""}
              </p>
            ))}
          </div>
        ) : null}

        {/*
          Only on a finished answer. `serverId` arrives on the `done` frame, so
          a turn that failed or was stopped has none - and an answer that never
          completed is not one there is anything to say about.
        */}
        {!isUser && message.serverId ? (
          <AnswerRating
            messageId={message.serverId}
            threadId={threadId}
            mode={mode}
            model={message.model ?? "unknown"}
            question={question}
            answer={message.content}
            onChange={onRated}
          />
        ) : null}
      </div>
    </div>
  )
}

export function ChatRoute() {
  const [draft, setDraft] = useState("")
  const [thread] = useState(currentThreadId)
  const [mode, setMode] = useState<Mode>("chat")
  const { messages, phase, rounds, toolsUsed, streaming, error, send, stop } = useChatStream(
    thread,
    mode,
  )
  const [ratedAt, setRatedAt] = useState(0)
  const active = MODES.find((entry) => entry.value === mode) ?? MODES[0]
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, phase, rounds])

  function submit() {
    if (streaming) return
    send(draft)
    setDraft("")
  }

  return (
    <Page
      title="Chat"
      description={active.hint}
      actions={
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border p-0.5">
            {MODES.map((entry) => (
              <button
                key={entry.value}
                type="button"
                onClick={() => setMode(entry.value)}
                disabled={streaming}
                className={cn(
                  "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                  entry.value === mode
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                  streaming && "opacity-60",
                )}
              >
                {entry.label}
              </button>
            ))}
          </div>
          <Badge variant="outline">{active.tools}</Badge>
        </div>
      }
      fill
    >
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <FeedbackPanel reloadKey={ratedAt} />

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1 scrollbar-thin">
          {messages.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="Nothing asked yet"
              description={`${active.hint} Switching mode changes which tools the agent may call – the server enforces it, not the prompt.`}
            />
          ) : (
            messages.map((message, index) => (
              <Bubble
                key={message.id}
                message={message}
                // The user turn immediately before it. Nothing stores the pair,
                // so the pairing is read off the list the page already has.
                question={messages[index - 1]?.content ?? ""}
                threadId={thread}
                mode={mode}
                onRated={() => setRatedAt(Date.now())}
              />
            ))
          )}

          <AgentTrace phase={phase} rounds={rounds} toolsUsed={toolsUsed} />

          {error ? (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <div ref={bottomRef} />
        </div>

        <div className="flex items-end gap-2 border-t pt-4">
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder="Ask a question…  (Enter to send, Shift+Enter for a new line)"
            className="min-h-[52px] resize-none"
            aria-label="Your question"
          />
          {streaming ? (
            <Button variant="outline" size="icon" onClick={stop} aria-label="Stop generating">
              <Square aria-hidden />
            </Button>
          ) : (
            <Button size="icon" onClick={submit} disabled={!draft.trim()} aria-label="Send">
              <Send aria-hidden />
            </Button>
          )}
        </div>
      </div>
    </Page>
  )
}
