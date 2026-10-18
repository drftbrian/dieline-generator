import { useLayoutEffect, useRef, useState } from 'react'
import {
  type ComposeLayer,
  type ComposeReport,
  type Point,
  type Scene,
  type SceneInstance,
  fetchComposePreview,
  useDetectScene,
  useSaveScene,
  useScene,
  useStartCompose,
  useStructure,
} from '@/api/scene'
import type { Reference, Version } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { SegmentedControl, Slider } from '@/components/ui/controls'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Spinner } from '@/components/ui/Spinner'
import { useObjectUrl } from '@/features/finishing/useObjectUrl'
import { ko } from '@/i18n/ko'
import { cn } from '@/lib/cn'

const t = ko.studio.merge.structural
const LAYERS: ComposeLayer[] = ['final', 'placement', 'removal_mask', 'background', 'lighting', 'albedo']

/** The hidden corner of a quad, shown where the parallelogram puts it (the server computes the
 *  exact one in 3D from the ground plane). */
function displayQuad(q: (Point | null)[]): Point[] {
  const k = q.findIndex((c) => c === null)
  if (k < 0) return q as Point[]
  const a = q[(k + 1) % 4] as Point
  const b = q[(k + 2) % 4] as Point
  const c = q[(k + 3) % 4] as Point
  const out = [...q] as Point[]
  out[k] = [a[0] + c[0] - b[0], a[1] + c[1] - b[1]]
  return out
}

function newInstance(n: number): SceneInstance {
  return {
    id: `inst${n}`,
    quad: [
      [0.35, 0.35],
      [0.65, 0.35],
      [0.65, 0.6],
      [0.35, 0.6],
    ],
    height: 0.2,
    enabled: true,
    yaw_deg: 0,
    offset: [0, 0],
  }
}

/** Drag the corners of each package's face on the reference. */
function QuadEditor({
  imageUrl,
  aspect,
  instances,
  onChange,
}: {
  imageUrl: string
  aspect: number
  instances: SceneInstance[]
  onChange: (list: SceneInstance[], commit: boolean) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ i: number; c: number } | null>(null)
  const listRef = useRef(instances)
  useLayoutEffect(() => {
    listRef.current = instances
  })
  const move = (e: React.PointerEvent, commit: boolean) => {
    const d = drag.current
    const el = box.current
    if (!d || !el) return
    const r = el.getBoundingClientRect()
    const p: Point = [
      Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    ]
    const list = listRef.current.map((inst, i) =>
      i === d.i ? { ...inst, quad: inst.quad.map((c, j) => (j === d.c ? p : c)) } : inst,
    )
    onChange(list, commit)
  }
  return (
    <div
      ref={box}
      className="relative w-full touch-none overflow-hidden rounded border border-line"
      style={{ aspectRatio: String(aspect) }}
      onPointerMove={(e) => move(e, false)}
      onPointerUp={(e) => {
        move(e, true)
        drag.current = null
      }}
    >
      <img src={imageUrl} alt="" className="absolute inset-0 h-full w-full object-fill" draggable={false} />
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {instances.map((inst, i) => {
          const q = displayQuad(inst.quad)
          return (
            <g key={inst.id} opacity={inst.enabled ? 1 : 0.35}>
              <polygon
                points={q.map((p) => p.join(',')).join(' ')}
                fill="rgba(229,51,63,0.12)"
                stroke="#e5333f"
                strokeWidth={0.004}
              />
              <text x={q[0]?.[0] ?? 0} y={(q[0]?.[1] ?? 0) - 0.01} fontSize={0.035} fill="#e5333f">
                {i + 1}
              </text>
            </g>
          )
        })}
      </svg>
      {instances.map((inst, i) =>
        displayQuad(inst.quad).map((p, c) => (
          <button
            key={`${inst.id}-${c}`}
            type="button"
            aria-label={`${t.instance(i + 1)} ${c + 1}`}
            onPointerDown={(e) => {
              ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
              drag.current = { i, c }
            }}
            className={cn(
              'absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow',
              inst.quad[c] === null ? 'bg-white/70 outline-dashed outline-1 outline-red-600' : 'bg-red-600',
            )}
            style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%` }}
          />
        )),
      )}
    </div>
  )
}

/** ③ 구조 합성: our folded carton in place of every package of the reference. */
export function StructuralCompose({
  projectId,
  reference,
  flat,
}: {
  projectId: string
  reference: Reference | null
  flat: Version | null
}) {
  const structure = useStructure(projectId)
  const scene = useScene(projectId, reference?.id ?? null)
  const save = useSaveScene(projectId, reference?.id ?? null)
  const detect = useDetectScene(projectId, reference?.id ?? null)
  const start = useStartCompose(projectId)
  // The working copy while editing, for the reference it was made on (a saved scene replaces it).
  const [draftOf, setDraftOf] = useState<{ ref: string; scene: Scene } | null>(null)
  const [layer, setLayer] = useState<ComposeLayer>('final')
  const [preview, setPreview] = useState<{ key: string; blob: Blob; report: ComposeReport } | null>(null)
  const [previewError, setPreviewError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [strength, setStrength] = useState(0.7)
  const previewKey = `${reference?.id}:${flat?.id}`
  const shownPreview = preview?.key === previewKey ? preview : null
  const url = useObjectUrl(shownPreview?.blob ?? null)
  const setDraft = (next: Scene) => reference && setDraftOf({ ref: reference.id, scene: next })

  const current = (draftOf?.ref === reference?.id ? draftOf?.scene : null) ?? scene.data ?? null
  const instances = current?.instances ?? []
  const settings = current?.settings ?? {}
  const commit = (next: Scene) => {
    setDraft(next)
    save.mutate({ instances: next.instances, settings: next.settings })
  }
  const update = (list: SceneInstance[], persist: boolean) => {
    const next = {
      ...(current ?? { source: 'user', settings: {} }),
      instances: list,
    } as Scene
    if (persist) commit(next)
    else setDraft(next)
  }
  const setSetting = (patch: Partial<Scene['settings']>, persist = true) => {
    const next = {
      ...(current ?? { source: 'user', instances: [] }),
      settings: { ...settings, ...patch },
    } as Scene
    if (persist) commit(next)
    else setDraft(next)
  }

  const runPreview = async (which: ComposeLayer = layer) => {
    if (!reference || !flat) return
    setBusy(true)
    setPreviewError(null)
    try {
      setPreview({ key: previewKey, ...(await fetchComposePreview(projectId, reference.id, flat.id, which)) })
    } catch (e) {
      setPreviewError(e)
    } finally {
      setBusy(false)
    }
  }

  const info = structure.data?.carton
  const supported = !!info?.supported && structure.data?.ok
  const active = instances.filter((i) => i.enabled).length
  const blocked = !reference || !flat ? null : !supported ? t.unsupported : !active ? t.needScene : null
  const manualLight = settings.key_azimuth != null

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="text-xs font-medium">{t.structure}</p>
        {structure.isPending ? (
          <Spinner className="size-3.5" />
        ) : supported && info?.body ? (
          <p className="text-xs text-ink-muted">
            {t.structureOk(
              t.styles[info.style ?? ''] ?? info.style ?? '',
              info.body.W_mm,
              info.body.D_mm,
              info.body.H_mm,
            )}
          </p>
        ) : (
          <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-800" role="alert">
            <p className="font-medium">{t.unsupported}</p>
            <ul className="list-disc pl-4">
              {(info?.reasons ?? structure.data?.issues.map((i) => i.message) ?? []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {reference && (
        <div className="space-y-2 border-t border-line pt-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium">{t.instances}</p>
            <Button className="h-7 text-xs" disabled={detect.isPending} onClick={() => detect.mutate()}>
              {detect.isPending ? (
                <>
                  <Spinner className="size-3" /> {t.detecting}
                </>
              ) : (
                t.detect
              )}
            </Button>
          </div>
          <p className="text-[11px] text-ink-muted">{t.detectHint}</p>
          {detect.error && <ErrorNotice error={detect.error} />}
          <QuadEditor
            imageUrl={reference.image_url}
            aspect={reference.width / Math.max(1, reference.height)}
            instances={instances}
            onChange={update}
          />
          <p className="text-[11px] text-ink-muted">{t.editorHint}</p>
          {instances.length === 0 && <p className="text-xs text-ink-muted">{t.none}</p>}
          {instances.map((inst, i) => {
            const set = (patch: Partial<SceneInstance>, persist = true) =>
              update(
                instances.map((x, j) => (j === i ? { ...x, ...patch } : x)),
                persist,
              )
            return (
              <div key={inst.id} className="space-y-1.5 rounded-md border border-line p-2">
                <div className="flex items-center gap-2 text-xs">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={inst.enabled}
                      onChange={(e) => set({ enabled: e.target.checked })}
                    />
                    <span className="font-medium">{t.instance(i + 1)}</span>
                  </label>
                  {inst.confidence != null && (
                    <span className="text-ink-muted">{t.confidence(Math.round(inst.confidence * 100))}</span>
                  )}
                  <button
                    type="button"
                    className="ml-auto text-ink-muted hover:text-red-700"
                    onClick={() =>
                      update(
                        instances.filter((_, j) => j !== i),
                        true,
                      )
                    }
                  >
                    {t.removeInstance}
                  </button>
                </div>
                <Row label={`${t.rotate} ${Math.round(inst.yaw_deg)}°`}>
                  <Slider
                    label={t.rotate}
                    min={-180}
                    max={180}
                    step={1}
                    value={inst.yaw_deg}
                    onChange={(v) => set({ yaw_deg: v }, false)}
                    onCommit={(v) => set({ yaw_deg: v })}
                  />
                </Row>
                <Row label={t.offsetLong}>
                  <Slider
                    label={t.offsetLong}
                    min={-0.5}
                    max={0.5}
                    step={0.01}
                    value={inst.offset[0]}
                    onChange={(v) => set({ offset: [v, inst.offset[1]] }, false)}
                    onCommit={(v) => set({ offset: [v, inst.offset[1]] })}
                  />
                </Row>
                <Row label={t.offsetShort}>
                  <Slider
                    label={t.offsetShort}
                    min={-0.5}
                    max={0.5}
                    step={0.01}
                    value={inst.offset[1]}
                    onChange={(v) => set({ offset: [inst.offset[0], v] }, false)}
                    onCommit={(v) => set({ offset: [inst.offset[0], v] })}
                  />
                </Row>
                <Row label={`${t.height} ${inst.height.toFixed(2)}`}>
                  <Slider
                    label={t.height}
                    min={0.03}
                    max={1}
                    step={0.01}
                    value={inst.height}
                    onChange={(v) => set({ height: v }, false)}
                    onCommit={(v) => set({ height: v })}
                  />
                </Row>
              </div>
            )
          })}
          <Button
            className="h-7 text-xs"
            onClick={() => update([...instances, newInstance(instances.length + 1)], true)}
          >
            {t.add}
          </Button>
        </div>
      )}

      {reference && (
        <div className="space-y-2 border-t border-line pt-4">
          <Row label={`${t.size} ${(settings.size ?? 1).toFixed(2)}`}>
            <Slider
              label={t.size}
              min={0.3}
              max={2}
              step={0.01}
              value={settings.size ?? 1}
              onChange={(v) => setSetting({ size: v }, false)}
              onCommit={(v) => setSetting({ size: v })}
            />
          </Row>
          <Row label={`${t.shadow} ${Math.round((settings.shadow_strength ?? 1) * 100)}%`}>
            <Slider
              label={t.shadow}
              min={0}
              max={1}
              step={0.05}
              value={settings.shadow_strength ?? 1}
              onChange={(v) => setSetting({ shadow_strength: v }, false)}
              onCommit={(v) => setSetting({ shadow_strength: v })}
            />
          </Row>
          <p className="text-xs font-medium">{t.light}</p>
          <SegmentedControl<'auto' | 'manual'>
            label={t.light}
            value={manualLight ? 'manual' : 'auto'}
            onChange={(v) =>
              setSetting(
                v === 'auto' ? { key_azimuth: null, key_elevation: null } : { key_azimuth: 45, key_elevation: 35 },
              )
            }
            options={[
              { value: 'auto', label: t.lightAuto },
              { value: 'manual', label: t.lightManual },
            ]}
          />
          {manualLight && (
            <>
              <Row label={`${t.azimuth} ${settings.key_azimuth}°`}>
                <Slider
                  label={t.azimuth}
                  min={0}
                  max={359}
                  step={1}
                  value={settings.key_azimuth ?? 45}
                  onChange={(v) => setSetting({ key_azimuth: v }, false)}
                  onCommit={(v) => setSetting({ key_azimuth: v })}
                />
              </Row>
              <Row label={`${t.elevation} ${settings.key_elevation}°`}>
                <Slider
                  label={t.elevation}
                  min={5}
                  max={85}
                  step={1}
                  value={settings.key_elevation ?? 35}
                  onChange={(v) => setSetting({ key_elevation: v }, false)}
                  onCommit={(v) => setSetting({ key_elevation: v })}
                />
              </Row>
            </>
          )}
        </div>
      )}

      <div className="space-y-2 border-t border-line pt-4">
        <div className="flex flex-wrap gap-1">
          {LAYERS.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => {
                setLayer(l)
                void runPreview(l)
              }}
              className={cn(
                'rounded border px-1.5 py-0.5 text-[11px]',
                l === layer ? 'border-accent bg-accent/10' : 'border-line text-ink-muted',
              )}
            >
              {t.layers[l]}
            </button>
          ))}
        </div>
        <Button
          className="h-8 w-full justify-center text-xs"
          disabled={!!blocked || busy || !reference || !flat}
          onClick={() => void runPreview()}
        >
          {busy ? (
            <>
              <Spinner className="size-3" /> {t.previewing}
            </>
          ) : (
            t.preview
          )}
        </Button>
        {previewError != null && <ErrorNotice error={previewError} />}
        {url && (
          <a href={url} target="_blank" rel="noreferrer">
            <img src={url} alt="" className="w-full rounded border border-line" />
          </a>
        )}
        {shownPreview?.report.light && (
          <p className="text-[11px] text-ink-muted">
            {t.report(
              shownPreview.report.lens_mm_35eq ?? 0,
              Math.round(shownPreview.report.light.azimuth),
              Math.round(shownPreview.report.light.elevation),
              t.lightSources[shownPreview.report.light.estimated?.azimuth_source ?? ''] ?? t.lightManual,
            )}
          </p>
        )}
      </div>

      <div className="space-y-2 border-t border-line pt-4">
        <Button
          variant="primary"
          className="h-10 w-full justify-center"
          disabled={!!blocked || !reference || !flat || start.isPending}
          onClick={() =>
            reference &&
            flat &&
            start.mutate({
              reference_id: reference.id,
              flat_version_id: flat.id,
              harmonize: false,
              strength,
            })
          }
        >
          {t.save}
        </Button>
        <Row label={`${t.strength} ${Math.round(strength * 100)}%`}>
          <Slider label={t.strength} min={0} max={1} step={0.05} value={strength} onChange={setStrength} />
        </Row>
        <Button
          className="h-9 w-full justify-center"
          disabled={!!blocked || !reference || !flat || start.isPending}
          onClick={() =>
            reference &&
            flat &&
            start.mutate({
              reference_id: reference.id,
              flat_version_id: flat.id,
              harmonize: true,
              strength,
            })
          }
        >
          {t.harmonize}
        </Button>
        <p className="text-[11px] text-ink-muted">{t.harmonizeHint}</p>
        {blocked && <p className="text-xs text-ink-muted">{blocked}</p>}
        {start.error && <ErrorNotice error={start.error} />}
        {save.error && <ErrorNotice error={save.error} />}
      </div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[11px] text-ink-muted">{label}</p>
      {children}
    </div>
  )
}
