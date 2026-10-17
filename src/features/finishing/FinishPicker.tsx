import { useState } from 'react'
import type { Finish, FinishCatalog, Panel } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { SegmentedControl } from '@/components/ui/controls'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useFinishingStore } from '@/stores/useFinishingStore'
import { ParamEditor, SurfacePicker } from './FinishControls'
import { assetTargets, defaultParams, sameTargets, surfaceTargets, type SurfaceChoice } from './params'
import { Swatch } from './Swatch'

const t = ko.studio.finishing.assign

/** B–F: category tabs → subtype → parameters → target → [후가공 적용]. */
export function FinishPicker({
  catalog,
  selected,
  panels,
  disabled,
}: {
  catalog: FinishCatalog
  /** Selected (selectable) asset ids. */
  selected: string[]
  panels: Panel[]
  disabled?: boolean
}) {
  const [category, setCategory] = useState(catalog.categories[0]?.id ?? '')
  const [finishId, setFinishId] = useState<string | null>(null)
  const [params, setParams] = useState<Record<string, number>>({})
  const [where, setWhere] = useState<'assets' | 'surface'>('assets')
  // Nothing ticked by default: a sheet-wide finish must be a deliberate choice.
  const [surface, setSurface] = useState<SurfaceChoice>({ sheet: false, panels: [] })
  const existing = useFinishingStore((s) => s.assignments)

  const finishes = catalog.finishes.filter((f) => f.category === category)
  const finish = catalog.finishes.find((f) => f.id === finishId && f.category === category) ?? null

  const choose = (f: Finish) => {
    setFinishId(f.id)
    setParams(defaultParams(f))
    setWhere(f.scope === 'surface' ? 'surface' : 'assets')
  }

  const mode = finish?.scope === 'surface' ? 'surface' : finish?.scope === 'selective' ? 'assets' : where
  const targets = mode === 'assets' ? assetTargets(selected) : surfaceTargets(surface)
  const blocked = !finish ? t.pickFinish : targets.length === 0 ? (mode === 'assets' ? t.needSelection : t.needPanel) : null

  // The same finish on the same targets again updates it instead of stacking a second layer.
  const twin = finish ? existing.find((a) => a.finish === finish.id && sameTargets(a.targets, targets)) : undefined
  const spotUv = catalog.finishes.find((f) => f.id === 'coating.spot_uv' && f.available)
  const surfaceOnSelection = mode === 'surface' && finish?.scope === 'surface' && selected.length > 0
  const label = twin
    ? t.update
    : mode === 'assets'
      ? t.applyTo.assets(selected.length)
      : surface.sheet
        ? t.applyTo.sheet
        : surface.panels.length
          ? t.applyTo.panels(surface.panels.length)
          : t.apply

  const apply = () => {
    if (!finish || blocked) return
    const store = useFinishingStore.getState()
    if (twin) store.update(twin.id, { params: { ...params }, enabled: true })
    else store.add({ finish: finish.id, targets, params: { ...params }, enabled: true })
  }

  const switchToSpotUv = () => {
    if (!spotUv) return
    setCategory(spotUv.category)
    choose(spotUv)
  }

  return (
    <div className="space-y-3">
      <div role="tablist" aria-label={t.categories} className="flex flex-wrap gap-1">
        {catalog.categories.map((c) => (
          <button
            key={c.id}
            type="button"
            role="tab"
            aria-selected={c.id === category}
            title={c.label_en}
            onClick={() => setCategory(c.id)}
            className={cn(
              'h-7 rounded-md px-2.5 text-xs font-medium',
              'focus-visible:outline-2 focus-visible:outline-accent',
              c.id === category ? 'bg-ink text-white' : 'bg-canvas text-ink-muted hover:text-ink',
            )}
          >
            {c.label_ko}
          </button>
        ))}
      </div>

      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-ink-muted">{t.subtypes}</p>
          <p className="text-[10px] text-ink-muted">{t.swatchCaption}</p>
        </div>
        <ul role="listbox" aria-label={t.subtypes} className="grid grid-cols-2 gap-1">
          {finishes.map((f) => {
            const on = f.id === finish?.id
            return (
              <li key={f.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={on}
                  disabled={!f.available}
                  title={f.available ? f.note || f.label_en : `${t.soon} — ${f.note || f.label_en}`}
                  onClick={() => choose(f)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md border p-1.5 text-left',
                    'focus-visible:outline-2 focus-visible:outline-accent',
                    on ? 'border-accent bg-accent/5' : 'border-line hover:bg-canvas',
                    !f.available && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                  )}
                >
                  <Swatch finish={f} size={26} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">{f.label_ko}</span>
                    <span className="block truncate text-[10px] text-ink-muted">
                      {f.available ? f.label_en : t.soon}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {finish && (
        <div className="space-y-3 rounded-md bg-canvas/60 p-2.5">
          <ParamEditor finish={finish} values={params} onChange={setParams} />

          <div className="space-y-1.5">
            <p className="text-xs font-medium text-ink-muted">{t.target}</p>
            <p className="text-[11px] text-ink-muted">{t.scopeHint[finish.scope]}</p>
            {finish.scope === 'both' && (
              <SegmentedControl
                size="sm"
                label={t.target}
                value={where}
                onChange={setWhere}
                options={[
                  { value: 'assets', label: t.targetSelection(selected.length) },
                  { value: 'surface', label: t.targetSurface },
                ]}
              />
            )}
            {mode === 'assets' ? (
              <p className={cn('text-xs', selected.length ? 'font-medium' : 'text-amber-800')}>
                {t.targetSelection(selected.length)}
              </p>
            ) : (
              <SurfacePicker panels={panels} value={surface} onChange={setSurface} />
            )}
            {surfaceOnSelection && (
              <div className="space-y-1.5 rounded-md border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900">
                <p>{t.surfaceOnSelection}</p>
                {spotUv && (
                  <Button variant="secondary" className="h-7 text-xs" onClick={switchToSpotUv}>
                    {t.toSpotUv}
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <Button
        variant="primary"
        className="h-9 w-full justify-center"
        disabled={disabled || !!blocked}
        title={blocked ?? undefined}
        onClick={apply}
      >
        {label}
      </Button>
      {blocked ? (
        <p className="text-[11px] text-ink-muted">{blocked}</p>
      ) : (
        twin && <p className="text-[11px] text-ink-muted">{t.updateNote}</p>
      )}
    </div>
  )
}
