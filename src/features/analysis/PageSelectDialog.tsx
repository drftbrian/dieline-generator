import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/overlays'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { loadPdf, renderPage } from '@/lib/pdf'

function PageThumb({ url, index }: { url: string; index: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let cancelled = false
    const canvas = ref.current
    if (!canvas) return
    loadPdf(url)
      .then(async (doc) => {
        const page = await doc.getPage(index + 1)
        const vp = page.getViewport({ scale: 1 })
        await renderPage(doc, index, canvas, 220 / Math.max(vp.width, vp.height))
      })
      .then(() => !cancelled && setReady(true))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [url, index])
  return (
    <div className="relative flex h-40 items-center justify-center bg-canvas">
      <canvas ref={ref} className="max-h-full max-w-full shadow-sm" />
      {!ready && <Spinner className="absolute" />}
    </div>
  )
}

/** Multi-page PDF: choose which page to analyze. */
export function PageSelectDialog({
  open,
  pageCount,
  sourceUrl,
  pending,
  onSelect,
}: {
  open: boolean
  pageCount: number
  sourceUrl: string
  pending: boolean
  onSelect: (page: number) => void
}) {
  const [selected, setSelected] = useState(0)
  const p = ko.pageSelect
  return (
    <Dialog
      open={open}
      onOpenChange={() => undefined}
      title={p.title(pageCount)}
      description={p.body}
      className="w-[min(92vw,720px)]"
      footer={
        <Button variant="primary" disabled={pending} onClick={() => onSelect(selected)}>
          {pending && <Spinner className="size-3.5" />}
          {p.confirm}
        </Button>
      }
    >
      <div role="radiogroup" aria-label={p.body} className="grid max-h-[50vh] grid-cols-3 gap-3 overflow-y-auto p-0.5">
        {Array.from({ length: pageCount }, (_, i) => (
          <button
            key={i}
            type="button"
            role="radio"
            aria-checked={selected === i}
            onClick={() => setSelected(i)}
            onDoubleClick={() => onSelect(i)}
            className={cn(
              'overflow-hidden rounded-lg border-2 text-left focus-visible:outline-2 focus-visible:outline-accent',
              selected === i ? 'border-accent' : 'border-line hover:border-ink-muted/40',
            )}
          >
            <PageThumb url={sourceUrl} index={i} />
            <span className="block px-2 py-1 text-xs">{p.page(i + 1)}</span>
          </button>
        ))}
      </div>
    </Dialog>
  )
}
