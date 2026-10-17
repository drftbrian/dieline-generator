import { useEffect, useRef, useState } from 'react'
import { Spinner } from '@/components/ui/Spinner'
import { loadPdf, renderPage } from '@/lib/pdf'

/**
 * The original PDF page drawn with PDF.js at the current zoom (re-rendered, not scaled up,
 * so the source stays sharp when inspected — UX P1, §4.4.1). Sized in page points.
 */
export function PdfPageLayer({
  url,
  pageIndex,
  width,
  height,
  zoom,
}: {
  url: string
  pageIndex: number
  width: number
  height: number
  zoom: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  // Re-render at most at the next power-of-two zoom step to avoid thrashing while zooming.
  const step = Math.pow(2, Math.ceil(Math.log2(Math.max(0.25, zoom * (window.devicePixelRatio || 1)))))

  useEffect(() => {
    let cancelled = false
    const canvas = canvasRef.current
    if (!canvas) return
    loadPdf(url)
      .then((doc) => (cancelled ? undefined : renderPage(doc, pageIndex, canvas, step)))
      .then(() => !cancelled && setLoading(false))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [url, pageIndex, step])

  return (
    <div className="absolute top-0 left-0 bg-white shadow-sm" style={{ width, height }}>
      <canvas ref={canvasRef} className="block h-full w-full" />
      {loading && !failed && (
        <div className="absolute inset-0 flex items-center justify-center text-ink-muted">
          <Spinner />
        </div>
      )}
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-ink-muted">
          원본 PDF를 표시하지 못했습니다.
        </div>
      )}
    </div>
  )
}
