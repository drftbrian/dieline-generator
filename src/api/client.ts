import type { components } from '@/types/api.gen'

type ErrorBody = Omit<components['schemas']['ErrorBody'], 'details'> & {
  details?: Record<string, unknown>
}

/** Server error with the shared `{ error: { code, message, hint } }` shape. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly hint: string | null
  readonly details: Record<string, unknown>

  constructor(status: number, body: ErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.hint = body.hint ?? null
    this.details = body.details ?? {}
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  json?: unknown
  body?: BodyInit
  /** Sent as `Idempotency-Key` so retried writes don't run twice. */
  idempotent?: boolean
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, idempotent, headers, ...init } = options
  const h = new Headers(headers)
  if (json !== undefined) h.set('Content-Type', 'application/json')
  if (idempotent) h.set('Idempotency-Key', crypto.randomUUID())

  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: h,
      body: json !== undefined ? JSON.stringify(json) : init.body,
    })
  } catch {
    throw new ApiError(0, {
      code: 'NETWORK_ERROR',
      message: '서버에 연결할 수 없습니다.',
      hint: '네트워크 연결을 확인하세요.',
    })
  }

  if (res.status === 204) return undefined as T
  const data: unknown = await res.json().catch(() => null)

  if (!res.ok) {
    const body = (data as { error?: ErrorBody } | null)?.error
    throw new ApiError(
      res.status,
      body ?? { code: `HTTP_${res.status}`, message: '요청을 처리하지 못했습니다.' },
    )
  }
  return data as T
}
