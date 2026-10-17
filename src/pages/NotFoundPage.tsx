import { Link } from 'react-router'
import { ko } from '@/i18n/ko'

export function NotFoundPage() {
  return (
    <main className="flex h-full flex-col items-center justify-center gap-3">
      <h1 className="text-lg font-semibold">{ko.notFound.title}</h1>
      <Link to="/projects" className="text-sm text-accent hover:underline">
        {ko.notFound.back}
      </Link>
    </main>
  )
}
