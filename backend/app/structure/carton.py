"""Which folding carton a topology is, from its fold graph alone (no names, no colours).

Recognised:

- **Body:** a chain of four panels joined by parallel folds of one length H, widths W, D, W, D,
  usually with a narrow glue flap at one end (the tube).
- **Each end (top / bottom), from the panels hinged to the body across those folds:**
  - **tuck end:** one W panel carries a lid about D deep with a tuck flap on its far edge,
    and the D panels may carry dust flaps.
  - **crash lock (auto bottom):** diagonal folds in that end (glued triangles). This is
    recognised but **not supported** for folding yet.
  - **unknown:** anything else.
- **Style:** two tuck ends whose lids hang on the same W panel are a straight tuck end (STE),
  and on opposite W panels a reverse tuck end (RTE).

Nothing here guesses: a net that does not match is reported as unsupported with the reasons.
"""

from __future__ import annotations

import statistics

from app.structure.topology import FoldEdge, Topology

BODY_TOL = 0.04  # equal body fold lengths / alternating widths within 4 %
LID_TOL = 0.08  # lid depth vs D
GLUE_MAX = 0.45  # a glue flap is narrower than this share of the body panels


def _chain(top: Topology, orient: str) -> list[str]:
    """The longest chain of panels joined by folds of ``orient`` (a tube's body)."""
    adj: dict[str, list[str]] = {}
    for e in top.folds:
        if e.orientation == orient:
            adj.setdefault(e.a, []).append(e.b)
            adj.setdefault(e.b, []).append(e.a)
    best: list[str] = []
    for start in adj:
        if len(adj[start]) != 1:
            continue
        path, prev, cur = [start], None, start
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in path]
            if len(nxt) != 1:
                break
            prev, cur = cur, nxt[0]
            path.append(cur)
        if len(path) > len(best):
            best = path
    return best


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(a, b, 1e-6)


def _body(top: Topology, nodes: dict, best: str):
    """(chain, order, glue, roles, W, D, H) of a W·D·W·D tube along folds of ``best``, or a
    Korean reason why that chain is not one."""
    chain = _chain(top, best)
    if len(chain) < 4:
        return "4개 이상 이어진 몸통 패널(같은 길이의 평행한 접는 선)을 찾지 못했습니다."
    across = (lambda p: p.width_mm) if best == "vertical" else (lambda p: p.height_mm)
    chain_folds = [e for e in top.folds if e.orientation == best and e.a in chain and e.b in chain]
    widths = [across(nodes[p]) for p in chain]
    order = list(chain)  # as on the dieline, glue flap included
    glue = None
    typical = statistics.median(widths)
    if widths[0] < GLUE_MAX * typical:
        glue, chain, widths = chain[0], chain[1:], widths[1:]
    elif widths[-1] < GLUE_MAX * typical:
        glue, chain, widths = chain[-1], chain[:-1], widths[:-1]
    if len(chain) != 4:
        return f"몸통 패널이 4개가 아닙니다 ({len(chain)}개)."
    a, b, c, d = widths
    if not (_close(a, c, BODY_TOL) and _close(b, d, BODY_TOL)):
        listed = ", ".join(f"{w:.1f}" for w in widths)
        return f"몸통 패널 너비가 W·D·W·D로 번갈아 나오지 않습니다 ({listed} mm)."
    body_lengths = [e.length_mm for e in chain_folds if e.a in chain and e.b in chain]
    H = statistics.median(body_lengths) if body_lengths else 0.0
    if body_lengths and not all(_close(L, H, BODY_TOL) for L in body_lengths):
        return "몸통의 접는 선 길이가 서로 다릅니다."
    w_idx, d_idx = ((0, 2), (1, 3)) if (a + c) >= (b + d) else ((1, 3), (0, 2))
    W = (widths[w_idx[0]] + widths[w_idx[1]]) / 2
    D = (widths[d_idx[0]] + widths[d_idx[1]]) / 2
    roles = {p: ("W" if i in w_idx else "D") for i, p in enumerate(chain)}
    if glue:
        roles[glue] = "glue"
    return chain, order, glue, roles, W, D, H


def classify(top: Topology, box=None) -> dict:
    out: dict = {"family": None, "style": None, "supported": False, "reasons": [], "checks": []}
    if not top.ok:
        out["reasons"].append("구조 오류가 있어 상자 형태를 판단하지 않았습니다.")
        return out
    nodes = {p.id: p for p in top.panels}
    # The body: the chain of parallel folds that forms a W·D·W·D tube. Both directions are
    # tried, longest chain first (a column of lid, body panel and tucks can be longer).
    found, why = None, "4개 이상 이어진 몸통 패널(같은 길이의 평행한 접는 선)을 찾지 못했습니다."
    for orient in sorted(("vertical", "horizontal"), key=lambda o: -len(_chain(top, o))):
        body = _body(top, nodes, orient)
        if isinstance(body, str):
            if len(_chain(top, orient)) >= 4 and found is None:
                why = body
            continue
        found = (orient, *body)
        break
    if found is None:
        out["reasons"].append(why)
        return out
    best, chain, order, glue, roles, W, D, H = found
    out["family"] = "rectangular_folding_carton"
    out["body"] = {
        "orientation": best,
        "panels": order,
        "roles": roles,
        "W_mm": round(W, 1),
        "D_mm": round(D, 1),
        "H_mm": round(H, 1),
        "glue_flap": glue,
    }

    # Ends: everything hinged to the body across its folds, split by side.
    body_set = set(chain) | ({glue} if glue else set())
    other = "horizontal" if best == "vertical" else "vertical"

    def centre(p):
        x0, y0, x1, y1 = nodes[p].bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    body_mid = statistics.mean(centre(p)[1 if best == "vertical" else 0] for p in chain)

    def subtree(root: str) -> tuple[set[str], list[FoldEdge]]:
        seen, edges, stack = {root}, [], [root]
        while stack:
            cur = stack.pop()
            for n, e in top.neighbours(cur):
                if n in body_set:
                    continue
                if e not in edges:
                    edges.append(e)
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        return seen, edges

    sides: dict[str, dict] = {}
    for side in ("top", "bottom") if best == "vertical" else ("left", "right"):
        roots = []
        for e in top.folds:
            if e.orientation != other:
                continue
            for body_p, flap in ((e.a, e.b), (e.b, e.a)):
                if body_p in chain and flap not in body_set:
                    pos = centre(flap)[1 if best == "vertical" else 0]
                    if (pos < body_mid) == (side in ("top", "left")):
                        roots.append((body_p, flap, e))
        info: dict = {"type": "none" if not roots else "unknown", "flaps": {}}
        diag = False
        for body_p, flap, _ in roots:
            members, edges = subtree(flap)
            diag |= any(x.orientation == "diagonal" for x in edges)
            info["flaps"][flap] = {
                "on": body_p,
                "role_of_body": roles[body_p],
                "panels": sorted(members),
            }
        if diag:
            info["type"] = "crash_lock"
            info["supported"] = False
            info["note"] = (
                "대각선 접는 선(접착 삼각형)이 있는 자동 잠금 바닥입니다. 아직 접기를 지원하지 않습니다."
            )
        elif roots:
            on_w = [(bp, f) for bp, f, _ in roots if roles[bp] == "W"]
            on_d = [(bp, f) for bp, f, _ in roots if roles[bp] == "D"]
            if len(on_w) == 1:
                bp, lid = on_w[0]
                lid_depth = nodes[lid].height_mm if best == "vertical" else nodes[lid].width_mm
                tucks = [
                    n
                    for n, e in top.neighbours(lid)
                    if n not in body_set and e.orientation == other
                ]
                info["lid"] = lid
                info["lid_on"] = bp
                info["lid_depth_mm"] = lid_depth
                info["dust_flaps"] = [f for _, f in on_d]
                info["tuck_flap"] = tucks[0] if len(tucks) == 1 else None
                if tucks and _close(lid_depth, D, LID_TOL):
                    info["type"] = "tuck_end"
                    info["supported"] = True
                else:
                    info["note"] = "뚜껑 깊이가 D와 다르거나 꽂이 날개가 없습니다."
                    info["supported"] = False
                out["checks"].append(
                    {
                        "check": f"{side}_lid_depth_vs_D",
                        "lid_mm": lid_depth,
                        "D_mm": round(D, 1),
                        "ok": _close(lid_depth, D, LID_TOL),
                    }
                )
            else:
                info["supported"] = False
                info["note"] = (
                    "뚜껑 구성을 알 수 없습니다 (W 패널 두 개에 모두 날개가 있거나 없음)."
                )
        else:
            info["supported"] = True  # an open end (a sleeve)
        sides[side] = info
    out["ends"] = sides
    ends = list(sides.values())
    if all(e["type"] == "tuck_end" for e in ends):
        same = ends[0]["lid_on"] == ends[1]["lid_on"]
        out["style"] = "straight_tuck_end" if same else "reverse_tuck_end"
    elif any(e["type"] == "crash_lock" for e in ends) and any(
        e["type"] == "tuck_end" for e in ends
    ):
        out["style"] = "tuck_top_crash_lock_bottom"
    else:
        out["style"] = "unrecognised"
    out["supported"] = all(e.get("supported") for e in ends)
    for side, e in sides.items():
        if not e.get("supported"):
            out["reasons"].append(f"{side}: {e.get('note', '지원하지 않는 구성입니다.')}")
    if box is not None:
        out["checks"].append(
            {
                "check": "dims_vs_stated_box",
                "measured_mm": [round(W, 1), round(D, 1), round(H, 1)],
                "stated_mm": [box.width_mm, box.depth_mm, box.height_mm],
                "ok": all(
                    abs(m - s) <= 2.0
                    for m, s in zip(
                        (W, D, H), (box.width_mm, box.depth_mm, box.height_mm), strict=True
                    )
                ),
            }
        )
    return out
