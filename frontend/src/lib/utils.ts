import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatUsd(value: number): string {
  if (value === 0) return "$0.00"
  if (value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

export function formatTokens(value: number): string {
  return new Intl.NumberFormat("en-GB").format(value)
}

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return "unknown"
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 60) return "just now"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/**
 * A fit score as a whole percentage.
 *
 * `score` is a fraction from 0 to 1 everywhere it is produced: the model is
 * asked for 0.0-1.0 and `FitReport.score` clamps to that range. Four separate
 * places rendered it and two of them forgot the x100, so the same 0.7 appeared
 * as "70% evidenced" in one panel, "1% fit" in the badge beside it, and "0.7%"
 * on the Documents page. It lives here, next to the other formatters, so a
 * fifth caller cannot invent a fifth convention.
 */
export function fitPercent(score: number): number {
  return Math.round(score * 100)
}

/** A fit worth highlighting, in the same 0-1 units everything else uses. */
export const STRONG_FIT = 0.7
