import { useEffect, useMemo, useState } from 'react'
import { assetLabel, useAssets } from '@/api/assets'
import { useSpecification } from '@/api/spec'
import type { Asset } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useAssetSelectionStore, useSelectedAssets } from '@/stores/useAssetSelectionStore'
import { FinishingAssign } from './FinishingAssign'
import { SELECT_COLOR } from './geometry'

const t = ko.studio.finishing

const sel = useAssetSelectionStore.getState

/** Click in a list: select (Shift: add/remove) and switch the canvas into selection mode. */
function pick(projectId: string, id: string, e: React.MouseEvent) {
  const s = sel()
  if (e.shiftKey) s.toggle(projectId, id)
  else s.select(projectId, id)
  s.setCycle(projectId, undefined)
  if (!s.selecting) s.setSelecting(true)
}

/**
 * ② 후가공 / Finishing: which logos / texts get a finish (Milestone 2), and which finish goes
 * on them, the sheet or panels (Milestone 3).
 */
export function FinishingSection({ projectId, hasFrame }: { projectId: string; hasFrame: boolean }) {
  const assets = useAssets(projectId, hasFrame)
  const selected = useSelectedAssets(projectId)
  const selecting = useAssetSelectionStore((s) => s.selecting)
  const byId = useMemo(() => new Map((assets.data?.assets ?? []).map((a) => [a.id, a])), [assets.data])

  // Forget selections of assets that are gone (structure re-confirmed, Figma changed).
  useEffect(() => {
    if (!assets.data) return
    sel().prune(projectId, new Set(assets.data.assets.filter((a) => a.selectable).map((a) => a.id)))
  }, [assets.data, projectId])

  const pdf = assets.data?.source === 'pdf'
  const approximate = pdf || selected.some((id) => byId.get(id)?.exact === false)
  const panels = useSpecification(projectId).data?.panels ?? NO_PANELS
  const targetable = useMemo(() => selected.filter((id) => byId.get(id)?.selectable), [selected, byId])

  return (
    <section className="space-y-3 border-t border-line pt-4">
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold">{t.title}</h3>
          <p className="text-xs text-ink-muted">{t.intro}</p>
        </div>
        <Button
          variant={selecting ? 'primary' : 'secondary'}
          aria-pressed={selecting}
          disabled={!hasFrame || !!assets.error}
          title={t.modeTitle}
          onClick={() => sel().setSelecting(!selecting)}
          className="h-7 shrink-0 px-2.5 text-xs"
        >
          {t.modeOn}
        </Button>
      </div>

      {!hasFrame ? (
        <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-800">{t.noFrame}</p>
      ) : assets.error ? (
        <ErrorNotice error={assets.error} />
      ) : !assets.data ? (
        <p className="flex items-center gap-1.5 text-xs text-ink-muted">
          <Spinner className="size-3" /> {t.loading}
        </p>
      ) : (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-ink-muted">{t.selected(selected.length)}</p>
              {selected.length > 0 && (
                <button
                  type="button"
                  className="text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline"
                  onClick={() => sel().clear(projectId)}
                >
                  {t.clearAll}
                </button>
              )}
            </div>
            {selected.length === 0 ? (
              <p className="rounded-md border border-dashed border-line p-3 text-xs text-ink-muted">{t.empty}</p>
            ) : (
              <ul className="divide-y divide-line rounded-md border border-line">
                {selected.map((id) => (
                  <SelectedRow key={id} projectId={projectId} id={id} asset={byId.get(id)} />
                ))}
              </ul>
            )}
            {selected.length > 0 && <p className="text-[11px] text-ink-muted">{t.cycleHint}</p>}
          </div>

          {approximate && <p className="rounded-md bg-amber-50 p-2.5 text-xs text-amber-800">{t.approximate}</p>}

          <LayerTree projectId={projectId} assets={assets.data.assets} byId={byId} selected={selected} />
        </>
      )}

      <FinishingAssign projectId={projectId} selected={targetable} byId={byId} panels={panels} />
    </section>
  )
}

const NO_PANELS: never[] = []

function Dot({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="size-2.5 shrink-0 rounded-full border-2"
      style={{ backgroundColor: color, borderColor: `#${SELECT_COLOR}` }}
    />
  )
}

function SelectedRow({ projectId, id, asset }: { projectId: string; id: string; asset: Asset | undefined }) {
  const color = asset?.color ? (asset.color.startsWith('#') ? asset.color : `#${asset.color}`) : `#${SELECT_COLOR}`
  return (
    <li
      className="flex items-center gap-2 px-2.5 py-1.5 text-xs"
      onMouseEnter={() => sel().setHover(projectId, id)}
      onMouseLeave={() => sel().setHover(projectId, null)}
    >
      <Dot color={color} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium" title={asset ? assetLabel(asset) : id}>
          {asset ? assetLabel(asset) : t.missing}
        </p>
        {asset && (
          <p className="truncate text-[11px] text-ink-muted">
            {t.kinds[asset.kind] ?? asset.kind} · {asset.panel ?? t.noPanel}
            {!asset.exact && ` · ${t.approximateItem}`}
          </p>
        )}
      </div>
      <button
        type="button"
        aria-label={t.remove}
        title={t.remove}
        className="inline-flex size-6 shrink-0 items-center justify-center rounded text-ink-muted hover:bg-canvas hover:text-ink"
        onClick={() => sel().remove(projectId, id)}
      >
        ×
      </button>
    </li>
  )
}

/** Collapsible layer tree: the alternative to cycling when elements overlap on the canvas. */
function LayerTree({
  projectId,
  assets,
  byId,
  selected,
}: {
  projectId: string
  assets: Asset[]
  byId: Map<string, Asset>
  selected: string[]
}) {
  const [open, setOpen] = useState(false)
  const roots = useMemo(() => assets.filter((a) => !a.parent || !byId.has(a.parent)), [assets, byId])
  const chosen = useMemo(() => new Set(selected), [selected])
  return (
    <div className="rounded-md border border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left text-xs font-medium hover:bg-canvas/60"
      >
        <span aria-hidden className={cn('inline-block w-3 transition-transform', open && 'rotate-90')}>
          ▸
        </span>
        {t.layers(assets.length)}
      </button>
      {open && (
        <div className="border-t border-line p-1.5">
          <p className="px-1 pb-1.5 text-[11px] text-ink-muted">{t.layersHint}</p>
          <ul className="max-h-72 overflow-y-auto" role="tree">
            {roots.map((a) => (
              <LayerNode key={a.id} projectId={projectId} asset={a} byId={byId} chosen={chosen} level={0} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function LayerNode({
  projectId,
  asset,
  byId,
  chosen,
  level,
}: {
  projectId: string
  asset: Asset
  byId: Map<string, Asset>
  chosen: Set<string>
  level: number
}) {
  const children = asset.children.map((id) => byId.get(id)).filter((a): a is Asset => !!a)
  const on = chosen.has(asset.id)
  const usable = asset.selectable && !asset.technical
  return (
    <li role="treeitem" aria-selected={on}>
      <button
        type="button"
        disabled={!usable}
        title={asset.technical ? t.technical : !asset.selectable ? t.notSelectable : assetLabel(asset)}
        onClick={(e) => pick(projectId, asset.id, e)}
        onMouseEnter={() => usable && sel().setHover(projectId, asset.id)}
        onMouseLeave={() => sel().setHover(projectId, null)}
        className={cn(
          'flex w-full items-center gap-1.5 rounded py-1 pr-1.5 text-left text-xs',
          usable ? 'hover:bg-canvas' : 'cursor-not-allowed text-ink-muted/60',
          on && 'bg-orange-50 font-medium text-orange-900 hover:bg-orange-100',
        )}
        style={{ paddingLeft: 6 + level * 12 }}
      >
        <span className="w-9 shrink-0 text-[10px] text-ink-muted">{t.kinds[asset.kind] ?? asset.kind}</span>
        <span className={cn('min-w-0 flex-1 truncate', asset.technical && 'line-through')}>{assetLabel(asset)}</span>
      </button>
      {children.length > 0 && (
        <ul role="group">
          {children.map((c) => (
            <LayerNode key={c.id} projectId={projectId} asset={c} byId={byId} chosen={chosen} level={level + 1} />
          ))}
        </ul>
      )}
    </li>
  )
}
