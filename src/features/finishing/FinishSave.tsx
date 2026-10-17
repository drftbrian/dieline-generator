import { useState } from 'react'
import { useStartFinish } from '@/api/generate'
import { Button } from '@/components/ui/Button'
import { Slider } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { useShownVersion } from '@/features/studio/useShownVersion'
import { isFinishSource } from '@/features/studio/versions'
import { ko } from '@/i18n/ko'
import { useCanvasStore } from '@/stores/useCanvasStore'
import { isDirty, useFinishingStore } from '@/stores/useFinishingStore'

const t = ko.studio.finishing.assign.save

/** 후가공 버전으로 저장: bake the saved finishes into a new flat version (optionally AI 사실감). */
export function FinishSave({ projectId }: { projectId: string }) {
  const version = useShownVersion(projectId)
  const start = useStartFinish(projectId)
  const [strength, setStrength] = useState(70)
  const [started, setStarted] = useState(false)
  const revision = useFinishingStore((s) => (s.projectId === projectId ? s.saved.revision : 0))
  const hasFinishes = useFinishingStore((s) => s.projectId === projectId && s.saved.assignments.some((a) => a.enabled))
  const pending = useFinishingStore((s) => s.projectId === projectId && (s.status === 'saving' || isDirty(s)))
  if (!hasFinishes) return null

  const blocked = !version ? t.noVersion : !isFinishSource(version) ? t.notSource : pending ? t.unsaved : null
  const run = (ai: boolean) => {
    if (!version || blocked) return
    setStarted(false)
    start.mutate(
      { sourceId: version.id, revision, ai, strength: strength / 100 },
      {
        onSuccess: () => {
          setStarted(true)
          useCanvasStore.getState().setView('flat')
        },
      },
    )
  }

  return (
    <section className="space-y-2 rounded-md border border-line p-2.5">
      <h5 className="text-xs font-semibold">{t.title}</h5>
      <p className="text-[11px] text-ink-muted">{t.body}</p>
      <Button
        variant="secondary"
        className="h-8 w-full justify-center text-xs"
        disabled={!!blocked || start.isPending}
        onClick={() => run(false)}
      >
        {t.plain}
      </Button>
      <div className="space-y-1.5 rounded-md bg-violet-50/60 p-2">
        <p className="text-[11px] text-violet-900">{t.aiNote}</p>
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-[11px] text-ink-muted">{t.strength}</span>
          <Slider value={strength} onChange={setStrength} label={t.strength} disabled={!!blocked} />
          <span className="w-8 shrink-0 text-right text-[11px] tabular-nums">{strength}%</span>
        </div>
        <Button
          variant="primary"
          className="h-8 w-full justify-center text-xs"
          disabled={!!blocked || start.isPending}
          onClick={() => run(true)}
        >
          {t.ai}
        </Button>
      </div>
      {blocked && <p className="text-[11px] text-ink-muted">{blocked}</p>}
      {start.error && <ErrorNotice error={start.error} />}
      {started && !start.error && <p className="text-[11px] text-emerald-700">{t.started}</p>}
    </section>
  )
}
