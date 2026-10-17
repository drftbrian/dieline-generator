"""Redline rule: outer outline = cut, inner closed cut loops = openings (the background shows)."""

import numpy as np

from app.pdf.geometry import Raster
from app.render.layers import Layers, board
from app.render.shading import render


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def test_an_inner_cut_loop_is_an_opening():
    r = Raster(100, 100, 2.0)
    sil = board(r, [square(10, 10, 90, 90), square(40, 40, 60, 60)])
    assert sil[40, 40]  # board (pixels = 2 x points)
    assert not sil[100, 100]  # inside the window
    assert not sil[5, 5]  # outside the sheet


def test_loops_that_are_part_of_the_outline_stay_board():
    r = Raster(100, 100, 2.0)
    # An outlined stroke: the outline's outer and inner contour (a thin ring).
    ring = [square(10, 10, 90, 90), square(10.5, 10.5, 89.5, 89.5)]
    assert board(r, ring)[100, 100]
    # A closed flap outline sharing the outer edge is board, not a hole.
    flap = [square(10, 10, 90, 90), square(10, 10, 30, 30)]
    assert board(r, flap)[40, 40]


def test_an_inner_cut_loop_renders_black():
    r = Raster(100, 100, 2.0)
    sil = board(r, [square(10, 10, 90, 90), square(40, 40, 60, 60)]).astype(np.float32)
    h, w = sil.shape
    art = np.zeros((h, w, 4), np.float32)
    L = Layers(w, h, 2.0, (0.0, 0.0), art, sil, np.zeros((h, w), np.float32))
    img, alpha = render(L)
    assert img[100, 100, :3].max() == 0  # the window shows the black background
    assert img[40, 40, :3].min() > 200  # white board
    assert alpha[100, 100] == 0
