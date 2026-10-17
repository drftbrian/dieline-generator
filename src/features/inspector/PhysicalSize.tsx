import { useState } from 'react'
import { usePatchSpecification } from '@/api/spec'
import type { Specification } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { NumberField } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { ProvenanceBadge } from '@/components/ui/Provenance'
import { Tooltip } from '@/components/ui/overlays'
import { ko } from '@/i18n/ko'

const t = ko.studio.inspector.physical

/** Real-world size: box spec, flat sheet size and where the scale came from. */
export function PhysicalSize({ projectId, spec }: { projectId: string; spec: Specification }) {
  const patch = usePatchSpecification(projectId)
  const [editing, setEditing] = useState(false)
  const [box, setBox] = useState({
    width_mm: spec.box?.width_mm ?? 100,
    depth_mm: spec.box?.depth_mm ?? 50,
    height_mm: spec.box?.height_mm ?? 150,
  })
  const s = spec.scale
  const cut = spec.paths.filter((p) => p.cls === 'cut').flatMap((p) => p.polylines.flat())
  const sheet: [number, number] | null =
    cut.length > 0
      ? [
          (Math.max(...cut.map((q) => q[0])) - Math.min(...cut.map((q) => q[0]))) * s.mm_per_pt,
          (Math.max(...cut.map((q) => q[1])) - Math.min(...cut.map((q) => q[1]))) * s.mm_per_pt,
        ]
      : null

  return (
    <div className="mt-2 space-y-0.5">
      {spec.box && (
        <p>
          <span className="text-ink-muted">{t.box} </span>
          <span className="font-medium tabular-nums">
            {spec.box.width_mm}×{spec.box.depth_mm}×{spec.box.height_mm}mm
          </span>
        </p>
      )}
      {sheet && (
        <p>
          <span className="text-ink-muted">{t.sheet} </span>
          <span className="tabular-nums">
            {sheet[0].toFixed(0)}×{sheet[1].toFixed(0)}mm
          </span>
        </p>
      )}
      <p className="flex flex-wrap items-center gap-1 text-ink-muted">
        <Tooltip content={s.evidence.join(' · ') || t.noScale}>
          <span className="tabular-nums">{t.scale((1 / s.mm_per_pt).toFixed(2))}</span>
        </Tooltip>
        <span>· {t.source[s.source]}</span>
        <ProvenanceBadge kind={s.source === 'pdf_units' ? 'estimate' : s.source === 'user' ? 'user_setting' : 'extracted'} />
        {!editing && (
          <button type="button" className="ml-auto text-accent hover:underline" onClick={() => setEditing(true)}>
            {t.edit}
          </button>
        )}
      </p>
      {editing && (
        <form
          className="mt-1 space-y-1.5 rounded-md border border-line bg-canvas/60 p-2"
          onSubmit={(e) => {
            e.preventDefault()
            patch.mutate({ patch: { box }, version: spec.version }, { onSuccess: () => setEditing(false) })
          }}
        >
          <p className="text-ink-muted">{t.hint}</p>
          {(['width_mm', 'depth_mm', 'height_mm'] as const).map((k, i) => (
            <label key={k} className="flex items-center justify-between gap-2">
              <span>{[t.fields.w, t.fields.d, t.fields.h][i]}</span>
              <NumberField
                label={[t.fields.w, t.fields.d, t.fields.h][i]!}
                value={box[k]}
                min={1}
                max={2000}
                step={0.5}
                suffix="mm"
                onChange={(v) => setBox((b) => ({ ...b, [k]: v }))}
              />
            </label>
          ))}
          <div className="flex justify-end gap-1.5">
            <Button className="h-7 text-xs" onClick={() => setEditing(false)}>
              {t.cancel}
            </Button>
            <Button type="submit" variant="primary" className="h-7 text-xs" disabled={patch.isPending}>
              {t.save}
            </Button>
          </div>
          {patch.error && <ErrorNotice error={patch.error} />}
        </form>
      )}
    </div>
  )
}
