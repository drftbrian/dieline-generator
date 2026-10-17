import { useHistory } from '@/api/history'
import type { Version } from '@/api/types'

/** A flat render the merge can start from: finished, current pipeline, with a frame. */
export const isMergeSource = (v: Version) => v.kind === 'flat' && v.status === 'done' && !v.legacy && !!v.frame

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
