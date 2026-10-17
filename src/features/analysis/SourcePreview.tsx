import { PdfPageLayer } from '@/features/canvas/PdfPageLayer'
import { useViewport } from '@/features/canvas/useViewport'
import { Viewport } from '@/features/canvas/Viewport'

/**
 * The original PDF, visible while analysis runs. Optionally crossfades to the finished flat mockup.
 */
export function SourcePreview({
  url,
  pageIndex,
  widthPt,
  heightPt,
  flatUrl,
}: {
  url: string
  pageIndex: number
  widthPt: number
  heightPt: number
  flatUrl?: string | null
}) {
  const vp = useViewport({ w: widthPt, h: heightPt })
  return (
    <div className="relative h-full w-full">
      <Viewport vp={vp} shortcuts={false}>
        <PdfPageLayer url={url} pageIndex={pageIndex} width={widthPt} height={heightPt} zoom={vp.zoom} />
      </Viewport>
      {flatUrl && (
        <img
          src={flatUrl}
          alt="원본 인쇄 미리보기"
          className="pointer-events-none absolute inset-0 h-full w-full bg-canvas object-contain p-8"
          style={{ animation: 'dieline-fadein 700ms ease-out both' }}
        />
      )}
      <style>{'@keyframes dieline-fadein { from { opacity: 0 } to { opacity: 1 } }'}</style>
    </div>
  )
}
