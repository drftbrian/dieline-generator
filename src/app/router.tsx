import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from '@/app/AppShell'
import { AnalyzePage } from '@/pages/AnalyzePage'
import { DashboardPage } from '@/pages/DashboardPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { StructuralReviewPage } from '@/pages/StructuralReviewPage'
import { StudioPage } from '@/pages/StudioPage'
import { WorkspaceGate } from '@/pages/WorkspaceGate'

// Dashboard → analyze → structural review → Studio (① 원본 · ② 플랫 렌더 · ③ 레퍼런스 합성).
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: 'projects', element: <DashboardPage /> },
      {
        path: 'projects/:id',
        children: [
          { index: true, element: <WorkspaceGate /> },
          { path: 'analyze', element: <AnalyzePage /> },
          { path: 'review', element: <StructuralReviewPage /> },
          { path: 'studio', element: <StudioPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
