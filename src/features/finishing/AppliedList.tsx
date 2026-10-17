import { useState } from 'react'
import { assetLabel } from '@/api/assets'
import type { Asset, Finish, FinishCatalog, Panel } from '@/api/types'
import { IconButton } from '@/components/ui/controls'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { useAssetSelectionStore } from '@/stores/useAssetSelectionStore'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { useFinishingStore, type WorkingAssignment } from '@/stores/useFinishingStore'
import { ParamEditor, SurfacePicker } from './FinishControls'
import { assetTargets, defaultParams, surfaceOf, surfaceTargets } from './params'
import { Swatch } from './Swatch'

const t = ko.studio.finishing.assign
const fin = useFinishingStore.getState

type Ctx = {
  projectId: string
  catalog: FinishCatalog
  byId: Map<string, Asset>
  panels: Panel[]
  selected: string[]
}

function targetSummary(a: WorkingAssignment, { byId, panels }: Pick<Ctx, 'byId' | 'panels'>) {
  if (a.targets.some((x) => x.kind === 'sheet')) return t.sheet
  const panelNames = a.targets
    .filter((x) => x.kind === 'panel')
    .map((x) => panels.find((p) => p.id === x.id)?.name ?? t.unknownPanel)
  const assetNames = a.targets
    .filter((x) => x.kind === 'asset')
    .map((x) => {
      const asset = byId.get(x.id ?? '')
      return asset ? assetLabel(asset) : ko.studio.finishing.missing
    })
  return t.targetsAssets([...panelNames, ...assetNames])
}

/** G: the persistent list of applied finishes, in application order. */
export function AppliedList(ctx: Ctx) {
  const assignments = useFinishingStore((s) => s.assignments)
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-ink-muted">{t.applied(assignments.length)}</p>
      {assignments.length === 0 ? (
        <p className="rounded-md border border-dashed border-line p-3 text-xs text-ink-muted">{t.appliedEmpty}</p>
      ) : (
        <ol className="divide-y divide-line rounded-md border border-line">
          {assignments.map((a, i) => (
            <Row
              key={a.id}
              a={a}
              ctx={ctx}
              first={i === 0}
              last={i === assignments.length - 1}
              editing={editing === a.id}
              onEdit={(on) => setEditing(on ? a.id : null)}
            />
          ))}
        </ol>
      )}
    </div>
  )
}

function Row({
  a,
  ctx,
  first,
  last,
  editing,
  onEdit,
}: {
  a: WorkingAssignment
  ctx: Ctx
  first: boolean
  last: boolean
  editing: boolean
  onEdit: (on: boolean) => void
}) {
  const finish = ctx.catalog.finishes.find((f) => f.id === a.finish)
  const assetIds = a.targets.filter((x) => x.kind === 'asset' && x.id).map((x) => x.id as string)
  const onSurface = a.targets.some((x) => x.kind !== 'asset')
  const canRetarget = finish?.scope !== 'surface' && ctx.selected.length > 0
  const retargetTitle =
    finish?.scope === 'surface' ? t.retargetSurface : ctx.selected.length === 0 ? t.retargetNeedSelection : t.retarget

  const selectTargets = () => {
    const s = useAssetSelectionStore.getState()
    s.selectMany(ctx.projectId, assetIds)
    if (!s.selecting) s.setSelecting(true)
    useCanvasStore.getState().setView('flat')
  }

  return (
    <li className={cn('text-xs', !a.enabled && 'bg-canvas/50')}>
      <div className="flex items-center gap-2 px-2 py-1.5">
        {finish ? <Swatch finish={finish} size={22} className={cn(!a.enabled && 'opacity-40')} /> : <span className="size-[22px]" />}
        <div className={cn('min-w-0 flex-1', !a.enabled && 'text-ink-muted')}>
          <p className="truncate font-medium">
            {finish?.label_ko ?? t.unknownFinish}
            {!a.enabled && <span className="ml-1 text-[10px] font-normal">· {t.hidden}</span>}
          </p>
          <p className="truncate text-[11px] text-ink-muted" title={targetSummary(a, ctx)}>
            {targetSummary(a, ctx)}
          </p>
        </div>
        <IconButton
          label={a.enabled ? t.hide : t.show}
          active={!a.enabled}
          className="size-6 text-xs"
          onClick={() => fin().update(a.id, { enabled: !a.enabled })}
        >
          {a.enabled ? '◉' : '○'}
        </IconButton>
        <IconButton
          label={editing ? t.editDone : t.edit}
          active={editing}
          className="size-6 text-xs"
          disabled={!finish}
          onClick={() => onEdit(!editing)}
        >
          ✎
        </IconButton>
        <IconButton label={t.removeAssignment} className="size-6 text-xs" onClick={() => fin().remove(a.id)}>
          ×
        </IconButton>
      </div>
      <div className="flex flex-wrap items-center gap-1 px-2 pb-1.5 pl-[38px]">
        <SmallAction disabled={!canRetarget} title={retargetTitle} onClick={() => fin().update(a.id, { targets: assetTargets(ctx.selected) })}>
          {t.retarget}
        </SmallAction>
        <SmallAction
          disabled={assetIds.length === 0}
          title={assetIds.length === 0 ? t.selectTargetsNone : t.selectTargets}
          onClick={selectTargets}
        >
          {t.selectTargets}
        </SmallAction>
        <span className="ml-auto flex">
          <IconButton label={t.moveUp} className="size-6 text-xs" disabled={first} onClick={() => fin().move(a.id, -1)}>
            ↑
          </IconButton>
          <IconButton label={t.moveDown} className="size-6 text-xs" disabled={last} onClick={() => fin().move(a.id, 1)}>
            ↓
          </IconButton>
        </span>
      </div>
      {editing && finish && <EditPanel a={a} finish={finish} panels={ctx.panels} surface={onSurface} />}
    </li>
  )
}

function SmallAction(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className="rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-muted hover:bg-canvas hover:text-ink disabled:pointer-events-none disabled:opacity-40"
    />
  )
}

/** Inline parameter (and surface target) editing; each commit is one undo step. */
function EditPanel({
  a,
  finish,
  panels,
  surface,
}: {
  a: WorkingAssignment
  finish: Finish
  panels: Panel[]
  surface: boolean
}) {
  const committed = { ...defaultParams(finish), ...a.params }
  // While dragging, the slider shows a draft; it falls back to the store after each commit.
  const [draft, setDraft] = useState<Record<string, number> | null>(null)
  return (
    <div className="space-y-2.5 border-t border-line bg-canvas/60 px-2.5 py-2.5">
      <ParamEditor
        finish={finish}
        values={draft ?? committed}
        onChange={setDraft}
        onCommit={(next) => {
          setDraft(null)
          if (finish.params.some((p) => next[p.id] !== committed[p.id])) fin().update(a.id, { params: next })
        }}
      />
      {surface && finish.scope !== 'selective' && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-ink-muted">{t.target}</p>
          <SurfacePicker
            panels={panels}
            value={surfaceOf(a.targets)}
            onChange={(c) => {
              const targets = surfaceTargets(c)
              if (targets.length > 0) fin().update(a.id, { targets })
            }}
          />
        </div>
      )}
    </div>
  )
}
