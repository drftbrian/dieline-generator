"""Figma REST API: import a frame by link (PDF export + layer tree).

Uses a personal access token (``FIGMA_TOKEN``, scope ``file_content:read``) sent in the
``X-Figma-Token`` header. Server-side only; the token never reaches the browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import get_settings
from app.errors import ApiError

API = "https://api.figma.com/v1"
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


@dataclass(frozen=True)
class FigmaLink:
    file_key: str
    node_id: str  # API form, "12:34"
    url: str


def parse_link(url: str) -> FigmaLink:
    """Accept figma.com/design|file|proto/<key>/...?node-id=12-34 (branch links too)."""
    u = urlparse(url.strip())
    host = (u.hostname or "").lower()
    if not (host == "figma.com" or host.endswith(".figma.com")):
        raise ApiError(
            400,
            "FIGMA_LINK_INVALID",
            "Figma 링크가 아닙니다.",
            hint="Figma에서 프레임을 선택하고 '링크 복사'한 주소를 붙여넣어 주세요.",
        )
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2 or parts[0] not in ("design", "file", "proto", "board"):
        raise ApiError(
            400,
            "FIGMA_LINK_INVALID",
            "파일 주소를 읽을 수 없습니다.",
            hint="figma.com/design/... 형태의 링크를 붙여넣어 주세요.",
        )
    key = parts[1]
    if "branch" in parts[2:-1]:  # .../<key>/<name>/branch/<branch key>/...
        key = parts[parts.index("branch", 2) + 1]
    node = parse_qs(u.query).get("node-id", [""])[0]
    node = unquote(node).replace("-", ":")
    if not re.fullmatch(r"[\w]+:[\w]+(;[\w:]+)*", node or ""):
        raise ApiError(
            400,
            "FIGMA_NODE_MISSING",
            "링크에 프레임 정보가 없습니다.",
            hint="Figma에서 패키지 프레임을 선택한 뒤 오른쪽 클릭 → '선택 항목 링크 복사'로 다시 복사해 주세요.",
        )
    return FigmaLink(key, node, url.strip())


def configured() -> bool:
    return get_settings().figma_token is not None


def _client() -> httpx.Client:
    token = get_settings().figma_token
    if token is None:
        raise ApiError(
            503,
            "FIGMA_TOKEN_MISSING",
            "Figma 토큰이 설정되지 않았습니다.",
            hint="backend/.env에 FIGMA_TOKEN을 추가한 뒤 서버를 다시 시작하세요.",
        )
    return httpx.Client(
        base_url=API, timeout=TIMEOUT, headers={"X-Figma-Token": token.get_secret_value()}
    )


def _get(c: httpx.Client, path: str, params: dict) -> dict:
    try:
        r = c.get(path, params=params)
    except httpx.HTTPError as e:
        raise ApiError(
            502,
            "FIGMA_UNREACHABLE",
            "Figma에 연결할 수 없습니다.",
            hint="네트워크 연결을 확인하고 다시 시도해 주세요.",
        ) from e
    if r.status_code == 403:
        raise ApiError(
            403,
            "FIGMA_FORBIDDEN",
            "이 Figma 파일에 접근할 수 없습니다.",
            hint="토큰 계정이 파일을 볼 수 있는지, 토큰에 file_content:read 권한이 있는지 확인하세요.",
        )
    if r.status_code == 404:
        raise ApiError(
            404,
            "FIGMA_NOT_FOUND",
            "Figma 파일이나 프레임을 찾을 수 없습니다.",
            hint="링크가 맞는지, 프레임이 삭제되지 않았는지 확인하세요.",
        )
    if r.status_code == 429:
        raise ApiError(
            429,
            "FIGMA_RATE_LIMIT",
            "Figma 요청 한도에 도달했습니다.",
            hint="잠시 후 다시 시도해 주세요.",
        )
    if r.status_code >= 400:
        raise ApiError(
            502,
            "FIGMA_ERROR",
            "Figma가 요청을 처리하지 못했습니다.",
            hint="잠시 후 다시 시도해 주세요.",
            details={"status": r.status_code},
        )
    return r.json()


@dataclass
class FigmaFrame:
    link: FigmaLink
    file_name: str
    node_name: str
    version: str
    last_modified: str
    document: dict  # the frame node, with geometry=paths


def fetch_frame(link: FigmaLink, version: str | None = None) -> FigmaFrame:
    """``version`` pins the file version (e.g. the one whose PDF was imported)."""
    params = {"ids": link.node_id, "geometry": "paths"}
    if version:
        params["version"] = version
    with _client() as c:
        data = _get(c, f"/files/{link.file_key}/nodes", params)
    entry = (data.get("nodes") or {}).get(link.node_id)
    if not entry or not entry.get("document"):
        raise ApiError(
            404,
            "FIGMA_NOT_FOUND",
            "링크의 프레임을 찾을 수 없습니다.",
            hint="프레임을 선택한 상태에서 링크를 다시 복사해 주세요.",
        )
    doc = entry["document"]
    if doc.get("type") not in ("FRAME", "COMPONENT", "INSTANCE", "SECTION", "GROUP"):
        raise ApiError(
            400,
            "FIGMA_NOT_FRAME",
            "선택한 항목이 프레임이 아닙니다.",
            hint="패키지 전개도 전체를 담은 프레임을 선택해 링크를 복사해 주세요.",
        )
    return FigmaFrame(
        link,
        data.get("name", ""),
        doc.get("name", ""),
        str(data.get("version", "")),
        data.get("lastModified", ""),
        doc,
    )


def file_version(link: FigmaLink) -> str:
    """Cheap check for "has the file changed?" (depth-limited node fetch)."""
    with _client() as c:
        data = _get(c, f"/files/{link.file_key}/nodes", {"ids": link.node_id, "depth": 1})
    return str(data.get("version", ""))


def export_pdf(link: FigmaLink) -> bytes:
    """Figma renders the frame to PDF (1 Figma px = 1 pt, origin at the frame's top-left)."""
    with _client() as c:
        data = _get(c, f"/images/{link.file_key}", {"ids": link.node_id, "format": "pdf"})
        url = (data.get("images") or {}).get(link.node_id)
        if data.get("err") or not url:
            raise ApiError(
                502,
                "FIGMA_EXPORT_FAILED",
                "Figma에서 PDF를 내보내지 못했습니다.",
                hint="프레임이 너무 크거나 비어 있지 않은지 확인하고 다시 시도해 주세요.",
            )
        try:
            r = httpx.get(url, timeout=TIMEOUT)  # pre-signed URL: no token header
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ApiError(
                502,
                "FIGMA_EXPORT_FAILED",
                "Figma에서 PDF를 받지 못했습니다.",
                hint="잠시 후 다시 시도해 주세요.",
            ) from e
    return r.content


def frame_url(link: FigmaLink) -> str:
    return f"https://www.figma.com/design/{link.file_key}/?node-id={link.node_id.replace(':', '-')}"
