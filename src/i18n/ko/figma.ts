// Figma link import on the dashboard.
export const figma = {
  importTitle: 'Figma 링크로 시작하기',
  importBody: 'Figma에서 패키지 프레임 링크를 붙여넣으면 칼선·접는선, 글자·폰트, 로고, 치수를 그대로 읽어옵니다.',
  importHint: '패키지 프레임을 선택 → 오른쪽 클릭 → "선택 항목 링크 복사"',
  placeholder: 'https://www.figma.com/design/…?node-id=…',
  importButton: '가져오기',
  importing: 'Figma에서 내보내는 중…',
  notConfigured: 'Figma 토큰이 설정되지 않아 링크 가져오기를 쓸 수 없어요. backend/.env에 FIGMA_TOKEN을 넣고 서버를 다시 시작하세요.',
  badge: 'Figma',
} as const
