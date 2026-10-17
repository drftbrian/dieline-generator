import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const cache = new Map<string, Promise<PDFDocumentProxy>>()

/** Load (and cache) a PDF for display. The original file is only read, never modified. */
export function loadPdf(url: string): Promise<PDFDocumentProxy> {
  let p = cache.get(url)
  if (!p) {
    p = pdfjs.getDocument({ url }).promise
    p.catch(() => cache.delete(url))
    cache.set(url, p)
  }
  return p
}

/**
 * Render a page so that 1 PDF point = `scale` canvas pixels. Pixel size is capped to keep
 * memory bounded; callers stretch the canvas with CSS to the world size.
 */
export async function renderPage(
  doc: PDFDocumentProxy,
  pageIndex: number,
  canvas: HTMLCanvasElement,
  scale: number,
  maxEdge = 6000,
): Promise<void> {
  const page = await doc.getPage(pageIndex + 1)
  const base = page.getViewport({ scale: 1 })
  const s = Math.min(scale, maxEdge / Math.max(base.width, base.height))
  const viewport = page.getViewport({ scale: s })
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)
  await page.render({ canvas, viewport }).promise
}
