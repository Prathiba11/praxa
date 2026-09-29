import { Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { ChatRoute } from "@/routes/chat"
import { DocumentsRoute } from "@/routes/documents"
import { HomeRoute } from "@/routes/home"
import { InterviewRoute } from "@/routes/interview"
import { JobsRoute } from "@/routes/jobs"
import { MemoryRoute } from "@/routes/memory"
import { NotFoundRoute } from "@/routes/not-found"
import { ResumesRoute } from "@/routes/resumes"
import { SettingsRoute } from "@/routes/settings"

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomeRoute />} />
        <Route path="chat" element={<ChatRoute />} />
        <Route path="jobs" element={<JobsRoute />} />
        <Route path="documents" element={<DocumentsRoute />} />
        <Route path="interview" element={<InterviewRoute />} />
        <Route path="memory" element={<MemoryRoute />} />
        <Route path="cvs" element={<ResumesRoute />} />
        <Route path="settings" element={<SettingsRoute />} />
        <Route path="*" element={<NotFoundRoute />} />
      </Route>
    </Routes>
  )
}
