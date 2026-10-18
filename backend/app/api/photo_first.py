"""Step 3, photo-first mode: the AI photos (candidates) to correct and their visible faces. The
correction itself runs as a job (``POST /projects/{pid}/typography``)."""

from __future__ import annotations

from fastapi import APIRouter, File, Response, UploadFile

from app.api.schemas import CandidateFacesIn, CandidateOut, PanelChoice
from app.services import photo_first, specs
from app.storage import repo

router = APIRouter(tags=["photo-first"])


def _out(pid: str, c: dict) -> CandidateOut:
    base = f"/api/projects/{pid}/candidates/{c['id']}"
    return CandidateOut(**c, image_url=f"{base}/image", thumb_url=f"{base}/thumb")


@router.get("/projects/{pid}/candidates/panels", response_model=list[PanelChoice])
def candidate_panels(pid: str) -> list[PanelChoice]:
    """The panels that can be a visible face of the closed carton (not flaps)."""
    spec = specs.load(repo.project_or_404(pid))
    return [
        PanelChoice(id=p.id, name=p.name, width_mm=p.width_mm, height_mm=p.height_mm)
        for p in photo_first.main_panels(spec)
    ]


@router.get("/projects/{pid}/candidates", response_model=list[CandidateOut])
def list_candidates(pid: str) -> list[CandidateOut]:
    repo.project_or_404(pid)
    return [_out(pid, c) for c in photo_first.list_candidates(pid)]


@router.post("/projects/{pid}/candidates", response_model=CandidateOut, status_code=201)
async def upload_candidate(pid: str, file: UploadFile = File(...)) -> CandidateOut:
    """An AI-generated product photo, kept byte for byte. No model reads it."""
    spec = specs.load(repo.project_or_404(pid))
    data = await file.read()
    return _out(pid, photo_first.add_candidate(pid, spec, file.filename or "photo", data))


@router.put("/projects/{pid}/candidates/{cid}/faces", response_model=CandidateOut)
def put_faces(pid: str, cid: str, body: CandidateFacesIn) -> CandidateOut:
    """Which panels are visible in the photo and the rough corners of each face."""
    spec = specs.load(repo.project_or_404(pid))
    faces = [f.model_dump() for f in body.faces]
    return _out(pid, photo_first.save_faces(pid, cid, spec, faces))


@router.delete("/projects/{pid}/candidates/{cid}", status_code=204)
def delete_candidate(pid: str, cid: str) -> Response:
    photo_first.delete_candidate(pid, cid)
    return Response(status_code=204)


@router.get("/projects/{pid}/candidates/{cid}/image")
def candidate_image(pid: str, cid: str) -> Response:
    c = photo_first.get_candidate(pid, cid)
    media = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[c["ext"]]
    return Response(photo_first.image_path(pid, c).read_bytes(), media_type=media)


@router.get("/projects/{pid}/candidates/{cid}/thumb")
def candidate_thumb(pid: str, cid: str) -> Response:
    photo_first.get_candidate(pid, cid)
    path = repo.project_dir(pid) / "candidates" / f"{cid}_thumb.jpg"
    return Response(path.read_bytes(), media_type="image/jpeg")
