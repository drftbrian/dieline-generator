import type { CSSProperties } from 'react'
import type { Finish } from '@/api/types'
import { cn } from '@/lib/cn'
import { ko } from '@/i18n/ko'

// CSS-only material hints ("미리보기 견본"): enough to tell foil from pigment, holographic,
// relief, coatings, bare paper and domes apart. Real rendered swatches come later.

function rgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h.padEnd(6, '0')
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) || 0) as [number, number, number]
}

/** Mix towards white (amt > 0) or black (amt < 0). */
function shade(hex: string, amt: number) {
  const target = amt > 0 ? 255 : 0
  const k = Math.abs(amt)
  const [r, g, b] = rgb(hex).map((c) => Math.round(c + (target - c) * k))
  return `rgb(${r} ${g} ${b})`
}

const PAPER = '#ece7de'
const PRINT = 'repeating-linear-gradient(45deg, #d6cdbf 0 3px, #c4b8a6 3px 6px)'

function style(f: Finish): { css: CSSProperties; letter?: CSSProperties } {
  const c = f.color ?? '#c0c0c0'
  const matte = /matte|satin|soft/.test(f.id)
  switch (f.model) {
    case 'metal':
      return {
        css: {
          background: [
            'repeating-radial-gradient(circle at 30% 20%, rgb(255 255 255 / .10) 0 1px, transparent 1px 3px)',
            'linear-gradient(115deg, transparent 32%, rgb(255 255 255 / .85) 45%, transparent 58%)',
            `linear-gradient(135deg, ${shade(c, -0.4)}, ${c} 38%, ${shade(c, 0.35)} 55%, ${shade(c, -0.3)})`,
          ].join(','),
        },
      }
    case 'pigment':
      return {
        css: { background: `linear-gradient(160deg, rgb(255 255 255 / .22), transparent 45%), ${c}` },
      }
    case 'holographic':
      return {
        css: {
          background: [
            'linear-gradient(115deg, transparent 35%, rgb(255 255 255 / .7) 47%, transparent 60%)',
            'conic-gradient(from 40deg at 40% 60%, #fbc2eb, #a6c1ee, #b8f0e0, #fdf6b2, #f9d1b7, #fbc2eb)',
          ].join(','),
        },
      }
    case 'relief': {
      const deboss = /deboss/.test(f.id)
      return {
        css: { background: PAPER },
        letter: {
          color: PAPER,
          textShadow: deboss
            ? '1px 1px 0 rgb(255 255 255 / .9), -1px -1px 1px rgb(0 0 0 / .3)'
            : '-1px -1px 0 rgb(255 255 255 / .95), 1px 1px 1px rgb(0 0 0 / .3)',
        },
      }
    }
    case 'clearcoat':
      return {
        css: {
          background: [
            matte
              ? 'linear-gradient(120deg, transparent 25%, rgb(255 255 255 / .28) 45%, transparent 65%)'
              : 'linear-gradient(120deg, transparent 30%, rgb(255 255 255 / .8) 43%, transparent 56%)',
            matte ? 'linear-gradient(rgb(255 255 255 / .18), rgb(255 255 255 / .18))' : 'linear-gradient(transparent, transparent)',
            PRINT,
          ].join(','),
        },
      }
    case 'uncoated':
      return {
        css: {
          background: [
            'repeating-linear-gradient(17deg, rgb(0 0 0 / .05) 0 1px, transparent 1px 3px)',
            'repeating-linear-gradient(-28deg, rgb(0 0 0 / .04) 0 1px, transparent 1px 4px)',
            'repeating-radial-gradient(circle at 60% 40%, rgb(0 0 0 / .03) 0 1px, transparent 1px 2px)',
            PAPER,
          ].join(','),
        },
      }
    case 'dome':
      return {
        css: {
          background: [
            'radial-gradient(circle at 34% 28%, rgb(255 255 255 / .95) 0 10%, rgb(255 255 255 / .25) 26%, transparent 50%)',
            'radial-gradient(circle at 50% 55%, transparent 55%, rgb(0 0 0 / .18) 75%)',
            f.color ?? PRINT,
          ].join(','),
          borderRadius: '9999px',
        },
      }
    default:
      return { css: { background: f.color ?? PAPER } }
  }
}

/** Small material swatch for a finish. `size` in px. */
export function Swatch({ finish, size = 28, className }: { finish: Finish; size?: number; className?: string }) {
  const { css, letter } = style(finish)
  return (
    <span
      aria-hidden
      title={ko.studio.finishing.assign.swatchCaption}
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-md border border-black/10 shadow-[inset_0_0_0_1px_rgb(255_255_255/.25)]',
        className,
      )}
      style={{ width: size, height: size, ...css }}
    >
      {letter && (
        <span className="leading-none font-black select-none" style={{ fontSize: size * 0.68, ...letter }}>
          A
        </span>
      )}
    </span>
  )
}
