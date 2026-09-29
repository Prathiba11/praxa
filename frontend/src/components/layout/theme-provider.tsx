import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react"

import {
  THEME_STORAGE_KEY,
  ThemeContext,
  readStoredTheme,
  type Theme,
} from "@/hooks/use-theme"

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme())

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", theme === "dark")
    root.style.colorScheme = theme
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // Not being able to remember the choice is not worth failing over.
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"))
  }, [])

  const value = useMemo(() => ({ theme, toggle }), [theme, toggle])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
