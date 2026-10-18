import { useState } from 'react'
import { useStartMerge } from '@/api/generate'
import { useDeleteReference, useReferences } from '@/api/references'
import type { MergeForm, Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { SegmentedControl, Select } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { JobStages, StepPanel, VerifyResult, VersionError } from '@/features/studio/StepPanel'
import type { StudioRegionProps } from '@/features/studio/types'
import { pick, useVersions } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { ReferenceDrop } from './ReferenceDrop'
import { ReferenceReading } from './ReferenceReading'
import { PhotoFirstCorrect } from './PhotoFirstCorrect'
import { StructuralCompose } from './StructuralCompose'

const t = ko.studio.merge
const MODES = ['structural', 'photo_first', 'legacy'] as const
type Mode = (typeof MODES)[number]

/** Which mode made a merge version (its errors show only in that mode). */
const modeOf = (form: Version['form']): Mode =>
  form === 'structural' ? 'structural' : form === 'photo_first' ? 'photo_first' : 'legacy'

/** ③ 레퍼런스 합성: our approved flat render in place of the packaging in one reference photo. */
export function MergePanel({ project }: StudioRegionProps) {
  const pid = project.id
  const refs = useReferences(pid)
  const removeRef = useDeleteReference(pid)
  const start = useStartMerge(pid)
  const { versions, merges, mergeSources } = useVersions(pid)
  const mergeId = useCanvasStore((s) => s.mergeId)
  const mergeSourceId = useCanvasStore((s) => s.mergeSourceId)
  const setMergeSource = useCanvasStore((s) => s.setMergeSource)
  const [refId, setRefId] = useState<string | null>(null)
  const [form, setForm] = useState<MergeForm>('auto')
  const [mode, setMode] = useState<Mode>('structural')

  const list = refs.data ?? []
  const reference = list.find((r) => r.id === refId) ?? list[list.length - 1] ?? null
  const flat = pick(mergeSources, mergeSourceId)
  const shown = pick(merges, mergeId)
  const all = versions.filter((v) => v.kind === 'merge')
  const running = all.filter((v) => v.status === 'running')
  const last = all[all.length - 1]
  const readingDone = reference?.analysis_status === 'done' && !!reference.analysis
  const blocked = !reference ? t.needReference : !readingDone ? t.needReading : !flat ? t.noFlatSource : null

  const submit = () => {
    if (!reference || !flat) return
    start.mutate({ reference_id: reference.id, flat_version_id: flat.id, form })
  }

  return (
    <StepPanel title={t.title} intro={t.intro}>
      <div className="space-y-1.5">
        <p className="text-xs font-medium">{t.mode}</p>
        <SegmentedControl<Mode>
          label={t.mode}
          value={mode}
          onChange={setMode}
          options={MODES.map((value) => ({ value, label: t.modes[value] }))}
        />
        <p className="text-xs text-ink-muted">{t.modeHint[mode]}</p>
      </div>

      {mode === 'photo_first' && <PhotoFirstCorrect projectId={pid} shown={shown} />}

      {mode !== 'photo_first' && (
        <>
      <ReferenceDrop projectId={pid} current={reference} onUploaded={(r) => setRefId(r.id)} />
      {refs.error && <ErrorNotice error={refs.error} />}

      {list.length > 1 && (
        <div>
          <p className="mb-1 text-xs text-ink-muted">{t.previous}</p>
          <div className="flex flex-wrap gap-1.5">
            {list.map((r) => (
              <button
                key={r.id}
                type="button"
                title={r.filename}
                onClick={() => setRefId(r.id)}
                className={cn(
                  'size-10 overflow-hidden rounded border',
                  r.id === reference?.id ? 'border-accent ring-2 ring-accent/30' : 'border-line',
                )}
              >
                <img src={r.thumb_url} alt={r.filename} className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}

      {reference && (
        <>
          <ReferenceReading projectId={pid} reference={reference} />
          <button
            type="button"
            className="self-start text-xs text-ink-muted hover:text-red-700"
            disabled={removeRef.isPending}
            onClick={() => removeRef.mutate(reference.id, { onSuccess: () => setRefId(null) })}
          >
            {t.remove}
          </button>
        </>
      )}

      {mode === 'legacy' && (
        <div className="space-y-1.5 border-t border-line pt-4">
          <p className="text-xs font-medium">{t.form}</p>
          <SegmentedControl<MergeForm>
            label={t.form}
            value={form}
            onChange={setForm}
            options={(['auto', 'flat', 'folded'] as const).map((value) => ({ value, label: t.formOptions[value] }))}
          />
          <p className="text-xs text-ink-muted">{t.formHint[form]}</p>
        </div>
      )}

      <div className="space-y-1.5">
        <p className="text-xs font-medium">{t.flatSource}</p>
        {flat ? (
          <div className="flex items-center gap-2">
            {flat.thumb_url && <img src={flat.thumb_url} alt="" className="size-10 shrink-0 rounded border border-line bg-black object-cover" />}
            <Select
              label={t.flatSource}
              value={flat.id}
              onChange={setMergeSource}
              className="min-w-0 flex-1"
              options={[...mergeSources].reverse().map((v) => ({ value: v.id, label: `v${v.number} · ${formatDateTime(v.created_at)}` }))}
            />
          </div>
        ) : (
          <div className="space-y-1.5 text-xs text-ink-muted">
            <p>{t.noFlatSource}</p>
            <Button className="h-7 text-xs" onClick={() => useCanvasStore.getState().setView('flat')}>
              {t.toFlat}
            </Button>
          </div>
        )}
      </div>

      {mode === 'structural' && <StructuralCompose projectId={pid} reference={reference} flat={flat} />}

      {mode === 'legacy' && (
        <div className="space-y-1.5">
          <Button variant="primary" className="h-10 w-full justify-center" disabled={!!blocked || start.isPending} onClick={submit}>
            {start.isPending ? (
              <>
                <Spinner className="size-3.5" /> {t.starting}
              </>
            ) : (
              t.generate
            )}
          </Button>
          {blocked && <p className="text-xs text-ink-muted">{blocked}</p>}
          {start.error && <ErrorNotice error={start.error} />}
        </div>
      )}

        </>
      )}

      {running.map((v) => (
        <JobStages key={v.id} version={v} />
      ))}
      {last?.status === 'failed' && modeOf(last.form) === mode && <VersionError version={last} />}
      {shown && !shown.legacy && shown.form !== 'photo_first' && mode !== 'photo_first' && (
        <VerifyResult verify={shown.verify} />
      )}
    </StepPanel>
  )
}
