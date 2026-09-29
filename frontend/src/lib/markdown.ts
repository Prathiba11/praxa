/**
 * Heading extraction and slugs. The rendering lives in `components/ui/markdown`.
 *
 * This file used to hold a hand-written Markdown parser - six constructs,
 * about a hundred lines, on the reasoning that a library was a big dependency
 * for a small vocabulary. A code review disagreed, and it was right:
 * the six constructs it handled were headings, bold, bullets, numbered lists,
 * paragraphs and rules, and the three it did not were **code blocks, tables and
 * links**. For a general assistant that is survivable. For one whose tracks are
 * DevOps and AI engineering, the two things it could not render are the two
 * things those answers contain most - a Terraform snippet arrived as a run-on
 * paragraph with stray backticks in it.
 *
 * `react-markdown` with `remark-gfm` replaced it. Raw HTML stays disabled:
 * `react-markdown` ignores HTML unless `rehype-raw` is added, and it is not
 * added, so text that came out of a model cannot become markup on the page.
 *
 * What remains here is the slug function, which has to be shared. The Documents
 * page builds a section nav from the headings in a draft, and those anchors
 * only work if the id in the nav and the id on the rendered heading are
 * computed the same way.
 */

export interface Heading {
  id: string
  level: 1 | 2
  text: string
}

/** A stable, URL-safe id for a heading. */
export function slug(text: string): string {
  return `s-${text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")}`
}

/**
 * Makes each id unique within one document.
 *
 * Two sections called "Experience" would otherwise both link to the first one.
 * The renderer and the nav each build their own counter and walk the headings
 * in the same order, so they agree without sharing state.
 */
export function uniqueSlugger(): (text: string) => string {
  const used = new Set<string>()
  return (text: string) => {
    const base = slug(text)
    let id = base
    let suffix = 2
    while (used.has(id)) id = `${base}-${suffix++}`
    used.add(id)
    return id
  }
}

/**
 * The h1 and h2 headings of a Markdown document, in order.
 *
 * Deliberately a regex over the source rather than a walk of the rendered
 * tree: the nav has to exist before anything renders, and this is the one
 * question about the document that the renderer cannot answer.
 *
 * Fenced code is skipped. A shell snippet containing `# comment` is a comment,
 * not a heading, and the old parser put those in the section list.
 */
export function headings(source: string): Heading[] {
  const next = uniqueSlugger()
  const found: Heading[] = []
  let inFence = false

  for (const raw of source.split("\n")) {
    const line = raw.trimEnd()

    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue

    const match = /^(#{1,2})\s+(.*)$/.exec(line)
    if (!match) continue

    const text = match[2].trim().replace(/\s*#+\s*$/, "")
    if (!text) continue

    found.push({ id: next(text), level: match[1].length as 1 | 2, text })
  }

  return found
}
