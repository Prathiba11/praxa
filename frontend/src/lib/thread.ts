/**
 * The conversation this tab is having.
 *
 * Two components need it and neither owns the other: the chat page sends
 * turns on it, and the usage meter reports what those turns cost. It lives
 * here so there is one answer rather than two that can drift.
 *
 * `sessionStorage`, not `localStorage`: a new tab should be a new
 * conversation, and closing the tab should end it. If storage is unavailable –
 * a private window, blocked site data – an id is still returned, it just does
 * not survive a reload.
 */
const KEY = "praxa.threadId"

let fallback: string | null = null

export function currentThreadId(): string {
  try {
    const existing = window.sessionStorage.getItem(KEY)
    if (existing) return existing
    const fresh = crypto.randomUUID()
    window.sessionStorage.setItem(KEY, fresh)
    return fresh
  } catch {
    fallback ??= crypto.randomUUID()
    return fallback
  }
}
