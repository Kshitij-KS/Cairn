# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
build_atlas.py — turn the memory into one JSON file the dashboard can render.

    build_atlas.py                 # public build: redacted, safe to deploy
    build_atlas.py --full          # local build: everything, never deployed
    build_atlas.py --out web/data/graph.json

It imports memory_guard's own parsers rather than reimplementing them. That is deliberate: if
the dashboard parsed frontmatter or relations differently from the engine that enforces the
rules, the picture would drift from the policy and the drift would be invisible — a dashboard
confidently displaying a graph nobody is actually governed by.

REDACTION is the load-bearing feature here, because this output is published. It is driven by
the `confidentiality:` field already on every note:

    open        everything, including the body
    internal    title, level, attribution, dates, tags, relation edges, observation counts by
                category, and a BRIEF (first sentence of the summary, capped) - no bodies, no
                individual observations
    restricted  the node is not emitted at all, and neither are its edges

The build REFUSES to produce a public file if any note lacks a confidentiality field, because
the safe default for an unlabelled note is "do not publish", and silently guessing is how leaks
happen.
"""

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def load_guard():
    """Import memory_guard as a module so the parsers are shared, not copied."""
    path = os.path.join(HERE, "memory_guard.py")
    spec = importlib.util.spec_from_file_location("memory_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mg = load_guard()

ACTIVITY_LIMIT = 200
BRIEF_CHARS = 160
STALE_DAYS = 90

LEVEL_META = {
    "L0": {"label": "observation", "colour": "#22d3ee"},
    "L1": {"label": "project planning", "colour": "#a78bfa"},
    "L2": {"label": "ideation & strategy", "colour": "#fb923c"},
    "L3": {"label": "governance", "colour": "#f43f5e"},
}


# --------------------------------------------------------------------------- helpers


def strip_md(text):
    """Flatten Markdown to a readable sentence — no HTML comments, links or emphasis."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"(?m)^\s*[#>]+\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def make_brief(body):
    """First real sentence of the note's summary, capped. Never an observation line."""
    for block in re.split(r"\n\s*\n", body):
        b = block.strip()
        if not b or b.startswith("#") or b.startswith("-") or b.startswith("|"):
            continue
        if b.startswith("```") or b.startswith(">"):
            continue
        flat = strip_md(b)
        if not flat:
            continue
        m = re.match(r"^(.{40,%d}?[.!?])\s" % BRIEF_CHARS, flat + " ")
        out = m.group(1) if m else flat[:BRIEF_CHARS].rsplit(" ", 1)[0] + "…"
        return out.strip()
    return ""


def parse_days_ago(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M"):
        try:
            d = datetime.strptime(date_str.strip()[:19 if "T" in date_str else 10], fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - d).days)
        except ValueError:
            continue
    return None


def git(ctx, *args):
    return mg.git("-C", ctx.repo_root, *args)


# --------------------------------------------------------------------------- collection


def collect_notes(ctx):
    notes = []
    roots = []
    for fn in sorted(os.listdir(ctx.notes_root)):
        if fn.endswith(".md") and os.path.isfile(os.path.join(ctx.notes_root, fn)):
            roots.append((fn, os.path.join(ctx.notes_root, fn)))
    for rel, abs_path in roots:
        try:
            text = mg.read_text(abs_path)
        except OSError:
            continue
        fm, body = mg.split_frontmatter(text)
        if fm is not None:
            notes.append((rel, abs_path, fm, body, text))
    for d in mg.NOTE_DIRS:
        root = os.path.join(ctx.notes_root, d)
        if not os.path.isdir(root):
            continue
        for dirpath, _dn, filenames in os.walk(root):
            for fn in sorted(filenames):
                if not fn.endswith(".md"):
                    continue
                abs_path = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_path, ctx.notes_root).replace(os.sep, "/")
                if rel.startswith("templates/") or rel == "log/CHANGELOG.md":
                    continue  # scaffolding and the generated log are not knowledge nodes
                try:
                    text = mg.read_text(abs_path)
                except OSError:
                    continue
                fm, body = mg.split_frontmatter(text)
                if fm is None:
                    continue
                notes.append((rel, abs_path, fm, body, text))
    return notes


def observation_stats(body):
    """Count observations per category without exposing their contents."""
    body = mg.strip_code(body)
    cats, total = {}, 0
    for m in re.finditer(r"^\s*-\s*\[([a-zA-Z][\w-]*)\]\s*(.+)$", body, re.M):
        cat = m.group(1).lower()
        cats[cat] = cats.get(cat, 0) + 1
        total += 1
    return total, cats


def observation_list(body):
    body = mg.strip_code(body)
    out = []
    for m in re.finditer(r"^\s*-\s*\[([a-zA-Z][\w-]*)\]\s*(.+)$", body, re.M):
        out.append({"category": m.group(1).lower(), "text": strip_md(m.group(2))})
    return out


def relations_of(body):
    body = mg.strip_code(body)
    rels = []
    for m in re.finditer(
        r"^\s*-\s+(\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)?\s*\[\[([^\]]+)\]\]", body, re.M
    ):
        rtype = (m.group(1) or "links_to").strip('"')
        target = m.group(2).strip()
        if target.startswith("<") or target.startswith("__"):
            continue  # template placeholder
        rels.append((rtype, target))
    return rels


# --------------------------------------------------------------------------- activity


def in_restricted_location(rel):
    return mg.norm_path(rel).startswith("context/restricted/")


def build_activity(ctx, public, node_paths, hidden_paths=frozenset(), show_authors=True, pub_path=None):
    # The record separator goes at the START. With it at the end, --name-only puts each commit's
    # file list into the NEXT chunk, and every commit silently parses as having no files.
    fmt = "%x02%H%x01%an%x01%ad%x01%s%x01%b"
    raw = git(ctx, "log", "--date=format:%Y-%m-%dT%H:%M:%S", "-n", str(ACTIVITY_LIMIT * 2),
              "--no-merges", "--pretty=format:" + fmt, "--name-only")
    entries = []
    for chunk in raw.split("\x02"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        head, _, files_blob = chunk.partition("\n")
        parts = head.split("\x01")
        if len(parts) < 4:
            continue
        sha, author, date, subject = parts[0], parts[1], parts[2], parts[3]
        body = parts[4] if len(parts) > 4 else ""
        files = [f.strip() for f in files_blob.split("\n") if f.strip()]
        files = [f for f in files
                 if f != "log/CHANGELOG.md"
                 and not f.startswith("web/data/")
                 and "__pycache__" not in f
                 and not f.endswith(".pyc")
                 and f not in hidden_paths
                 and not (public and in_restricted_location(f[len(ctx.prefix):] if ctx.prefix and f.startswith(ctx.prefix) else f))]
        if not files:
            continue
        levels = [ctx.path_level(f) for f in files]
        real = [l for l in levels if l in mg.LEVEL_ORDER]
        level = max(real, key=mg.level_rank) if real else "L0"
        if public:
            # Only the paths of notes the map already publishes, under their public names. Code
            # paths say how the codebase is laid out, a note's old path can be its restricted or
            # withheld name, and neither belongs on the page (recheck D2, 07-F1).
            rels = [f[len(ctx.prefix):] if ctx.prefix and f.startswith(ctx.prefix) else f for f in files]
            shown = [(pub_path or {}).get(r) for r in rels if r in node_paths]
            shown = [x for x in shown if x]
        else:
            shown = files
        actor = "agent" if re.search(r"Sync-Actor:\s*agent", body) else "human"
        am = re.search(r"Sync-Agent:\s*(\S+)", body)
        agent = am.group(1) if am and am.group(1) != "unknown" else None
        touched = [f for f in files
                   if f.replace(ctx.prefix, "", 1) in node_paths or f in node_paths]
        if public:
            touched = [(pub_path or {}).get(f.replace(ctx.prefix, "", 1) if ctx.prefix else f, f) for f in touched]
        entries.append({
            "sha": sha[:8],
            "author": author if show_authors else None,
            "at": date,
            "level": level,
            "actor": actor,
            "agent": agent if show_authors else None,
            "files": len(files),
            "paths": shown[:6],
            "touched": touched[:12],
            # A commit subject can carry the very thing the note bodies are withholding
            # ("promote: switch payments to the new provider at 1.9% per charge"). Withheld publicly.
            "message": None if public else subject,
        })
        if len(entries) >= ACTIVITY_LIMIT:
            break
    return entries


# --------------------------------------------------------------------------- health


def build_health(nodes, edges, unresolved):
    ids = {n["id"] for n in nodes}
    linked = set()
    for e in edges:
        linked.add(e["source"])
        linked.add(e["target"])
    issues = []

    orphans = [n for n in nodes if n["id"] not in linked]
    for n in orphans:
        issues.append({"kind": "orphan", "severity": "major", "id": n["id"],
                       "title": n["title"],
                       "detail": "nothing links to it and it links to nothing - graph traversal "
                                 "will never surface this note"})

    todo = [n for n in nodes if n["todos"] > 0]
    for n in sorted(todo, key=lambda x: -x["todos"]):
        issues.append({"kind": "placeholder", "severity": "major" if n["level"] in ("L2", "L3") else "minor",
                       "id": n["id"], "title": n["title"],
                       "detail": "%d unfilled TODO placeholder%s - agents read this note first and "
                                 "find a blank" % (n["todos"], "s" if n["todos"] != 1 else "")})

    stale = [n for n in nodes if (n["age_days"] or 0) >= STALE_DAYS]
    for n in stale:
        issues.append({"kind": "stale", "severity": "minor", "id": n["id"], "title": n["title"],
                       "detail": "untouched for %d days" % n["age_days"]})

    flagged = [n for n in nodes if n["review_needed"]]
    for n in flagged:
        issues.append({"kind": "review_needed", "severity": "major", "id": n["id"],
                       "title": n["title"],
                       "detail": "a planning change landed upstream: %s" % n["review_needed"]})

    for src, target in unresolved:
        issues.append({"kind": "broken_link", "severity": "minor", "id": src,
                       "title": target,
                       "detail": "relation points at [[%s]], which does not exist" % target})

    penalty = (len(orphans) * 6 + sum(1 for i in issues if i["kind"] == "placeholder") * 4
               + len(stale) * 2 + len(flagged) * 5 + len(unresolved) * 2)
    score = max(0, 100 - penalty)
    return {
        "score": score,
        "counts": {
            "orphans": len(orphans),
            "placeholders": sum(1 for i in issues if i["kind"] == "placeholder"),
            "stale": len(stale),
            "review_needed": len(flagged),
            "broken_links": len(unresolved),
        },
        "issues": issues[:60],
    }


# --------------------------------------------------------------------------- clustering & layout
#
# THE CEILING IS TYPOGRAPHIC, NOT COMPUTATIONAL. Measured three ways and they agree: a 1120x760
# plot pane holds 68-102 non-overlapping 11px labels; a force layout tuned for that pane keeps 0%
# label collision at 60 nodes and 54% at 90; a packed layout degrades from 40. Drawing the whole
# corpus is therefore not slow, it is impossible - at 1000 notes fit-to-view is 0.25x, which
# renders an 11px label at under 3px. Canvas, WebGL and edge bundling do not move this number.
#
# So the map never shows more than CAP labelled things at one depth, whatever the corpus does.
# The corpus is cut into buckets of at most CAP, oversized buckets are cut again, and every
# position is computed HERE rather than in the browser. Two reasons, and the second is the
# better one: the page never runs a simulation, and the map looks identical for everyone on the
# team, so "that cluster on the left" means the same thing to all of you on every visit.

# Measured: about 60 labelled items fit a pane when they can be placed freely. A note's label is
# anchored under its own mark, which is a much tighter constraint - at 54 notes the spacing is
# 56px and a 130px label cannot fit, so only nine of them could be named. 32 is where a leaf view
# names most of what it holds. Growth goes into DEPTH, and every level still has a real name.
CAP = 32
WORLD = 1000.0                   # layout units; the client fits this box to its pane
GOLDEN = 2.399963229728653       # radians - the angle that packs a disc without rings lining up
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _pretty(segment):
    return re.sub(r"[-_]+", " ", segment).strip().title()


def _area_key(n):
    """Which part of the memory this note lives in. Folder path, so a per-project tier
    clusters by its own subfolders rather than collapsing into one blob."""
    d = os.path.dirname(n["path"])
    if not d:
        return ("overview", "Overview")
    return ("area:" + d, _pretty(d.split("/")[-1]))


def _month_of(n):
    s = (n.get("updated") or n.get("created") or "")[:7]
    return s if re.match(r"^\d{4}-\d{2}$", s) else ""


def _time_key(n):
    s = _month_of(n)
    if not s:
        return ("time:undated", "Undated")
    y, m = s.split("-")
    return ("time:" + s, "%s %s" % (MONTHS[int(m) - 1], y))


def _day_key(n):
    s = (n.get("updated") or n.get("created") or "")[:10]
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return ("day:undated", "Undated")
    return ("day:" + s, "%d %s" % (d.day, MONTHS[d.month - 1]))


def _week_key(n):
    s = (n.get("updated") or n.get("created") or "")[:10]
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return ("week:undated", "Undated")
    monday = d - timedelta(days=d.weekday())
    return ("week:" + monday.isoformat(),
            "Week of %d %s" % (monday.day, MONTHS[monday.month - 1]))


def _bucket(nodes, keyfn):
    """Stable grouping: buckets appear in the order their first member does."""
    out, order = {}, []
    for n in nodes:
        k, label = keyfn(n)
        if k not in out:
            out[k] = {"id": k, "label": label, "members": []}
            order.append(k)
        out[k]["members"].append(n)
    return [out[k] for k in order]


def _chunks(cluster):
    """Last resort. A numbered boundary tells a reader nothing - "Jan 2026 1" and "Jan 2026 2"
    do not say which half a note is in - so this runs only when no real key is left."""
    ms = cluster["members"]
    return [{"id": "%s/%d" % (cluster["id"], i // CAP),
             "label": "%s, part %d" % (cluster["label"], i // CAP + 1),
             "members": ms[i:i + CAP]}
            for i in range(0, len(ms), CAP)]


def _partition(nodes, keys):
    """Bucket by keys[0]; split anything over CAP by keys[1], and so on down the list.

    Each key is a distinction a person can predict - folder, then month, then week. The first
    version had a single fallback key and then went straight to numbered chunks, which produced
    a level of "Jan 2026 1 to May 2026 1" discs that meant nothing to anyone.
    """
    def build(items, ks):
        out = []
        for c in _bucket(items, ks[0]):
            if len(c["members"]) <= CAP:
                out.append(c)
                continue
            kids = build(c["members"], ks[1:]) if len(ks) > 1 else []
            if len(kids) < 2:        # a split that does not split is not a level
                kids = _chunks(c)
            c["children"] = kids
            c["members"] = []
            out.append(c)
        return out
    return build(nodes, keys)


def _collapse(c):
    """A level holding exactly one thing is a click that shows you what you were already
    looking at. Splice it out."""
    for k in (c.get("children") or []):
        _collapse(k)
    while len(c.get("children") or []) == 1:
        only = c["children"][0]
        c["members"] = only.get("members") or []
        c["children"] = only.get("children") or []


def _cluster_radius(count):
    """Log, not square root. Square root gave a 701-note group eleven times the radius of a
    1-note group, which made the small ones unreadable dots and wasted most of the canvas on
    one disc. Log keeps the ordering honest and the range about five to one."""
    return 34.0 + 30.0 * math.log2(1 + max(1, count))


def _radii(counts, floor=0.34):
    """Radii for one level, with a floor relative to the largest on that level.

    A group's name is drawn inside its disc, so a disc too small to hold a name is a group
    with no name at all. Ordering by size still reads; three-to-one is enough to see it."""
    raw = [_cluster_radius(c) for c in counts]
    big = max(raw) if raw else 1.0
    return [max(r, big * floor) for r in raw]


def _relax(items, iters=240, pull=0.012, springs=()):
    """Push overlapping discs apart, pull the whole set gently toward the origin, and hold any
    springs. Deterministic: the same notes always give the same layout."""
    for _ in range(iters):
        for a, b, rest, k in springs:
            dx, dy = items[b]["x"] - items[a]["x"], items[b]["y"] - items[a]["y"]
            d = math.hypot(dx, dy) or 0.01
            f = (d - rest) / d * k * 0.5
            items[a]["x"] += dx * f; items[a]["y"] += dy * f
            items[b]["x"] -= dx * f; items[b]["y"] -= dy * f
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                d = math.hypot(dx, dy) or 0.01
                need = a["r"] + b["r"]
                if d < need:
                    push = (need - d) / d * 0.5
                    a["x"] -= dx * push; a["y"] -= dy * push
                    b["x"] += dx * push; b["y"] += dy * push
        for it in items:
            it["x"] -= it["x"] * pull
            it["y"] -= it["y"] * pull
    return items


def _layout_packed(clusters):
    """The AREA arrangement: constellations packed around the centre, biggest nearest, so the
    shape of what the team knows is the shape of the picture.

    Discs are padded by LABEL_PAD while they are being pushed apart, because a constellation is
    drawn with its name above it and its level mix below it. Packing the discs alone left the
    labels touching on a corpus of three thousand."""
    LABEL_PAD = 38.0
    order = sorted(range(len(clusters)), key=lambda i: -clusters[i]["count"])
    rs = _radii([c["count"] for c in clusters])
    items = [None] * len(clusters)
    for seat, i in enumerate(order):
        a = seat * GOLDEN
        rad = 64.0 * math.sqrt(seat + 0.6)
        items[i] = {"x": math.cos(a) * rad, "y": math.sin(a) * rad,
                    "r": rs[i] + LABEL_PAD}
    _relax(items, iters=260, pull=0.014)
    for c, it in zip(clusters, items):
        c["x"], c["y"] = round(it["x"], 2), round(it["y"], 2)
        c["r"] = round(it["r"] - LABEL_PAD, 2)
    return clusters


def _layout_stream(clusters):
    """The TIME arrangement: a stream running left to right, oldest upstream.

    Spacing is CUMULATIVE, not a fixed span divided by the number of months. A fixed span was the
    first attempt and it failed the moment the corpus reached seventeen months: the discs grow
    with their contents, the span did not, and the month labels ran into each other. The stream
    is therefore as long as its contents need, and the client frames it."""
    def sort_key(c):
        return (0, c["id"]) if c["id"] != "time:undated" else (1, "")
    order = sorted(clusters, key=sort_key)
    rs = _radii([c["count"] for c in order])
    for c, r in zip(order, rs):
        c["r"] = round(r, 2)

    LABEL = 132.0            # a month label is about this wide once drawn; discs may not crowd it
    x = 0.0
    for i, c in enumerate(order):
        if i:
            gap = max((order[i - 1]["r"] + c["r"]) * 1.22, LABEL)
            x += gap
        c["x"] = x
    span = x or 1.0
    for i, c in enumerate(order):
        t = c["x"] / span
        c["x"] = round(c["x"] - span / 2, 2)
        c["y"] = round(math.sin(t * math.pi * 2.1) * max(WORLD * 0.15, span * 0.06)
                       + (1 if i % 2 else -1) * c["r"] * 0.34, 2)
    return clusters


def _layout_members(cluster, edges_by_id):
    """Positions for the notes inside one constellation, in a local unit box. Seeded by
    phyllotaxis, which alone is enough for the journal (a sequence, not a network), then relaxed
    only when the notes actually link to each other."""
    members = cluster["members"]
    if not members:
        return
    idx = {m["id"]: i for i, m in enumerate(members)}
    items = []
    for i, m in enumerate(members):
        a = i * GOLDEN
        rad = math.sqrt(i + 0.5) / math.sqrt(len(members)) * 0.92
        items.append({"x": math.cos(a) * rad, "y": math.sin(a) * rad,
                      "r": 0.055 + 0.028 * math.sqrt(max(1, m["observations"]))})
    springs = []
    for e in edges_by_id:
        if e["source"] in idx and e["target"] in idx:
            springs.append((idx[e["source"]], idx[e["target"]],
                            0.30 if e["dependency"] else 0.46,
                            0.30 if e["dependency"] else 0.10))
    if springs:
        _relax(items, iters=170, pull=0.010, springs=springs)
    else:
        _relax(items, iters=45, pull=0.004)
    span = max(max(abs(it["x"]) + it["r"], abs(it["y"]) + it["r"]) for it in items) or 1.0
    # Positions live on the CLUSTER, not the note: the same note sits in one cluster of the area
    # arrangement and a different one of the time arrangement, and writing to the note would let
    # the second arrangement quietly overwrite the first.
    cluster["pos"] = {m["id"]: [round(it["x"] / span, 4), round(it["y"] / span, 4)]
                      for m, it in zip(members, items)}
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    cluster["_levels_by_id"] = {m["id"]: order.get(m["level"], 0) for m in members}


# Density has to survive being drawn in a large disc: 44 points in a 700-note region reads as
# scatter, not as tissue. The cap is what a disc can hold before the dots merge, not a fixed number.
SAMPLE_MAX = 130


def _sample_points(cluster, depth=0):
    """Up to SAMPLE_MAX positions, in unit space, of the notes this cluster contains.

    Drawn at the region level this makes a group read as tissue - you can see that Journal is
    dense and Overview is sparse - and it is the real geometry, not a texture. Children are
    folded in at their own offset so the pattern survives nesting."""
    pts = []
    if cluster.get("pos"):
        # carry the level index so the tissue is a readout, not a texture
        lv = cluster.get("_levels_by_id") or {}
        pts = [[x, y, lv.get(i, 0)] for i, (x, y) in cluster["pos"].items()]
    else:
        kids = cluster.get("children") or []
        if kids and depth < 4:
            rs = [max(0.12, k.get("r", 60)) for k in kids]
            big = max(rs) if rs else 1.0
            for k in kids:
                sub = _sample_points(k, depth + 1)
                if not sub:
                    continue
                # child's own centre within the parent, normalised
                span = max(abs(k.get("x", 0)), abs(k.get("y", 0)), 1.0)
                cx = k.get("x", 0) / (span * 2.4) if span else 0.0
                cy = k.get("y", 0) / (span * 2.4) if span else 0.0
                f = (k.get("r", big) / big) * 0.34
                pts.extend([[cx + px * f, cy + py * f, lvl] for px, py, lvl in sub])
    if len(pts) > SAMPLE_MAX:
        step = len(pts) / SAMPLE_MAX
        pts = [pts[int(i * step)] for i in range(SAMPLE_MAX)]
    return [[round(x, 3), round(y, 3), lvl] for x, y, lvl in pts]


def _summarise(cluster):
    """What an aggregate is allowed to say about itself: counts only. No member titles, because
    a cluster label is published and a title is not, whatever the notes inside are rated."""
    def collect(c):
        # recursive: the tree can be three deep now, and a one-level sum reported zero notes
        # for every group whose children are themselves groups
        if c["members"]:
            return list(c["members"])
        out = []
        for ch in c.get("children", []):
            out.extend(collect(ch))
        return out

    ms = collect(cluster)
    mix = {}
    for m in ms:
        mix[m["level"]] = mix.get(m["level"], 0) + 1
    ages = [m["age_days"] for m in ms if m["age_days"] is not None]
    cluster["count"] = len(ms)
    cluster["levels"] = mix
    cluster["observations"] = sum(m["observations"] for m in ms)
    cluster["review_needed"] = sum(1 for m in ms if m["review_needed"])
    cluster["todos"] = sum(m["todos"] for m in ms)
    cluster["newest_days"] = min(ages) if ages else None
    cluster["oldest_days"] = max(ages) if ages else None


TOP_CAP = 10           # months fit on a stream only while there are few enough to label
GROUP_CAP = 9          # and so do sub-groups, which is the cap that was missing


def _regroup(clusters):
    """Cap the number of GROUPS on a level, not just the number of notes.

    The first version capped members at 54 and left children uncounted, so a three-thousand-note
    corpus opened Journal onto forty-five month discs and sixty per cent of their labels ran into
    each other. Every level has the same ceiling; this enforces it on the levels that hold groups.
    """
    if len(clusters) <= GROUP_CAP:
        return clusters

    years = {}
    for c in clusters:
        m = re.match(r"^time:(\d{4})-\d{2}", c["id"])
        if not m:
            years = None
            break
        years.setdefault(m.group(1), []).append(c)
    # the year roll-up only helps if it actually divides the run; one year holding everything
    # would recurse forever and add a level that explains nothing
    if years and 1 < len(years) <= GROUP_CAP:
        return [{"id": "time:" + y, "label": y, "members": [], "children": _regroup(kids)}
                for y, kids in sorted(years.items())]

    # generic: chunk the run and name each chunk by the span it covers
    size = max(GROUP_CAP, -(-len(clusters) // GROUP_CAP))
    out = []
    for i in range(0, len(clusters), size):
        part = clusters[i:i + size]
        label = part[0]["label"] if len(part) == 1 \
            else "%s to %s" % (part[0]["label"], part[-1]["label"])
        out.append({"id": "%s..%s" % (part[0]["id"], part[-1]["id"]), "label": label,
                    "members": [], "children": part})
    return out


def _year_key(n):
    s = _month_of(n)
    return ("time:" + s[:4], s[:4]) if s else ("time:undated", "Undated")


def _time_partition(nodes):
    """Months while there are few enough of them to label, years once there are not.

    The first version always used months, and at seventeen months the labels along the stream
    ran together - the top level has the same ceiling as every other level, and nothing was
    enforcing it there."""
    months = _bucket(nodes, _time_key)
    if len(months) <= TOP_CAP:
        return _partition(nodes, [_time_key, _week_key, _day_key, _area_key])
    return _partition(nodes, [_year_key, _time_key, _week_key, _day_key])


def build_arrangement(kind, nodes, edges):
    """One complete arrangement of the corpus: clusters, their layout, member positions, and
    the edges rolled up to cluster level so the far view can show flow without showing 2000
    lines."""
    if kind == "area":
        clusters = _partition(nodes, [_area_key, _time_key, _week_key, _day_key])
    else:
        clusters = _time_partition(nodes)

    # collapse levels that hold one thing, then cap GROUPS per level as well as notes
    for c in clusters:
        _collapse(c)
    for c in clusters:
        if c.get("children"):
            c["children"] = _regroup(c["children"])
        _collapse(c)

    def walk(c):
        for ch in c.get("children", []):
            walk(ch)
        _summarise(c)
        if c["members"]:
            _layout_members(c, edges)

    for c in clusters:
        walk(c)

    top = clusters
    (_layout_packed if kind == "area" else _layout_stream)(top)

    def pack_children(c):
        """Children sit inside their parent's disc, by the same rules, at every depth. The 30
        units of padding is room for each child's own label."""
        kids = c.get("children") or []
        if not kids:
            return
        ordered = sorted(kids, key=lambda k: -k["count"])
        rs = _radii([k["count"] for k in ordered])
        items = []
        for seat, (ch, r) in enumerate(zip(ordered, rs)):
            a = seat * GOLDEN
            rad = 52.0 * math.sqrt(seat + 0.6)
            items.append({"ch": ch, "x": math.cos(a) * rad, "y": math.sin(a) * rad,
                          "r": r * 0.82 + 30.0})
        _relax(items, iters=200, pull=0.02)
        for it in items:
            it["ch"]["x"], it["ch"]["y"] = round(it["x"], 2), round(it["y"], 2)
            it["ch"]["r"] = round(it["r"] - 30.0, 2)
            pack_children(it["ch"])

    for c in top:
        pack_children(c)

    def attach_sample(c):
        for k in (c.get("children") or []):
            attach_sample(k)
        c["sample"] = _sample_points(c)

    for c in top:
        attach_sample(c)

    # cluster-level edges: every note relation rolled up to the TOP cluster it lands in
    home = {}

    def claim(c, top_id):
        for m in c["members"]:
            home[m["id"]] = top_id
        for ch in c.get("children", []):
            claim(ch, top_id)

    for c in top:
        claim(c, c["id"])
    weights = {}
    for e in edges:
        a, b = home.get(e["source"]), home.get(e["target"])
        if a is None or b is None or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        w = weights.setdefault(key, {"source": key[0], "target": key[1],
                                     "weight": 0, "dependency": 0})
        w["weight"] += 1
        w["dependency"] += 1 if e["dependency"] else 0

    def strip(c):
        out = {k: v for k, v in c.items()
               if k not in ("members", "children", "_levels_by_id")}
        out["members"] = [m["id"] for m in c["members"]]
        out["children"] = [strip(ch) for ch in c.get("children", [])]
        return out

    return {
        "kind": kind,
        "clusters": [strip(c) for c in top],
        "edges": sorted(weights.values(), key=lambda w: (-w["weight"], w["source"])),
        "cap": CAP,
    }


# --------------------------------------------------------------------------- main build


def build(ctx, public=True):
    notes = collect_notes(ctx)

    missing_conf = [rel for rel, _a, fm, _b, _t in notes if not mg.fm_get(fm, "confidentiality")]
    if public and missing_conf:
        mg.die(
            "refusing to build a PUBLIC atlas: %d note(s) have no `confidentiality` field, and the "
            "safe default for an unlabelled note is 'do not publish'.\n  %s\n"
            "  Fix: uv run -q --script scripts/memory_guard.py stamp --all"
            % (len(missing_conf), "\n  ".join(missing_conf[:8])),
            5,
        )

    by_title, nodes, node_paths = {}, [], set()
    withheld = {"restricted": 0, "bodies": 0, "briefs": 0, "experiments": 0}
    pub = ctx.policy.get("publication", {})
    publish_authors = bool(pub.get("publish_authors", False))
    # Everything that names a restricted note: its id, path and title. They must appear nowhere in a
    # public file, including derived fields (broken-link health, activity paths) - audit 07-F1.
    restricted = {"ids": set(), "paths": set(), "titles": set()}

    # A note whose TITLE is sensitive (`public_title:` or `publish_title: false`) is published under
    # an opaque id and path: its file name is its title as a slug, and relations name it by the real
    # title. Keying relations on the public title lost the edge AND published the real title as a
    # "broken link" (recheck 07-F6). The real title, id and path join the leak sweep below.
    hidden = {"ids": set(), "paths": set(), "titles": set()}
    pub_id, pub_path = {}, {}
    if public:
        masked = []
        for rel, _a, fm, _b, _t in notes:
            conf0 = "restricted" if in_restricted_location(rel) else (mg.fm_get(fm, "confidentiality") or "internal").strip()
            if conf0 in ("restricted", "open"):
                continue
            if (mg.fm_get(fm, "publish_title") or "").lower() == "false" or mg.fm_get(fm, "public_title"):
                masked.append(((mg.fm_get(fm, "created") or ""), rel, fm))
        for i, (_c, rel, fm) in enumerate(sorted(masked), 1):
            d = os.path.dirname(rel)
            pid = (d + "/" if d else "") + "withheld-%d" % i
            pub_id[rel], pub_path[rel] = pid, pid + ".md"
            hidden["ids"].add(rel[:-3])
            hidden["paths"].add(rel)
            hidden["paths"].add((ctx.prefix + rel) if ctx.prefix else rel)
            hidden["titles"].add((mg.fm_get(fm, "title") or os.path.basename(rel)[:-3]).strip())

    for rel, abs_path, fm, body, _text in notes:
        conf = (mg.fm_get(fm, "confidentiality") or "internal").strip()
        # The restricted location wins over any label: `confidentiality: open` under
        # context/restricted/ published a full body (audit 07-F7).
        if in_restricted_location(rel):
            conf = "restricted"
        real_title = (mg.fm_get(fm, "title") or os.path.basename(rel)[:-3]).strip()
        if public and conf == "restricted":
            withheld["restricted"] += 1
            restricted["ids"].add(rel[:-3])
            restricted["paths"].add(rel)
            restricted["paths"].add((ctx.prefix + rel) if ctx.prefix else rel)
            restricted["titles"].add((mg.fm_get(fm, "title") or os.path.basename(rel)[:-3]).strip())
            continue

        title = (mg.fm_get(fm, "title") or os.path.basename(rel)[:-3]).strip()
        if public and conf != "open":
            # Titles are the map, so they publish by default; a note whose title is itself
            # sensitive sets `public_title:` or `publish_title: false` (audit 07-F6).
            if (mg.fm_get(fm, "publish_title") or "").lower() == "false":
                title = "Untitled note"
            elif mg.fm_get(fm, "public_title"):
                title = mg.fm_get(fm, "public_title").strip()
        level = ctx.path_level(ctx.prefix + rel if ctx.prefix else rel) or "L0"
        if level not in mg.LEVEL_ORDER:
            level = "L0"
        obs_total, obs_cats = observation_stats(body)
        tags = [t.strip() for t in (mg.fm_get(fm, "tags") or "").strip("[]").split(",") if t.strip()]
        updated = mg.fm_get(fm, "updated") or mg.fm_get(fm, "created")
        todos = len(re.findall(r"TODO:", body))
        show_body = (not public) or conf == "open"
        # Trials and evals are experiments on the memory itself: a hypothesis ("the architecture
        # note is wrong about X") or a test question can reveal what the team doubts. Public builds
        # carry their existence and status only, whatever their confidentiality says.
        experiment = rel.startswith(("trials/", "evals/"))
        if public and experiment:
            show_body = False
            withheld["experiments"] += 1
        if not show_body:
            withheld["bodies"] += 1

        # A summary line is the note's first sentence. For an L2 strategy note that sentence is
        # the strategy, so publishing it would undo the redaction beside it. Governed by
        # publication.brief_levels rather than hard-coded here.
        pub = ctx.policy.get("publication", {})
        brief_levels = pub.get("brief_levels", ["L0"])
        show_brief = (not public) or conf == "open" or level in brief_levels
        if public and experiment:
            show_brief = False
        if not show_brief:
            withheld["briefs"] = withheld.get("briefs", 0) + 1

        node = {
            "id": pub_id.get(rel, rel[:-3]),
            "path": pub_path.get(rel, rel),
            "title": title,
            "folder": rel.split("/")[0],
            "type": mg.fm_get(fm, "type") or "note",
            "level": level,
            "confidentiality": conf,
            "author": mg.fm_get(fm, "author") if (publish_authors or not public) else None,
            "updated_by": mg.fm_get(fm, "updated_by") if (publish_authors or not public) else None,
            "agent": mg.fm_get(fm, "agent") if (publish_authors or not public) else None,
            "status": mg.fm_get(fm, "status"),
            "created": mg.fm_get(fm, "created"),
            "updated": updated,
            "age_days": parse_days_ago(updated),
            "tags": tags,
            "observations": obs_total,
            "categories": obs_cats,
            "todos": todos,
            "review_needed": mg.fm_get(fm, "review_needed"),
            "brief": make_brief(body) if show_brief else None,
            "body": body.strip() if show_body else None,
            "observation_list": observation_list(body) if show_body else None,
            "claims": len([c for c in mg.parse_claims(body) if c[3]]),
        }
        if rel.startswith("features/"):
            secs = mg.note_sections(body)
            node["feature"] = {
                "status": mg.fm_get(fm, "status"),
                "owner": mg.fm_get(fm, "owner") if (publish_authors or not public) else None,
                # code paths say how the codebase is laid out: full builds only
                "covers": None if public else mg.fm_list(fm, "covers"),
                "card": (secs.get("card") or "").strip() if show_brief else None,
                "contract": (secs.get("contract") or "").strip() if show_body else None,
            }
        if rel.startswith("trials/"):
            node["trial"] = {
                "status": mg.fm_get(fm, "status"),
                "expires": mg.fm_get(fm, "expires"),
                "owner": mg.fm_get(fm, "owner") if (publish_authors or not public) else None,
                "audience": len(mg.fm_list(fm, "for")) if public else mg.fm_list(fm, "for"),
                "hypothesis": None if public else mg.fm_get(fm, "hypothesis"),
            }
            if public:
                node["title"] = "Trial"  # a trial's title is its hypothesis in short
        if rel.startswith("evals/") and public:
            node["title"] = "Retrieval tests"
        nodes.append(node)
        node_paths.add(rel)
        pub_id.setdefault(rel, node["id"])
        pub_path.setdefault(rel, node["path"])
        by_title.setdefault(real_title, node["id"])   # relations name the REAL title

    dependency_types = set(
        ctx.policy.get("cascade", {}).get("relation_types_followed",
                                          ["implements", "depends_on", "part_of", "supersedes"])
    )
    edges, unresolved, seen = [], [], set()
    id_set = {n["id"] for n in nodes}
    for rel, _abs, _fm, body, _t in notes:
        src = pub_id.get(rel)
        if src not in id_set:
            continue  # restricted source: its edges are withheld too
        for rtype, target in relations_of(body):
            tid = by_title.get(target)
            if tid is None:
                if public and (target in restricted["titles"] or target in hidden["titles"]):
                    continue  # a link to a restricted note: say nothing, not even "broken"
                unresolved.append((src, target))
                continue
            if tid == src:
                continue
            key = (src, tid, rtype)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": src, "target": tid, "type": rtype,
                          "dependency": rtype in dependency_types})

    activity = build_activity(ctx, public, node_paths, restricted["paths"] if public else set(),
                              publish_authors or not public, pub_path)
    health = build_health(nodes, edges, unresolved)
    arrangements = {k: build_arrangement(k, nodes, edges) for k in ("area", "time")}

    # queue: what is waiting on a human
    proposals = []
    for n in nodes:
        if n["path"].startswith("log/proposals/") or n["title"].upper().startswith("PROPOSAL"):
            proposals.append({
                "id": n["id"], "title": n["title"], "status": n["status"] or "open",
                "author": n["author"], "age_days": n["age_days"], "level": n["level"],
                "brief": n["brief"],   # already withheld above when the level is not publishable
            })
    review = [{"id": n["id"], "title": n["title"], "level": n["level"],
               "why": n["review_needed"], "age_days": n["age_days"]}
              for n in nodes if n["review_needed"]]

    # features: the spine agents navigate by, with its dependency direction resolved
    feat_ids = {n["id"] for n in nodes if "feature" in n}
    features = []
    for n in nodes:
        if "feature" not in n:
            continue
        up = sorted({e["target"] for e in edges if e["source"] == n["id"] and e["dependency"]
                     and e["target"] in feat_ids})
        down = sorted({e["source"] for e in edges if e["target"] == n["id"] and e["dependency"]
                       and e["source"] in feat_ids})
        features.append(dict(n["feature"], id=n["id"], title=n["title"], relies_on=up, relied_on_by=down,
                             gaps=0))
    gaps = []
    for rel, _abs, _fm, body, _t in notes:
        if not rel.startswith("log/gaps/") or pub_id.get(rel) not in id_set:
            continue
        linked = [by_title.get(t) for _r, t in relations_of(body)]
        feature = next((x for x in linked if x in feat_ids), None)
        for (_i, cat, text, cid, sec) in mg.parse_claims(body):
            if cat != "gap" or sec == "retired":
                continue
            gaps.append({"id": cid, "feature": feature, "text": None if public else text})
            for f in features:
                if f["id"] == feature:
                    f["gaps"] += 1
    trials = [dict(n["trial"], id=n["id"], title=n["title"]) for n in nodes if "trial" in n]

    # Playbooks (ADR-005): trust is DERIVED here exactly as mem and the guard derive it, from the
    # hash-bound approval and the run log beside each playbook. Only counts and labels are
    # published; steps, caveats and run notes stay in the notes.
    playbooks = []
    node_by_path = {n["path"]: n for n in nodes}
    for rel, abs_path, fm, body, _t in notes:
        n = node_by_path.get(rel)
        if not n or not rel.startswith("playbooks/") or (mg.fm_get(fm, "type") or "") != "playbook":
            continue
        runs_path = abs_path[:-3] + ".runs"
        runs, _bad = mg.parse_runs(mg.read_text(runs_path) if os.path.isfile(runs_path) else "")
        t = mg.playbook_trust(ctx, fm or [], body, runs)
        playbooks.append({"id": n["id"], "playbook": mg.fm_get(fm, "id") or "", "title": n["title"],
                          "trust": t["label"], "stale": t["stale"], "runs": t["runs"], "successes": t["successes"],
                          "failed": t["failed"], "last_success": t["last_success"], "steps": len(mg.parse_steps(body))})

    # "What the agent saw": local, full builds only. The ledgers live in the
    # gitignored .memory/ on this machine; a public build never reads them.
    sessions = []
    if not public:
        sdir = os.path.join(ctx.notes_root, ".memory", "session")
        if os.path.isdir(sdir):
            for fn in sorted(os.listdir(sdir)):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(sdir, fn), encoding="utf-8") as fh:
                        led = json.load(fh)
                except (OSError, ValueError):
                    continue
                sessions.append({"session": led.get("session"), "ref": led.get("ref"),
                                 "started": led.get("started"), "turns": led.get("turn", 0),
                                 "loaded": [{"id": k, "depth": v.get("depth"), "turn": v.get("turn"),
                                             "evicted": bool(v.get("evicted"))}
                                            for k, v in (led.get("loaded") or {}).items()]})
            sessions.sort(key=lambda x: x.get("started") or "", reverse=True)
            sessions = sessions[:10]

    sha = git(ctx, "rev-parse", "--short", "HEAD").strip() or "working-tree"
    # UTC from the commit timestamp: a local-time rendering would publish the committer's offset.
    _ct = git(ctx, "log", "-1", "--format=%ct").strip()
    sha_at = (datetime.fromtimestamp(int(_ct), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
              if _ct.isdigit() else "")
    remote = git(ctx, "remote", "get-url", "origin").strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", remote)
    repo_url = "https://github.com/%s/%s" % (m.group(1), m.group(2)) if m else None

    out = {
        "schema": 4,
        "mode": "public" if public else "full",
        "project": ctx.project_name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": sha,
        "source_commit_at": sha_at,
        "repo_url": repo_url,
        "levels": {k: dict(LEVEL_META[k], **{"paths": ctx.policy["levels"][k]["paths"],
                                             "may_change": ctx.policy["levels"][k]["may_change"]})
                   for k in mg.LEVEL_ORDER if k in ctx.policy.get("levels", {})},
        "dependency_types": sorted(dependency_types),
        "publication": ctx.policy.get("publication", {}),
        "withheld": withheld,
        "stats": {
            "notes": len(nodes),
            "observations": sum(n["observations"] for n in nodes),
            "relations": len(edges),
            "dependencies": sum(1 for e in edges if e["dependency"]),
            "authors": len({n["author"] for n in nodes if n["author"]}),
            "commits": len(activity),
            "claims": sum(n["claims"] for n in nodes),
            "features": len(features),
            "gaps": len(gaps),
            "live_trials": sum(1 for t in trials if t["status"] == "live"),
            "playbooks": len(playbooks),
        },
        "features": features,
        "gaps": gaps,
        "trials": trials,
        "playbooks": playbooks,
        "sessions": sessions,
        "nodes": nodes,
        "edges": edges,
        "arrangements": arrangements,
        "activity": activity,
        "queue": {"proposals": proposals, "review_needed": review},
        "health": health,
    }
    if public:
        sweep = {k: restricted[k] | hidden[k] for k in restricted}
        leaks = restricted_leaks(out, sweep)
        if leaks:
            mg.die("refusing to build a PUBLIC atlas: the name of a restricted note, or a withheld title, "
                   "would appear in %s.\n  Reword the note that mentions it (its brief is its first "
                   "sentence), or rename the restricted note." % ", ".join(leaks[:5]), 5)
    return out


def _leak_rx(restricted):
    tokens = sorted({t for t in (restricted["ids"] | restricted["paths"] | restricted["titles"]) if t},
                    key=len, reverse=True)
    if not tokens:
        return None
    # Whole words only: a restricted note titled "Plan" must not block every brief that says
    # "Planning" (recheck D7). Case-insensitive, so "ACME deal" is caught for "Acme Deal".
    return re.compile(r"(?<![\w])(?:%s)(?![\w])" % "|".join(re.escape(t) for t in tokens), re.I)


def restricted_leaks(obj, restricted, where="$", _rx=None):
    """Every JSON location whose key or string value names a restricted note (id, path or title)."""
    rx = _rx if _rx is not None else _leak_rx(restricted)
    if rx is None:
        return []
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and rx.search(k):
                found.append(where + "." + k)
            found += restricted_leaks(v, restricted, where + "." + str(k), rx)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += restricted_leaks(v, restricted, "%s[%d]" % (where, i), rx)
    elif isinstance(obj, str):
        if rx.search(obj):
            found.append(where)
    return found


# The ONLY shape a public graph.json may have (schema 3). Anything else is a leak until proven
# otherwise: the old verifier was a denylist and 26 of 46 tampering cases passed it (audit 07-F3).
_S = str
_N = (int, float)
_OPT_S = (str, type(None))
_LVL = ("L0", "L1", "L2", "L3")
SCHEMA = {
    "$": {"schema": int, "mode": _S, "project": _S, "generated_at": _S, "source_commit": _S,
          "source_commit_at": _S, "repo_url": _OPT_S, "levels": dict, "dependency_types": list,
          "publication": dict, "withheld": dict, "stats": dict, "nodes": list, "edges": list,
          "arrangements": dict, "activity": list, "queue": dict, "health": dict, "features": list,
          "gaps": list, "trials": list, "playbooks": list, "sessions": list},
    "level": {"label": _S, "colour": _S, "paths": list, "may_change": list},
    "publication": {"$comment": _S, "brief_levels": list, "publish_commit_messages": bool,
                    "publish_authors": bool, "$comment_containment": _S},
    "withheld": {"restricted": int, "bodies": int, "briefs": int, "experiments": int},
    "stats": {k: int for k in ("notes", "observations", "relations", "dependencies", "authors",
                               "commits", "claims", "features", "gaps", "live_trials", "playbooks")},
    "node": {"id": _S, "path": _S, "title": _S, "folder": _S, "type": _S, "level": _S,
             "confidentiality": _S, "author": _OPT_S, "updated_by": _OPT_S, "agent": _OPT_S,
             "status": _OPT_S, "created": _OPT_S, "updated": _OPT_S, "age_days": (int, type(None)),
             "tags": list, "observations": int, "categories": dict, "todos": int,
             "review_needed": _OPT_S, "brief": _OPT_S, "body": _OPT_S, "observation_list": (list, type(None)),
             "claims": int, "feature": dict, "trial": dict},
    "node.feature": {"status": _OPT_S, "owner": _OPT_S, "covers": type(None), "card": _OPT_S,
                     "contract": _OPT_S},
    "node.trial": {"status": _OPT_S, "expires": _OPT_S, "owner": _OPT_S, "audience": int, "hypothesis": type(None)},
    "edge": {"source": _S, "target": _S, "type": _S, "dependency": bool},
    "arrangement": {"kind": _S, "cap": int, "clusters": list, "edges": list},
    "cluster": {"id": _S, "label": _S, "count": int, "observations": int, "review_needed": int,
                "todos": int, "newest_days": (int, type(None)), "oldest_days": (int, type(None)),
                "levels": dict, "x": _N, "y": _N, "r": _N, "members": list, "children": list,
                "pos": dict, "sample": list},
    "cluster_edge": {"source": _S, "target": _S, "weight": _N, "dependency": _N},
    "activity": {"sha": _S, "author": _OPT_S, "at": _S, "level": _S, "actor": _S, "agent": _OPT_S,
                 "files": int, "paths": list, "touched": list, "message": type(None)},
    "queue": {"proposals": list, "review_needed": list},
    "proposal": {"id": _S, "title": _S, "status": _S, "author": _OPT_S, "age_days": (int, type(None)),
                 "level": _S, "brief": _OPT_S},
    "review": {"id": _S, "title": _S, "level": _S, "why": _OPT_S, "age_days": (int, type(None))},
    "health": {"score": int, "counts": dict, "issues": list},
    "issue": {"kind": _S, "severity": _S, "id": _S, "title": _S, "detail": _S},
    "feature": {"id": _S, "title": _S, "status": _OPT_S, "owner": _OPT_S, "covers": type(None),
                "card": _OPT_S, "contract": _OPT_S, "relies_on": list, "relied_on_by": list, "gaps": int},
    "gap": {"id": _OPT_S, "feature": _OPT_S, "text": type(None)},
    "trial": {"id": _S, "title": _S, "status": _OPT_S, "expires": _OPT_S, "owner": _OPT_S,
              "audience": int, "hypothesis": type(None)},
    "playbook": {"id": _S, "playbook": _S, "title": _S, "trust": _S, "stale": bool, "runs": int,
                 "successes": int, "failed": int, "last_success": _OPT_S, "steps": int},
}
_REQUIRED_TOP = set(SCHEMA["$"])


def _shape(bad, obj, kind, where, required=None):
    spec = SCHEMA[kind]
    if not isinstance(obj, dict):
        bad.append("%s: expected an object" % where)
        return False
    for k, v in obj.items():
        if k not in spec:
            bad.append("%s: unknown field %r" % (where, k))
        elif not isinstance(v, spec[k]) or (spec[k] is int and isinstance(v, bool)):
            bad.append("%s.%s: wrong type %s" % (where, k, type(v).__name__))
    for k in (required or ()):
        if k not in obj:
            bad.append("%s: missing %r" % (where, k))
    return True


def _no_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError("duplicate JSON key %r" % k)
        seen[k] = v
    return seen


def load_strict(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh, object_pairs_hook=_no_dupes)


DEFAULT_PUBLICATION = {"brief_levels": ["L0"], "publish_authors": False, "publish_commit_messages": False}


def _items(bad, seq, types, where):
    """Every element of a list has one of the allowed types (the closed schema typed only the list
    itself, so a secret could ride inside tags or sample points, recheck 07-F3)."""
    if not isinstance(seq, list):
        return
    for i, v in enumerate(seq):
        if not isinstance(v, types) or (isinstance(v, bool) and bool not in (types if isinstance(types, tuple) else (types,))):
            bad.append("%s[%d]: wrong type %s" % (where, i, type(v).__name__))


def _values(bad, obj, types, where, key_rx=None):
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        if key_rx is not None and not re.match(key_rx, k):
            bad.append("%s: unexpected key %r" % (where, k[:40]))
        if not isinstance(v, types) or isinstance(v, bool):
            bad.append("%s.%s: wrong type %s" % (where, k[:40], type(v).__name__))


def _point(bad, v, where, n):
    if not (isinstance(v, list) and len(v) == n and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
        bad.append("%s: not a point" % where)


def verify_public(d, trusted_publication=None):
    """Closed schema, reference integrity, then every publication rule. Returns problems (empty = ok).

    The file's own `publication` block is a claim, not a fact: a tampered file can grant itself
    publish_authors or brief_levels "all". Without the policy (trusted_publication) the strictest
    defaults apply, and a file claiming more is refused (recheck 07-F3). CI also compares the file
    with a fresh build from source (--against-source)."""
    bad = []
    if not isinstance(d, dict):
        return ["the file is not a JSON object"]
    _shape(bad, d, "$", "$", _REQUIRED_TOP)
    if d.get("schema") != 4:
        bad.append("schema is %r, expected 4" % d.get("schema"))
    if d.get("mode") != "public":
        bad.append("mode is %r, not public" % d.get("mode"))
    if bad:
        return bad
    pub = d["publication"]
    _shape(bad, pub, "publication", "$.publication")
    _items(bad, pub.get("brief_levels"), str, "$.publication.brief_levels")
    trusted = trusted_publication if trusted_publication is not None else DEFAULT_PUBLICATION
    t_levels = set(trusted.get("brief_levels", ["L0"]) or [])
    claimed = set(pub.get("brief_levels") or [])
    if claimed - t_levels:
        bad.append("$.publication.brief_levels: the file claims %s beyond the %s setting %s"
                   % (sorted(claimed - t_levels), "policy's" if trusted_publication is not None else "default",
                      sorted(t_levels)))
    if bool(pub.get("publish_authors")) and not bool(trusted.get("publish_authors")):
        bad.append("$.publication.publish_authors: the file claims true; the %s says false"
                   % ("policy" if trusted_publication is not None else "default"))
    brief_levels = t_levels & (claimed or t_levels)
    authors_ok = bool(trusted.get("publish_authors")) and bool(pub.get("publish_authors"))
    _items(bad, d.get("dependency_types"), str, "$.dependency_types")
    for i, t in enumerate(d.get("dependency_types") or []):
        if isinstance(t, str) and not re.match(r"^[a-z][a-z_]{0,31}$", t):
            bad.append("$.dependency_types[%d]: not a relation type" % i)
    for k, v in d["levels"].items():
        if k not in _LVL:
            bad.append("$.levels: unknown level %r" % k)
        _shape(bad, v, "level", "$.levels.%s" % k)
        if isinstance(v, dict):
            _items(bad, v.get("paths"), str, "$.levels.%s.paths" % k)
            _items(bad, v.get("may_change"), str, "$.levels.%s.may_change" % k)
    _shape(bad, d["withheld"], "withheld", "$.withheld")
    _shape(bad, d["stats"], "stats", "$.stats")

    ids = []
    for i, n in enumerate(d["nodes"]):
        w = "$.nodes[%d]" % i
        if not _shape(bad, n, "node", w, ("id", "path", "title", "level", "confidentiality", "body", "brief")):
            continue
        ids.append(n.get("id"))
        _items(bad, n.get("tags"), str, w + ".tags")
        _values(bad, n.get("categories"), int, w + ".categories", r"^[a-z][\w-]{0,40}$")
        if isinstance(n.get("observation_list"), list):
            for j, o in enumerate(n["observation_list"]):
                if not (isinstance(o, dict) and set(o) <= {"category", "text"} and all(isinstance(x, str) for x in o.values())):
                    bad.append("%s.observation_list[%d]: not an observation" % (w, j))
        if n.get("level") not in _LVL:
            bad.append("%s.level: %r" % (w, n.get("level")))
        if n.get("confidentiality") not in ("open", "internal", "restricted"):
            bad.append("%s.confidentiality: %r" % (w, n.get("confidentiality")))
        conf, level, path = n.get("confidentiality"), n.get("level"), n.get("path", "")
        if conf == "restricted" or path.startswith("context/restricted/"):
            bad.append("%s: restricted note present (%s)" % (w, n.get("id")))
        if n.get("body") is not None and conf != "open":
            bad.append("%s: body published (%s)" % (w, n.get("id")))
        if n.get("observation_list") is not None and conf != "open":
            bad.append("%s: observations published (%s)" % (w, n.get("id")))
        if n.get("brief") is not None and conf != "open" and level not in brief_levels:
            bad.append("%s: %s summary published above publication.brief_levels (%s)" % (w, level, n.get("id")))
        if path.startswith(("trials/", "evals/")) and any(n.get(k) is not None for k in ("body", "brief", "observation_list")):
            bad.append("%s: experiment content published (%s)" % (w, n.get("id")))
        if not authors_ok and any(n.get(k) for k in ("author", "updated_by", "agent")):
            bad.append("%s: identity published while publish_authors is false" % w)
        if "feature" in n:
            _shape(bad, n["feature"], "node.feature", w + ".feature")
            if conf != "open" and level not in brief_levels and n["feature"].get("card") is not None:
                bad.append("%s.feature.card: published above brief_levels" % w)
            if conf != "open" and n["feature"].get("contract") is not None:
                bad.append("%s.feature.contract: published" % w)
        if "trial" in n:
            _shape(bad, n["trial"], "node.trial", w + ".trial")
    idset = set(ids)
    pathset = {n.get("path") for n in d["nodes"] if isinstance(n, dict)}
    by_id = {n.get("id"): n for n in d["nodes"] if isinstance(n, dict)}
    if len(idset) != len(ids):
        bad.append("$.nodes: duplicate ids")

    for i, e in enumerate(d["edges"]):
        if _shape(bad, e, "edge", "$.edges[%d]" % i, ("source", "target")):
            if e.get("source") not in idset or e.get("target") not in idset:
                bad.append("$.edges[%d]: references a note that is not public" % i)

    for name, arr in d["arrangements"].items():
        w = "$.arrangements.%s" % name
        if name not in ("area", "time"):
            bad.append("%s: unknown arrangement" % w)
            continue
        if not _shape(bad, arr, "arrangement", w):
            continue
        stack = [(c, "%s.clusters[%d]" % (w, j)) for j, c in enumerate(arr.get("clusters", []))]
        cids = set()
        while stack:
            c, cw = stack.pop()
            if not _shape(bad, c, "cluster", cw):
                continue
            cids.add(c.get("id"))
            _items(bad, c.get("members"), str, cw + ".members")
            for m in c.get("members", []):
                if m not in idset:
                    bad.append("%s.members: %r is not a public note" % (cw, m))
            for m, pv in (c.get("pos") or {}).items():
                if m not in idset:
                    bad.append("%s.pos: %r is not a public note" % (cw, m))
                _point(bad, pv, "%s.pos[%r]" % (cw, m), 2)
            for j, sp in enumerate(c.get("sample") or []):
                _point(bad, sp, "%s.sample[%d]" % (cw, j), 3)
            _values(bad, c.get("levels"), int, cw + ".levels")
            for lk in (c.get("levels") or {}):
                if lk not in _LVL:
                    bad.append("%s.levels: unknown key %r" % (cw, lk))
            stack += [(ch, "%s.children[%d]" % (cw, k)) for k, ch in enumerate(c.get("children", []))]
        for j, ce in enumerate(arr.get("edges", [])):
            if _shape(bad, ce, "cluster_edge", "%s.edges[%d]" % (w, j)):
                if ce.get("source") not in cids or ce.get("target") not in cids:
                    bad.append("%s.edges[%d]: unknown cluster" % (w, j))

    for i, a in enumerate(d["activity"]):
        w = "$.activity[%d]" % i
        if _shape(bad, a, "activity", w):
            if a.get("message") is not None:
                bad.append("%s: commit message published" % w)
            if not authors_ok and (a.get("author") or a.get("agent")):
                bad.append("%s: identity published while publish_authors is false" % w)
            _items(bad, a.get("touched"), str, w + ".touched")
            _items(bad, a.get("paths"), str, w + ".paths")
            for t in a.get("touched", []):
                if t not in pathset:
                    bad.append("%s.touched: %r is not a public note" % (w, t))
            for pth in a.get("paths", []):
                if pth.startswith("context/restricted/") or "/context/restricted/" in pth:
                    bad.append("%s.paths: restricted path" % w)
                elif pth not in pathset:
                    bad.append("%s.paths: %r is not a public note (code paths are never published)" % (w, pth))
            if a.get("level") not in _LVL or a.get("actor") not in ("agent", "human"):
                bad.append("%s: level or actor out of range" % w)

    if _shape(bad, d["queue"], "queue", "$.queue"):
        for i, q in enumerate(d["queue"].get("proposals", [])):
            w = "$.queue.proposals[%d]" % i
            if _shape(bad, q, "proposal", w):
                if q.get("id") not in idset:
                    bad.append("%s: not a public note" % w)
                if q.get("brief") is not None and q.get("level") not in brief_levels:
                    bad.append("%s: summary published above brief_levels" % w)
                if not authors_ok and q.get("author"):
                    bad.append("%s: identity published while publish_authors is false" % w)
        for i, q in enumerate(d["queue"].get("review_needed", [])):
            if _shape(bad, q, "review", "$.queue.review_needed[%d]" % i) and q.get("id") not in idset:
                bad.append("$.queue.review_needed[%d]: not a public note" % i)

    _values(bad, (d.get("health") or {}).get("counts"), int, "$.health.counts")
    if _shape(bad, d["health"], "health", "$.health"):
        for i, it in enumerate(d["health"].get("issues", [])):
            if _shape(bad, it, "issue", "$.health.issues[%d]" % i) and it.get("id") not in idset:
                bad.append("$.health.issues[%d]: not a public note" % i)

    for i, f in enumerate(d["features"]):
        w = "$.features[%d]" % i
        if _shape(bad, f, "feature", w):
            if f.get("id") not in idset:
                bad.append("%s: not a public note" % w)
            if f.get("covers") is not None:
                bad.append("%s: feature code paths published" % w)
            src = by_id.get(f.get("id")) or {}
            if src.get("confidentiality") != "open":
                if f.get("card") is not None and src.get("level") not in brief_levels:
                    bad.append("%s: card published above brief_levels" % w)
                if f.get("contract") is not None:
                    bad.append("%s: contract published" % w)
            _items(bad, f.get("relies_on"), str, w + ".relies_on")
            _items(bad, f.get("relied_on_by"), str, w + ".relied_on_by")
            for r in (f.get("relies_on") or []) + (f.get("relied_on_by") or []):
                if r not in idset:
                    bad.append("%s: references a note that is not public" % w)
    for i, g in enumerate(d["gaps"]):
        if _shape(bad, g, "gap", "$.gaps[%d]" % i):
            if g.get("text") is not None:
                bad.append("$.gaps[%d]: gap text published" % i)
            if g.get("feature") is not None and g["feature"] not in idset:
                bad.append("$.gaps[%d]: references a note that is not public" % i)
    for i, t in enumerate(d["trials"]):
        if _shape(bad, t, "trial", "$.trials[%d]" % i) and t.get("id") not in idset:
            bad.append("$.trials[%d]: not a public note" % i)
    for i, pbk in enumerate(d["playbooks"]):
        w = "$.playbooks[%d]" % i
        if _shape(bad, pbk, "playbook", w):
            if pbk.get("id") not in idset:
                bad.append("%s: not a public note" % w)
            if pbk.get("trust") not in ("approved", "reproduced", "unreviewed"):
                bad.append("%s: unknown trust %r" % (w, pbk.get("trust")))
    if d["sessions"]:
        bad.append("local session ledgers published (%d)" % len(d["sessions"]))
    url = d.get("repo_url")
    if url is not None and not re.match(r"^https://github\.com/[\w.-]+/[\w.-]+$", url):
        bad.append("$.repo_url: not a plain GitHub URL")
    return bad


def canonical(d):
    """The graph with its only time-dependent field removed, for build-vs-file comparison."""
    x = dict(d)
    x.pop("generated_at", None)
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true",
                    help="unredacted build for local use — never deploy this")
    ap.add_argument("--out", default=None)
    ap.add_argument("--notes-root")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--verify", metavar="GRAPH_JSON",
                    help="check an existing public graph.json: the closed schema, every redaction rule, "
                         "and (by default) an exact match with a fresh build of the notes; exit 1 on any problem")
    ap.add_argument("--against-source", action="store_true",
                    help="with --verify: rebuild from the notes and require the file to match it exactly "
                         "(apart from generated_at). The default; kept for existing workflows")
    ap.add_argument("--shape-only", action="store_true",
                    help="with --verify: check the file alone, WITHOUT the notes. A file-only check cannot "
                         "see a note relabelled `open` or a changed title, so it is never enough to publish")
    ap.add_argument("--policy", metavar="ROLES_JSON",
                    help="with --shape-only: the governance/roles.json whose publication settings apply "
                         "(default: the strictest settings)")
    args = ap.parse_args(argv)

    if args.verify:
        try:
            d = load_strict(args.verify)
        except (OSError, ValueError) as e:
            print("::error::redaction failed\n  %s" % e)
            return 1
        if args.shape_only and args.against_source:
            print("::error::--shape-only and --against-source contradict each other")
            return 1
        trusted = None
        ctx = None
        if args.shape_only:
            if args.policy:
                try:
                    with open(args.policy, encoding="utf-8") as fh:
                        trusted = dict(DEFAULT_PUBLICATION, **(json.load(fh).get("publication") or {}))
                except (OSError, ValueError, AttributeError) as e:
                    print("::error::cannot read --policy: %s" % e)
                    return 1
        else:
            ctx = mg.Ctx(args.notes_root)
            trusted = dict(DEFAULT_PUBLICATION, **(ctx.policy.get("publication") or {}))
        bad = verify_public(d, trusted)
        if not bad and ctx is not None:
            fresh = build(ctx, public=True)
            if canonical(fresh) != canonical(d):
                bad.append("the file differs from a fresh public build of the notes at this commit")
        if bad:
            print("::error::redaction failed")
            for b in bad:
                print("  " + b)
            return 1
        print("redaction verified%s: %d notes, %d withheld bodies, %d experiments withheld"
              % (" (shape only: the notes were not compared)" if ctx is None else " against the notes",
                 d["stats"]["notes"], d["withheld"]["bodies"], d["withheld"].get("experiments", 0)))
        return 0

    ctx = mg.Ctx(args.notes_root)
    public = not args.full
    data = build(ctx, public=public)

    out = args.out or os.path.join(
        ctx.notes_root, "web", "data", "graph.json" if public else "graph.full.json")
    if os.path.dirname(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)  # a bare filename has no directory (07-F10)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    if not args.quiet:
        s = data["stats"]
        print("atlas: %s build -> %s" % (data["mode"].upper(), os.path.relpath(out, ctx.notes_root)))
        print("  %d notes · %d observations · %d relations (%d dependency) · %d commits"
              % (s["notes"], s["observations"], s["relations"], s["dependencies"], s["commits"]))
        print("  health %d/100 — %s" % (
            data["health"]["score"],
            ", ".join("%s %d" % (k, v) for k, v in data["health"]["counts"].items() if v) or "clean"))
        if public:
            w = data["withheld"]
            print("  REDACTED: %d bodies and %d summary lines withheld, %d restricted notes "
                  "omitted entirely, commit messages withheld"
                  % (w["bodies"], w.get("briefs", 0), w["restricted"]))
            bad = verify_public(data, dict(DEFAULT_PUBLICATION, **(ctx.policy.get("publication") or {})))
            if bad:
                print("  REDACTION FAILED - do not publish:\n    " + "\n    ".join(bad))
                return 1
            leaked = [n["id"] for n in data["nodes"] if n["body"] is not None]
            print("  published in full (confidentiality: open): %s"
                  % (", ".join(leaked) if leaked else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
