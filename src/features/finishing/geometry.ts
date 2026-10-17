import type { AssetFrame, Frame } from '@/api/types'

/**
 * The flat view's world is the render image in pixels; the render covers `frame` (page pt).
 * Asset masks cover a slightly different page-pt frame, so everything goes through page pt.
 */
export type PickGeometry = {
  /** Render image size (world units). */
  image: { w: number; h: number }
  /** World (image px) -> page pt. */
  toPage: (p: { x: number; y: number }) => { x: number; y: number }
  /** Is a world point on the render image? */
  inside: (p: { x: number; y: number }) => boolean
  /** Where a mask image covering `mask` (page pt) sits in the world. */
  maskRect: { x: number; y: number; w: number; h: number }
}

type PageFrame = { origin: readonly number[]; size: readonly number[] }

/** Where an image covering `inner` (page pt) sits on a render of `frame` that is `image` px big. */
export function frameRect(frame: Frame, image: { w: number; h: number }, inner: PageFrame) {
  const [ox, oy] = frame.origin
  const kx = image.w / frame.size[0]
  const ky = image.h / frame.size[1]
  return {
    x: ((inner.origin[0] ?? 0) - ox) * kx,
    y: ((inner.origin[1] ?? 0) - oy) * ky,
    w: (inner.size[0] ?? 0) * kx,
    h: (inner.size[1] ?? 0) * ky,
  }
}

export function pickGeometry(frame: Frame, image: { w: number; h: number }, mask: AssetFrame): PickGeometry {
  const [ox, oy] = frame.origin
  const [sw, sh] = frame.size
  const kx = image.w / sw
  const ky = image.h / sh
  return {
    image,
    toPage: (p) => ({ x: ox + p.x / kx, y: oy + p.y / ky }),
    inside: (p) => p.x >= 0 && p.y >= 0 && p.x <= image.w && p.y <= image.h,
    maskRect: frameRect(frame, image, mask),
  }
}

/** Highlight colours (RRGGBB) for the mask endpoint and the panel dots. */
export const HOVER_COLOR = '2563EB'
export const SELECT_COLOR = 'F97316'
