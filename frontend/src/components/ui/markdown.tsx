import type { ComponentPropsWithoutRef } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { uniqueSlugger } from "@/lib/markdown"
import { cn } from "@/lib/utils"

/**
 * One renderer for everything a model writes: chat answers and generated
 * documents both come through here.
 *
 * `remark-gfm` is what adds tables, strikethrough, task lists and bare-URL
 * autolinking on top of plain Markdown. Without it a comparison the model
 * formatted as a table renders as a pile of pipe characters.
 *
 * **Raw HTML is not enabled.** `react-markdown` ignores HTML unless `rehype-raw`
 * is installed and passed as a rehype plugin, and it is not. That is deliberate
 * rather than incidental: the text reaching this component was written by a
 * model that has just read a job posting, and a posting is attacker-controlled.
 *
 * Every element is mapped to the application's own classes rather than left to
 * a prose stylesheet, so the output matches the rest of the interface and dark
 * mode works from the same tokens as everything else.
 */
export function Markdown({ children, compact }: { children: string; compact?: boolean }) {
  // One slugger per render, walked in document order - the same order
  // `headings()` walks - so the nav's anchors match the ids emitted here.
  const next = uniqueSlugger()
  const heading = (text: unknown) => next(String(text ?? ""))

  return (
    <div className={compact ? "space-y-2" : "space-y-4"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children, ...props }) => (
            <h1
              {...props}
              id={heading(children)}
              className="scroll-mt-6 border-b pb-3 text-2xl font-semibold tracking-tight"
            >
              {children}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2
              {...props}
              id={heading(children)}
              className="scroll-mt-6 pt-3 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
            >
              {children}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3 {...props} className="scroll-mt-6 pt-1 font-medium">
              {children}
            </h3>
          ),
          p: ({ children, ...props }) => (
            <p
              {...props}
              className={cn("leading-relaxed", compact ? "text-sm" : "text-[15px]")}
            >
              {children}
            </p>
          ),
          strong: ({ children, ...props }) => (
            <strong {...props} className="font-semibold text-foreground">
              {children}
            </strong>
          ),
          ul: ({ children, ...props }) => (
            <ul
              {...props}
              className={cn(
                "list-disc space-y-1.5 marker:text-muted-foreground",
                compact ? "pl-4" : "pl-5",
              )}
            >
              {children}
            </ul>
          ),
          ol: ({ children, ...props }) => (
            <ol
              {...props}
              className={cn(
                "list-decimal space-y-1.5 marker:text-muted-foreground",
                compact ? "pl-4" : "pl-5",
              )}
            >
              {children}
            </ol>
          ),
          li: ({ children, ...props }) => (
            <li {...props} className="leading-relaxed">
              {children}
            </li>
          ),
          hr: (props) => <hr {...props} className="border-border/70" />,
          blockquote: ({ children, ...props }) => (
            <blockquote {...props} className="border-l-2 pl-4 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
          /* Links open in a new tab, and carry `noreferrer` - the href may have
             come from a job posting, so it is not trusted with a referrer or
             with `window.opener`. */
          a: ({ children, ...props }) => (
            <a
              {...props}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium underline underline-offset-2 hover:text-foreground"
            >
              {children}
            </a>
          ),
          code: Code,
          pre: ({ children, ...props }) => (
            <pre
              {...props}
              className="overflow-x-auto rounded-md border bg-muted/50 p-3 text-xs leading-relaxed scrollbar-thin"
            >
              {children}
            </pre>
          ),
          /* GFM tables. The wrapper is what stops a wide table pushing the
             whole page sideways on a narrow screen. */
          table: ({ children, ...props }) => (
            <div className="overflow-x-auto scrollbar-thin">
              <table {...props} className="w-full border-collapse text-sm">
                {children}
              </table>
            </div>
          ),
          th: ({ children, ...props }) => (
            <th
              {...props}
              className="border-b px-3 py-2 text-left font-semibold [&[align=center]]:text-center [&[align=right]]:text-right"
            >
              {children}
            </th>
          ),
          td: ({ children, ...props }) => (
            <td
              {...props}
              className="border-b border-border/50 px-3 py-2 align-top [&[align=center]]:text-center [&[align=right]]:text-right"
            >
              {children}
            </td>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

/**
 * Inline code and fenced code are the same element in Markdown's model; only
 * the parent differs. `react-markdown` v9 dropped the `inline` prop, so the
 * distinction is made by looking for the language class a fenced block gets
 * and falling back to "no newline means inline".
 */
function Code({ className, children, ...props }: ComponentPropsWithoutRef<"code">) {
  const fenced = /\blanguage-/.test(className ?? "") || String(children).includes("\n")

  if (fenced) {
    return (
      <code {...props} className={cn("font-mono", className)}>
        {children}
      </code>
    )
  }

  return (
    <code
      {...props}
      className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em] text-foreground"
    >
      {children}
    </code>
  )
}
