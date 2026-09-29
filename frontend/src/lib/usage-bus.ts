/**
 * A turn finished and money was spent.
 *
 * The usage meter sits in the app shell and the chat page sits inside it, so
 * neither can hand the other a callback without threading state through every
 * layout component in between. A window event is the smallest thing that
 * closes that gap; a state library would be a large answer to a small
 * question, and a poll would ask the server for numbers that mostly have not
 * changed.
 *
 * Wrapped in these two functions rather than used raw so the event name exists
 * once and both sides are typed against the same thing.
 */
const EVENT = "praxa:usage-changed"

export function usageChanged(): void {
  window.dispatchEvent(new Event(EVENT))
}

export function onUsageChanged(handler: () => void): () => void {
  window.addEventListener(EVENT, handler)
  return () => window.removeEventListener(EVENT, handler)
}
