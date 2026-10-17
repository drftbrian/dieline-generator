"""The finishing catalogue: stable unique ids, labels, bounded defaults, required subtypes."""

from app.finishing import catalog


def test_ids_are_unique_and_namespaced():
    ids = [f.id for f in catalog.FINISHES]
    assert len(ids) == len(set(ids))
    for f in catalog.FINISHES:
        assert f.id.split(".")[0] == f.category
        assert f.label_ko and f.label_en
        assert f.category in catalog.CATEGORIES


def test_defaults_are_within_bounds():
    for f in catalog.FINISHES:
        for p in f.params:
            assert p.min <= p.default <= p.max, (f.id, p.id)
        assert len({p.id for p in f.params}) == len(f.params), f.id


def test_required_subtypes_exist():
    need = {
        "foil.gold",
        "foil.silver",
        "foil.black",
        "foil.white",
        "foil.red",
        "foil.green",
        "foil.blue",
        "foil.holographic",
        "relief.emboss",
        "relief.deboss",
        "surface.gloss_lamination",
        "surface.matte_lamination",
        "surface.uncoated",
        "coating.spot_uv",
        "coating.flood_uv",
        "coating.varnish_gloss",
        "coating.varnish_matte",
        "coating.varnish_satin",
        "dome.epoxy",
    }
    assert need <= set(catalog.BY_ID)
    # Pigment foils never get the metal model; metallic gold/silver always do.
    assert catalog.finish("foil.black").model == "pigment"
    assert catalog.finish("foil.white").model == "pigment"
    assert catalog.finish("foil.gold").model == "metal"
    # Raised UV is reserved, not offered (not to be confused with spot UV or resin domes).
    assert not catalog.finish("coating.raised_uv").available


def test_clamp_params():
    v = catalog.clamp_params("relief.emboss", {"depth_mm": 9, "bogus": 1})
    assert v["depth_mm"] == 1.0 and "bogus" not in v and v["shoulder_mm"] == 0.4
