export const common = {
  appName: 'Dieline Studio',
  shell: {
    desktopOnlyTitle: '데스크톱에서 사용하세요',
    desktopOnlyBody: 'Dieline Studio는 1024px 이상 화면에서 동작합니다.',
  },
  server: {
    checking: '서버 연결 확인 중',
    ok: '서버 연결됨',
    down: '서버에 연결할 수 없습니다',
    downHint: '`pnpm dev`로 프론트엔드와 서버를 함께 실행했는지 확인하세요.',
  },
  notFound: {
    title: '페이지를 찾을 수 없습니다',
    back: '프로젝트 목록으로',
  },
  actions: {
    cancel: '취소',
    close: '닫기',
    retry: '다시 시도',
    apply: '적용',
    delete: '삭제',
    undo: '실행 취소',
  },
} as const
