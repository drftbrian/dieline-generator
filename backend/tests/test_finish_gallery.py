"""Every catalogue finish renders on the test card under both lights (the comparison gallery
script, without reference photos)."""

import sys

from app.config import get_settings


def test_gallery_renders_every_finish(tmp_path, monkeypatch):
    sys.path.insert(0, "scripts")
    import finish_gallery

    from app.finishing import catalog

    monkeypatch.setattr(get_settings(), "finish_reference_dir", tmp_path / "none")
    monkeypatch.setattr(sys, "argv", ["finish_gallery.py", str(tmp_path / "out")])
    finish_gallery.main()
    made = {p.stem for p in (tmp_path / "out").glob("*.jpg")}
    assert {f.id for f in catalog.FINISHES} <= made and "gallery" in made
