import { createContext, useContext } from "react"

export type Theme = "light" | "dark"

export interface ThemeContextValue {
  theme: Theme
  toggle: () => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext)
  if (!value) throw new Error("useTheme must be used inside <ThemeProvider>")
  return value
}

export const THEME_STORAGE_KEY = "praxa.theme"

/** Reads the stored preference, falling back to the OS setting. */
export function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === "light" || stored === "dark") return stored
  } catch {
    // Private browsing or blocked storage: the OS setting is a fine default.
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"
}
