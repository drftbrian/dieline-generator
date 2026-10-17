import { useEffect, useRef, useState } from 'react'
import { Spinner } from '@/components/ui/Spinner'
import { loadPdf } from '@/lib/pdf'

/** Original page rendered by PDF.js at the current zoom (re-rendered, not scaled up, so it stays sharp). */
export function SourceLayer({
  url,
  pageIndex,
  width,
  height,
  zoom,
  alt,
}: {
  url: string
  pageIndex: number
  width: number
  height: number
  zoom: number
  alt: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')
  // Re-render only at power-of-two steps so zooming doesn't thrash the renderer.
  const step = Math.pow(2, Math.ceil(Math.log2(Math.max(0.25, zoom * (window.devicePixelRatio || 1)))))

  useEffect(() => {
    let cancelled = false
    let task: { cancel: () => void } | null = null
    const canvas = canvasRef.current
    if (!canvas) return
    ;(async () => {
      try {
        const doc = await loadPdf(url)
        const page = await doc.getPage(pageIndex + 1)
        const base = page.getViewport({ scale: 1 })
        const scale = Math.min(step, 6000 / Math.max(base.width, base.height))
        const viewport = page.getViewport({ scale })
        if (cancelled) return
        // Render off-screen then swap, so the previous frame stays visible while re-rendering.
        const off = document.createElement('canvas')
        off.width = Math.ceil(viewport.width)
        off.height = Math.ceil(viewport.height)
        const render = page.render({ canvas: off, viewport })
        task = render
        await render.promise
        if (cancelled) return
        canvas.width = off.width
        canvas.height = off.height
        canvas.getContext('2d')?.drawImage(off, 0, 0)
        setState('ready')
      } catch {
        if (!cancelled) setState('failed')
      }
    })()
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [url, pageIndex, step])

  return (
    <div className="absolute top-0 left-0 bg-white shadow-sm" style={{ width, height }}>
      <canvas ref={canvasRef} role="img" aria-label={alt} className="block h-full w-full" />
      {state === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center text-ink-muted">
          <Spinner />
        </div>
      )}
      {state === 'failed' && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-muted">
          원본 PDF를 표시하지 못했습니다.
        </div>
      )}
    </div>
  )
}
