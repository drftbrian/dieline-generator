import { useState } from 'react'
import {
  useCandidatePanels,
  useCandidates,
  useDeleteCandidate,
  useSaveFaces,
  useStartTypography,
  useUploadCandidate,
  versionLayerUrl,
} from '@/api/photoFirst'
import type { Point } from '@/api/scene'
import type { CandidateFace, Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'
import { QuadEditor } from './QuadEditor'
import { ImageDrop } from './ReferenceDrop'

const t = ko.studio.merge.photoFirst
const MAX_FACES = 3
const VIEWS = ['raw', 'strict', 'repair_preview'] as const

/** What the job reports per face (``VerifyOut.typography``). */
type TypographyFace = {
  face_id: string
  registration: { ok: boolean; confidence: number }
  items: Record<string, number>
  unexpected: number
  after: Record<string, { shading: { preserved: boolean } }>
}
type Typography = { status: 'ok' | 'review_required'; review: string[]; faces: TypographyFace[]; background?: { removed_fraction: number } | null }

/** A new face: a rectangle beside the others, to drag into place. */
function newFace(panel: string, n: number): CandidateFace {
  const x = Math.min(0.6, 0.2 + 0.2 * n)
  return { panel, quad: [[x, 0.25], [x + 0.2, 0.25], [x + 0.2, 0.8], [x, 0.8]] }
}

/** ③ AI 사진 글자 교정: an AI photo of our box, with Figma's own lettering put back. */
export function PhotoFirstCorrect({ projectId, shown }: { projectId: string; shown: Version | null }) {
  const candidates = useCandidates(projectId)
  const panels = useCandidatePanels(projectId)
  const upload = useUploadCandidate(projectId)
  const save = useSaveFaces(projectId)
  const remove = useDeleteCandidate(projectId)
  const start = useStartTypography(projectId)
  const [candId, setCandId] = useState<string | null>(null)
  const [draft, setDraft] = useState<{ id: string; faces: CandidateFace[] } | null>(null)

  const list = candidates.data ?? []
  const cand = list.find((c) => c.id === candId) ?? list[list.length - 1] ?? null
  const faces = draft && draft.id === cand?.id ? draft.faces : (cand?.faces ?? [])
  const choices = panels.data ?? []
  const nameOf = (id: string) => choices.find((p) => p.id === id)?.name ?? id
  const unused = choices.filter((p) => !faces.some((f) => f.panel === p.id))

  const commit = (next: CandidateFace[]) => {
    if (!cand) return
    setDraft({ id: cand.id, faces: next })
    save.mutate({ id: cand.id, faces: next })
  }
  const result = shown?.form === 'photo_first' ? shown : null
  const typography = (result?.verify?.typography ?? null) as Typography | null

  return (
    <div className="space-y-4 border-t border-line pt-4">
      <ImageDrop
        current={cand && { image_url: cand.image_url, filename: cand.filename }}
        pending={upload.isPending}
        error={upload.error ?? candidates.error}
        label={t.drop}
        onFile={(file) => upload.mutate(file, { onSuccess: (c) => setCandId(c.id) })}
      />

      {list.length > 1 && (
        <div>
          <p className="mb-1 text-xs text-ink-muted">{t.previous}</p>
          <div className="flex flex-wrap gap-1.5">
            {list.map((c) => (
              <button
                key={c.id}
                type="button"
                title={c.filename}
                onClick={() => setCandId(c.id)}
                className={cn(
                  'size-10 overflow-hidden rounded border',
                  c.id === cand?.id ? 'border-accent ring-2 ring-accent/30' : 'border-line',
                )}
              >
                <img src={c.thumb_url} alt={c.filename} className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}

      {cand && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium">{t.faces}</p>
            <button
              type="button"
              className="text-xs text-ink-muted hover:text-red-700"
              disabled={remove.isPending}
              onClick={() => remove.mutate(cand.id, { onSuccess: () => setCandId(null) })}
            >
              {t.remove}
            </button>
          </div>
          <QuadEditor
            imageUrl={cand.image_url}
            aspect={cand.width / Math.max(1, cand.height)}
            quads={faces.map((f, i) => ({ id: `${f.panel}-${i}`, label: nameOf(f.panel), quad: f.quad as Point[] }))}
            onChange={(quads, done) => {
              const next = faces.map((f, i) => ({ ...f, quad: (quads[i]?.quad ?? f.quad) as number[][] }))
              if (done) commit(next)
              else setDraft({ id: cand.id, faces: next })
            }}
          />
          <p className="text-[11px] text-ink-muted">{t.facesHint}</p>
          {faces.length === 0 && <p className="text-xs text-ink-muted">{t.noFaces}</p>}
          {faces.map((f, i) => (
            <div key={`${f.panel}-${i}`} className="flex items-center gap-2 text-xs">
              <Select
                label={t.panel}
                value={f.panel}
                className="min-w-0 flex-1"
                onChange={(panel) => commit(faces.map((x, j) => (j === i ? { ...x, panel } : x)))}
                options={choices
                  .filter((p) => p.id === f.panel || !faces.some((x) => x.panel === p.id))
                  .map((p) => ({ value: p.id, label: `${p.name} · ${Math.round(p.width_mm)}×${Math.round(p.height_mm)}mm` }))}
              />
              <button
                type="button"
                className="text-ink-muted hover:text-red-700"
                onClick={() => commit(faces.filter((_, j) => j !== i))}
              >
                {t.removeFace}
              </button>
            </div>
          ))}
          {faces.length < MAX_FACES && unused[0] && (
            <Button className="h-7 text-xs" onClick={() => commit([...faces, newFace(unused[0]!.id, faces.length)])}>
              {t.addFace}
            </Button>
          )}
          {save.error && <ErrorNotice error={save.error} />}

          <Button
            variant="primary"
            className="h-10 w-full justify-center"
            disabled={faces.length === 0 || start.isPending || save.isPending}
            onClick={() => start.mutate({ candidate_id: cand.id })}
          >
            {start.isPending ? (
              <>
                <Spinner className="size-3.5" /> {t.starting}
              </>
            ) : (
              t.run
            )}
          </Button>
          <p className="text-[11px] text-ink-muted">{t.runHint}</p>
          {start.error && <ErrorNotice error={start.error} />}
        </div>
      )}

      {result && typography && (
        <div
          className={cn(
            'space-y-1.5 rounded-md border p-3 text-xs',
            typography.status === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
              : 'border-amber-200 bg-amber-50 text-amber-900',
          )}
        >
          <p className="font-medium">
            {t.result} v{result.number} · {typography.status === 'ok' ? t.ok : t.review}
          </p>
          {typography.status !== 'ok' && <p>{t.reviewHint}</p>}
          {typography.faces.map((f) => {
            const n = (k: string) => f.items[k] ?? 0
            return (
              <div key={f.face_id} className="space-y-0.5">
                <p className="font-medium">
                  {f.registration.ok
                    ? t.face(nameOf(f.face_id), Math.round(f.registration.confidence * 100))
                    : t.faceFailed(nameOf(f.face_id))}
                </p>
                {f.registration.ok && (
                  <>
                    <p>{t.items(n('match'), n('approximate') + n('misplaced'), n('mismatch'), n('not_verifiable'), n('unresolved'))}</p>
                    {f.unexpected > 0 && <p>{t.unexpected(f.unexpected)}</p>}
                    <p>{t.shadow(f.after.text_corrected?.shading.preserved ?? false)}</p>
                  </>
                )}
              </div>
            )
          })}
          {(typography.background?.removed_fraction ?? 0) > 0 && <p>{t.background}</p>}
          <div className="pt-1">
            <p className="mb-1 font-medium">{t.views}</p>
            <div className="flex flex-wrap gap-2">
              {VIEWS.map((layer) => (
                <a
                  key={layer}
                  href={versionLayerUrl(projectId, result.id, layer)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline"
                >
                  {t.viewLabels[layer]}
                </a>
              ))}
            </div>
            <p className="mt-1 opacity-80">{t.viewHint}</p>
          </div>
          {typography.review.length > 0 && (
            <details>
              <summary className="cursor-pointer">{t.details}</summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {typography.review.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
