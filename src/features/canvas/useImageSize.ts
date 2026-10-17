import { useEffect, useState } from 'react'

/** Natural pixel size of an image URL (null until it has loaded). */
export function useImageSize(url: string | null): { w: number; h: number } | null {
  const [size, setSize] = useState<{ url: string; w: number; h: number } | null>(null)
  useEffect(() => {
    if (!url) return
    let alive = true
    const img = new Image()
    img.onload = () => alive && setSize({ url, w: img.naturalWidth, h: img.naturalHeight })
    img.src = url
    return () => {
      alive = false
    }
  }, [url])
  return size && size.url === url ? { w: size.w, h: size.h } : null
}
