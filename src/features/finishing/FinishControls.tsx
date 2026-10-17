import type { Finish, Panel } from '@/api/types'
import { Slider } from '@/components/ui/controls'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { formatParam, paramStep, snapParam, type SurfaceChoice } from './params'

const t = ko.studio.finishing.assign

/**
 * Sliders for a finish's parameters. `onChange` fires while dragging; `onCommit` once a drag /
 * key press / reset ends (the applied list records one undo step per commit).
 */
export function ParamEditor({
  finish,
  values,
  onChange,
  onCommit,
}: {
  finish: Finish
  values: Record<string, number>
  onChange: (next: Record<string, number>) => void
  onCommit?: (next: Record<string, number>) => void
}) {
  if (finish.params.length === 0) return <p className="text-[11px] text-ink-muted">{t.noParams}</p>
  const allDefault = finish.params.every((p) => (values[p.id] ?? p.default) === p.default)
  const resetAll = () => {
    const next = { ...values, ...Object.fromEntries(finish.params.map((p) => [p.id, p.default])) }
    onChange(next)
    onCommit?.(next)
  }
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-ink-muted">{t.params}</p>
        <button
          type="button"
          disabled={allDefault}
          onClick={resetAll}
          className="text-[11px] text-ink-muted underline-offset-2 hover:text-ink hover:underline disabled:pointer-events-none disabled:opacity-40"
        >
          {t.resetAll}
        </button>
      </div>
      {finish.params.map((p) => {
        const v = values[p.id] ?? p.default
        const set = (x: number) => ({ ...values, [p.id]: snapParam(p, x) })
        return (
          <div key={p.id} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="min-w-0 truncate" title={p.note || p.label_en}>
                {p.label_ko} <span className="text-[10px] text-ink-muted">{p.label_en}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span className="tabular-nums">{formatParam(p, v)}</span>
                <button
                  type="button"
                  disabled={v === p.default}
                  title={t.resetTitle(formatParam(p, p.default))}
                  onClick={() => {
                    const next = set(p.default)
                    onChange(next)
                    onCommit?.(next)
                  }}
                  className="rounded px-1 text-[10px] text-ink-muted hover:bg-canvas hover:text-ink disabled:pointer-events-none disabled:opacity-30"
                >
                  {t.reset}
                </button>
              </span>
            </div>
            <Slider
              label={p.label_ko}
              value={v}
              min={p.min}
              max={p.max}
              step={paramStep(p)}
              onChange={(x) => onChange(set(x))}
              onCommit={onCommit ? (x) => onCommit(set(x)) : undefined}
            />
          </div>
        )
      })}
    </div>
  )
}

/** "전체 시트" or any number of panels (from the specification). */
export function SurfacePicker({
  panels,
  value,
  onChange,
}: {
  panels: Panel[]
  value: SurfaceChoice
  onChange: (next: SurfaceChoice) => void
}) {
  const toggle = (id: string) =>
    onChange({
      sheet: false,
      panels: value.panels.includes(id) ? value.panels.filter((x) => x !== id) : [...value.panels, id],
    })
  return (
    <div className="space-y-1 rounded-md border border-line p-2 text-xs">
      <label className="flex items-center gap-2 font-medium">
        <input
          type="checkbox"
          checked={value.sheet}
          onChange={(e) => onChange({ sheet: e.target.checked, panels: e.target.checked ? [] : value.panels })}
        />
        {t.sheet}
      </label>
      {panels.length === 0 ? (
        <p className="text-[11px] text-ink-muted">{t.noPanels}</p>
      ) : (
        <div className="grid grid-cols-2 gap-x-2 gap-y-1 border-t border-line pt-1.5">
          {panels.map((p) => (
            <label
              key={p.id}
              className={cn('flex min-w-0 items-center gap-2', value.sheet && 'text-ink-muted/60')}
              title={p.name}
            >
              <input
                type="checkbox"
                disabled={value.sheet}
                checked={!value.sheet && value.panels.includes(p.id)}
                onChange={() => toggle(p.id)}
              />
              <span className="truncate">{p.name}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
