import { Compass } from "lucide-react"
import { Link } from "react-router-dom"

import { Page } from "@/components/layout/page"
import { buttonVariants } from "@/components/ui/button-variants"
import { EmptyState } from "@/components/ui/empty-state"

export function NotFoundRoute() {
  return (
    <Page title="Not found" description="That page does not exist.">
      <EmptyState
        icon={Compass}
        title="Nothing here"
        description="The address does not match any part of the app."
        action={
          <Link to="/" className={buttonVariants()}>
            Back to chat
          </Link>
        }
      />
    </Page>
  )
}
