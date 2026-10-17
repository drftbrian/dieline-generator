import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

/** Upload expectations checklist. Always visible inside the drop zone. */
export function UploadExpectations({ onGuide }: { onGuide: () => void }) {
  return (
    <div className="mx-auto max-w-md text-left">
      <p className="mb-2 text-sm font-medium">{ko.upload.expectTitle}</p>
      <ul className="space-y-1 text-sm">
        {ko.upload.expectations.map((e) => (
          <li key={e.label} className="flex gap-2">
            <span
              aria-hidden
              className={cn('w-4 shrink-0 text-center', e.required ? 'text-emerald-600' : 'text-ink-muted')}
            >
              {e.required ? '✓' : '○'}
            </span>
            <span>
              <span className="font-medium">{e.label}</span>
              <span className="text-ink-muted"> — {e.text}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-muted">
        {ko.upload.expectFootnote}{' '}
        <button
          type="button"
          className="font-medium text-accent hover:underline"
          onClick={(e) => {
            e.stopPropagation()
            onGuide()
          }}
        >
          [{ko.upload.guide}]
        </button>
      </p>
    </div>
  )
}
