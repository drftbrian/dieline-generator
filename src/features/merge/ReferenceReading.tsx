import { useReanalyzeReference } from '@/api/references'
import type { Reference } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'

const t = ko.studio.merge

/** Claude's reading of the reference, read-only: category, summary, detected form, 7 sections. */
export function ReferenceReading({ projectId, reference: r }: { projectId: string; reference: Reference }) {
  const reread = useReanalyzeReference(projectId)

  if (r.analysis_status === 'pending' || r.analysis_status === 'stale') {
    return (
      <p className="flex items-center gap-1.5 text-xs text-ink-muted">
        <Spinner className="size-3" /> {r.analysis_status === 'stale' ? t.stale : t.reading}
      </p>
    )
  }
  if (r.analysis_status === 'skipped' || !r.analysis) {
    return (
      <div className="space-y-2 rounded-md bg-amber-50 p-3 text-xs text-amber-800">
        <p>{r.analysis_status === 'skipped' ? t.readSkipped : t.readFailed}</p>
        <Button className="h-7 text-xs" disabled={reread.isPending} onClick={() => reread.mutate(r.id)}>
          {t.reread}
        </Button>
        <ErrorNotice error={reread.error} />
      </div>
    )
  }

  const a = r.analysis
  return (
    <div className="space-y-2 text-xs">
      <h3 className="font-semibold text-ink-muted">{t.readingTitle}</h3>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1">
        <dt className="text-ink-muted">{t.category}</dt>
        <dd>
          <Badge>{t.categories[a.category] ?? a.category}</Badge>
        </dd>
        <dt className="text-ink-muted">{t.detectedForm}</dt>
        <dd>{t.forms[a.packaging_form] ?? a.packaging_form}</dd>
      </dl>
      <p className="text-prov-ai">Claude: “{a.summary}”</p>
      <div>
        <p className="mb-1 text-ink-muted">{t.sections}</p>
        <ul className="divide-y divide-line rounded-md border border-line">
          {a.sections.map((s) => (
            <li key={s.key}>
              <details className="group">
                <summary className="cursor-pointer list-none px-2 py-1.5 font-medium hover:bg-canvas">
                  <span className="mr-1 inline-block w-3 text-ink-muted group-open:rotate-90">▸</span>
                  {s.title_ko}
                </summary>
                <p className="px-2 pb-2 pl-6 whitespace-pre-wrap text-ink-muted" lang="en">
                  {s.text_en}
                </p>
              </details>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
