import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api } from './client'
import { keys } from './keys'
import type { Project } from './types'

export const MAX_UPLOAD_MB = 25

type UploadOut = { project: Project; job_id: string }

/** Client-side checks before any bytes are sent. */
export function precheckPdf(file: File): ApiError | null {
  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    return new ApiError(400, {
      code: 'PDF_INVALID',
      message: 'PDF 파일을 읽을 수 없습니다. 파일이 손상되었거나 PDF 형식이 아닙니다.',
      hint: '다른 파일을 선택해주세요.',
    })
  }
  const mb = file.size / (1024 * 1024)
  if (mb > MAX_UPLOAD_MB) {
    return new ApiError(413, {
      code: 'PDF_TOO_LARGE',
      message: `파일이 ${MAX_UPLOAD_MB}MB를 넘습니다 (${mb.toFixed(1)}MB).`,
      hint: '이미지 해상도를 낮추거나 불필요한 레이어를 제거해주세요.',
    })
  }
  return null
}

/** XHR upload so the UI can show "업로드 중… 12.4 / 18.0 MB". */
export function uploadWithProgress(
  projectId: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
): Promise<UploadOut> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/projects/${projectId}/upload`)
    xhr.setRequestHeader('Idempotency-Key', crypto.randomUUID())
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded, e.total)
    xhr.onload = () => {
      let data: unknown = null
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadOut)
      else {
        const body = (data as { error?: ConstructorParameters<typeof ApiError>[1] } | null)?.error
        reject(new ApiError(xhr.status, body ?? { code: `HTTP_${xhr.status}`, message: '업로드하지 못했습니다.' }))
      }
    }
    xhr.onerror = () =>
      reject(new ApiError(0, { code: 'NETWORK_ERROR', message: '서버에 연결할 수 없습니다.', hint: '네트워크 연결을 확인하세요.' }))
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

/** Create a project named after the file and upload it. */
export function useUploadPdf() {
  const qc = useQueryClient()
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null)
  const mutation = useMutation({
    mutationFn: async (file: File) => {
      const pre = precheckPdf(file)
      if (pre) throw pre
      const name = file.name.replace(/\.pdf$/i, '') || 'carton'
      const project = await api<Project>('/projects', { method: 'POST', json: { name }, idempotent: true })
      setProgress({ loaded: 0, total: file.size })
      try {
        return await uploadWithProgress(project.id, file, (loaded, total) => setProgress({ loaded, total }))
      } catch (e) {
        // A rejected file must not leave an empty project behind on the dashboard.
        await api<void>(`/projects/${project.id}`, { method: 'DELETE' }).catch(() => undefined)
        throw e
      }
    },
    onSettled: () => {
      setProgress(null)
      qc.invalidateQueries({ queryKey: keys.projects })
    },
    onSuccess: (out) => qc.setQueryData(keys.project(out.project.id), out.project),
  })
  return { ...mutation, progress }
}

export function useAnalyze(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (page: number | null) =>
      api<{ job_id: string }>(`/projects/${projectId}/analyze`, { method: 'POST', json: { page } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.project(projectId) }),
  })
}

export const sourceFileUrl = (projectId: string) => `/api/projects/${projectId}/source/file`
export const pageImageUrl = (projectId: string) => `/api/projects/${projectId}/page-image`
