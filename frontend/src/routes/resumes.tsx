import {
  Compass,
  FileCheck,
  FileUp,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserRound,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Page } from "@/components/layout/page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import type { Profile, ResumeSlot } from "@/lib/types"
import { formatRelative } from "@/lib/utils"

/**
 * Whose CV the assistant is answering about.
 *
 * Without this page the knowledge base is whatever was put in `data/kb/resumes`
 * by hand, which made the application honest but personal: it answered about
 * one engineer, and anyone else was looking at a demo. Dropping a CV in here
 * changes what every other part of the system reads - retrieval, fit scoring,
 * tailoring, cover letters, interview practice.
 *
 * The badge on each slot matters more than it looks. A profile with no real CV
 * falls back to a committed sample describing a *fictional* person, and an
 * answer about "your experience" drawn from that is worse than no answer. The
 * page says which is which before it says anything else.
 */

const PROFILE_LABEL: Record<Profile, string> = {
  automotive_cyber: "Automotive cybersecurity",
  devops: "DevOps",
  ai_eng: "AI engineering",
  general: "General",
}

/** The id used for the permanently empty row at the bottom of the shelf. */
const NEW_GENERAL = "__new_general__"

export function ResumesRoute() {
  const [slots, setSlots] = useState<ResumeSlot[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function refresh() {
    try {
      setSlots(await api.resumes.list())
    } catch (error) {
      setMessage((error as Error).message)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function upload(profile: Profile, file: File, rowId: string) {
    setBusy(rowId)
    setMessage(null)
    try {
      const content = await file.text()
      const result = await api.resumes.upload({ profile, filename: file.name, content })
      setMessage(result.message)
      await refresh()
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function remove(slot: ResumeSlot) {
    setBusy(slot.id)
    setMessage(null)
    try {
      const result =
        slot.profile === "general"
          ? await api.resumes.removeGeneral(slot.id)
          : await api.resumes.remove(slot.profile)
      setMessage(result.message)
      await refresh()
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Page
      tone="data"
      title="Your CVs"
      description="One CV per career track. Replace a track to answer from your own history instead of the sample."
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-4">
        {message ? (
          <p className="rounded-md border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
            {message}
          </p>
        ) : null}

        {slots === null ? (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <>
            {slots.map((slot) => (
              <Slot
                key={`${slot.profile}:${slot.id}`}
                slot={slot}
                busy={busy === slot.id}
                onUpload={(file) => upload(slot.profile, file, slot.id)}
                onRemove={() => remove(slot)}
              />
            ))}
            {/* Always last, always empty. The shelf has no fixed size, so the
                way to add to it is a row that is permanently available rather
                than a button that appears once the previous upload finished. */}
            <AddGeneral
              busy={busy === NEW_GENERAL}
              onUpload={(file) => upload("general", file, NEW_GENERAL)}
            />
          </>
        )}

        <p className="pt-2 text-xs leading-relaxed text-muted-foreground">
          Markdown or plain text. The file is stored on this machine and indexed locally – the CV
          itself is never sent anywhere except as part of a question you ask.
        </p>
        </div>

        <aside>
          <div className="xl:sticky xl:top-6">
            <ProfilePanel />
          </div>
        </aside>
      </div>
    </Page>
  )
}

/**
 * What a profile is, and the two questions this page kept being asked.
 *
 * Both have the same root: the tracks are a closed set, not a folder of files.
 * `Profile` is an enum, every tool takes one of its members, and the knowledge
 * base has one directory per member. So the page offers replacement and not
 * addition, and saying that plainly is better than leaving someone to hunt for
 * an "add" button that was never going to be there.
 *
 * This panel said "exactly three" until a fourth was added, which is the risk
 * with copy that counts things. It now describes the shape rather than the
 * number, and the number it does quote comes from the slots the API returned.
 */
function ProfilePanel() {
  return (
    <div className="space-y-4 rounded-2xl border bg-card/40 p-5">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent">
          How this works
        </p>
        <p className="mt-1 text-lg font-medium">One CV per track</p>
      </div>

      <Note
        icon={<Layers className="size-4" aria-hidden />}
        title="Why the list is fixed"
        body="The three tracks are bodies of knowledge, not slots. Each has its own folder of reference material, so adding a track is more than adding a file."
      />
      <Note
        icon={<Compass className="size-4" aria-hidden />}
        title="General holds several"
        body="The three tracks take one CV each and replacing overwrites. General is a shelf: add as many as you like, each named after its first heading. Tailoring uses the most recent, marked In use."
      />
      <Note
        icon={<RefreshCw className="size-4" aria-hidden />}
        title="Replacing rebuilds the index"
        body="Takes a few seconds. After that, answers about that track come from your CV instead of the sample."
      />
      <Note
        icon={<FileCheck className="size-4" aria-hidden />}
        title="Tailored CVs go elsewhere"
        body="They are written to your output folder on approval. These are the sources they are written from."
      />
      <Note
        icon={<ShieldCheck className="size-4" aria-hidden />}
        title="Samples are fictional"
        body="A track marked Sample answers as an invented person."
      />
    </div>
  )
}

function Note({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border border-border/70 bg-background/50 text-accent">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
    </div>
  )
}

/**
 * The permanently empty row at the bottom of the General shelf.
 *
 * Not a button that appears when the shelf is empty and vanishes when it is
 * not: the shelf has no fixed size, so there is never a moment when adding to
 * it stops making sense. A row that is always there is also the only affordance
 * on this page that does not look like it might overwrite something.
 */
function AddGeneral({ busy, onUpload }: { busy: boolean; onUpload: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null)

  return (
    <button
      type="button"
      onClick={() => input.current?.click()}
      disabled={busy}
      className="flex w-full items-center gap-3 rounded-lg border border-dashed bg-card/20 px-5 py-4 text-left transition-colors hover:border-border hover:bg-card/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
    >
      <input
        ref={input}
        type="file"
        accept=".md,.markdown,.txt,text/plain,text/markdown"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(file)
          event.target.value = ""
        }}
      />
      <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-dashed text-muted-foreground">
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium">
          {busy ? "Indexing\u2026" : "Add another CV"}
        </span>
        <span className="block text-xs text-muted-foreground">
          Goes on the General shelf.
        </span>
      </span>
    </button>
  )
}

function Slot({
  slot,
  busy,
  onUpload,
  onRemove,
}: {
  slot: ResumeSlot
  busy: boolean
  onUpload: (file: File) => void
  onRemove: () => void
}) {
  const input = useRef<HTMLInputElement>(null)

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card/40 px-5 py-4">
      <div className="min-w-0 space-y-1">
        <p className="flex items-center gap-2 font-medium">
          <UserRound className="size-4 shrink-0 text-muted-foreground" />
          {slot.profile === "general" ? slot.label : PROFILE_LABEL[slot.profile]}
          {slot.profile === "general" ? <Badge variant="outline">General</Badge> : null}
          {slot.inUse ? <Badge>In use</Badge> : null}
          {slot.isYours ? (
            <Badge variant="outline">Yours</Badge>
          ) : (
            <Badge variant="secondary">Sample – a fictional person</Badge>
          )}
        </p>
        <p className="text-sm text-muted-foreground">
          {slot.isYours
            ? `${slot.characters.toLocaleString()} characters${
                slot.updatedAt ? ` · updated ${formatRelative(slot.updatedAt)}` : ""
              }`
            : "No CV of yours here yet. Answers about this profile describe someone invented."}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <input
          ref={input}
          type="file"
          accept=".md,.markdown,.txt,text/plain,text/markdown"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUpload(file)
            event.target.value = ""
          }}
        />
        {slot.isYours ? (
          <Button variant="ghost" size="sm" onClick={onRemove} disabled={busy}>
            <Trash2 className="mr-2 size-4" />
            Remove
          </Button>
        ) : null}
        <Button variant="outline" size="sm" onClick={() => input.current?.click()} disabled={busy}>
          {busy ? <Loader2 className="mr-2 size-4 animate-spin" /> : <FileUp className="mr-2 size-4" />}
          {slot.isYours ? "Replace" : "Upload"}
        </Button>
      </div>
    </div>
  )
}
