import { useHistory } from '@/api/history'
import type { Version } from '@/api/types'
import { ko } from '@/i18n/ko'

/** A flat render the merge can start from: finished, current pipeline, with a frame. */
export const isMergeSource = (v: Version) => v.kind === 'flat' && v.status === 'done' && !v.legacy && !!v.frame

/** A finished code render (no AI) that the optional AI 재질 보정 can start from. */
export const isEnhanceable = (v: Version) =>
  v.kind === 'flat' && v.status === 'done' && !v.legacy && !v.enhancement && v.verify?.mode === 'deterministic'

/** A flat render the finishes can be baked into (not one that already has them). */
export const isFinishSource = (v: Version) =>
  v.kind === 'flat' && v.status === 'done' && !v.legacy && !v.finishing && !!v.frame

/** What a version is, for labels: 플랫 렌더 / AI 재질 보정 / 후가공 버전 / 레퍼런스 합성. */
export const kindLabel = (v: Version) =>
  ko.studio.generation.kinds[v.finishing ? 'finish' : v.enhancement ? 'enhance' : v.kind]

export function useVersions(projectId: string) {
  const history = useHistory(projectId)
  const versions = history.data?.versions ?? []
  const done = versions.filter((v) => v.status === 'done')
  const flats = done.filter((v) => v.kind === 'flat')
  const merges = done.filter((v) => v.kind === 'merge')
  const mergeSources = flats.filter(isMergeSource)
  return { history, versions, done, flats, merges, mergeSources }
}

/** The selected id if it is still in the list, else the newest one. */
export function pick(list: Version[], id: string | null): Version | null {
  return list.find((v) => v.id === id) ?? list[list.length - 1] ?? null
}
