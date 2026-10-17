"""Upload validation."""

from dataclasses import dataclass

import pymupdf

from app.errors import ApiError


@dataclass
class ValidPdf:
    page_count: int
    width_pt: float
    height_pt: float


def validate_pdf(data: bytes, max_mb: int) -> ValidPdf:
    size_mb = len(data) / (1024 * 1024)
    if size_mb > max_mb:
        raise ApiError(
            413,
            "PDF_TOO_LARGE",
            f"파일이 {max_mb}MB를 넘습니다 ({size_mb:.1f}MB).",
            hint="이미지 해상도를 낮추거나 불필요한 레이어를 제거해주세요.",
            details={"size_mb": round(size_mb, 1), "limit_mb": max_mb},
        )
    if not data.lstrip()[:5] == b"%PDF-":
        raise ApiError(
            400,
            "PDF_INVALID",
            "PDF 파일을 읽을 수 없습니다. 파일이 손상되었거나 PDF 형식이 아닙니다.",
            hint="다른 파일을 선택해주세요.",
        )
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any parser failure means unreadable
        raise ApiError(
            400,
            "PDF_INVALID",
            "PDF 파일을 읽을 수 없습니다. 파일이 손상되었거나 PDF 형식이 아닙니다.",
            hint="다른 파일을 선택해주세요.",
        ) from exc
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ApiError(
                400,
                "PDF_ENCRYPTED",
                "암호로 보호된 PDF입니다.",
                hint="보호를 해제한 뒤 다시 업로드하세요.",
            )
        if doc.page_count == 0:
            raise ApiError(
                400, "PDF_EMPTY", "페이지가 없는 PDF입니다.", hint="다른 파일을 선택해주세요."
            )
        try:
            page = doc[0]
            page.get_drawings()
        except Exception as exc:  # noqa: BLE001
            raise ApiError(
                400,
                "PDF_INVALID",
                "PDF 파일을 읽을 수 없습니다. 파일이 손상되었거나 PDF 형식이 아닙니다.",
                hint="다른 파일을 선택해주세요.",
            ) from exc
        return ValidPdf(doc.page_count, page.rect.width, page.rect.height)
