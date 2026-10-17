import { useEffect, useMemo } from 'react'

// One blob: URL per Blob, shared by every user of it. A URL is revoked a moment after its last
// user lets go (the delay survives StrictMode's mount → unmount → mount and lets the next image load).
const urls = new Map<Blob, string>()
const users = new Map<string, number>()
const timers = new Map<string, number>()

function urlFor(blob: Blob) {
  let url = urls.get(blob)
  if (!url) {
    url = URL.createObjectURL(blob)
    urls.set(blob, url)
  }
  return url
}

/** A blob: URL for a Blob, revoked once no component shows it any more. */
export function useObjectUrl(blob: Blob | undefined | null): string | null {
  const url = useMemo(() => (blob ? urlFor(blob) : null), [blob])
  useEffect(() => {
    if (!blob || !url) return
    window.clearTimeout(timers.get(url))
    users.set(url, (users.get(url) ?? 0) + 1)
    return () => {
      const n = (users.get(url) ?? 1) - 1
      users.set(url, n)
      if (n > 0) return
      timers.set(
        url,
        window.setTimeout(() => {
          if ((users.get(url) ?? 0) > 0) return
          URL.revokeObjectURL(url)
          urls.delete(blob)
          users.delete(url)
          timers.delete(url)
        }, 1500),
      )
    }
  }, [blob, url])
  return url
}
