import { Outlet } from 'react-router'
import { useMinWidth } from '@/lib/useMinWidth'
import { ko } from '@/i18n/ko'

// below 1024px the app is desktop-only.
const DESKTOP_MIN_PX = 1024

export function AppShell() {
  const isDesktop = useMinWidth(DESKTOP_MIN_PX)

  if (!isDesktop) {
    return (
      <main className="flex h-full items-center justify-center p-8 text-center">
        <div className="max-w-sm space-y-2">
          <h1 className="text-lg font-semibold">{ko.shell.desktopOnlyTitle}</h1>
          <p className="text-sm text-ink-muted">{ko.shell.desktopOnlyBody}</p>
        </div>
      </main>
    )
  }

  return <Outlet />
}
