import path from "node:path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The API runs on FastAPI (uvicorn) during development; in production the same
// FastAPI process serves this bundle from dist/, so the app always talks to a
// same-origin "/api" and never needs CORS or a base-URL environment variable.
const API_TARGET = process.env.PRAXA_API_URL ?? "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
})
