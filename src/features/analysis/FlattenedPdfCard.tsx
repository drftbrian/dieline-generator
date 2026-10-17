import { Button } from '@/components/ui/Button'
import { ko } from '@/i18n/ko'

/** Raster-only PDF warning. */
export function FlattenedPdfCard({ onDraw, onOther }: { onDraw: () => void; onOther: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <p className="font-semibold text-amber-900">{ko.flattened.title}</p>
      <p className="mt-1 text-amber-900/80">{ko.flattened.body}</p>
      <div className="mt-3 flex gap-2">
        <Button variant="primary" onClick={onDraw}>
          {ko.flattened.draw}
        </Button>
        <Button onClick={onOther}>{ko.flattened.other}</Button>
      </div>
    </div>
  )
}
