import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { ApiError } from '@/api/client'
import { Toaster } from '@/components/ui/Toaster'
import { TooltipProvider } from '@/components/ui/overlays'

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            // Client errors (4xx) are answers, not glitches — don't retry them.
            retry: (count, error) =>
              !(error instanceof ApiError && error.status > 0 && error.status < 500) && count < 2,
          },
        },
      }),
  )
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        {children}
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
