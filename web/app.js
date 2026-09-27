/* Memory Atlas
 *
 * Reads one generated file (data/graph.json) and draws it. No backend, no build step, and no
 * layout simulation in the browser: every position is computed by build_atlas.py and baked into
 * the data, so the map opens instantly and looks identical for everyone on the team.
 *
 * WHY IT IS BUILT THIS WAY. Measured three ways, a 1120x760 pane holds about 60 labelled items
 * before labels start colliding, and that ceiling is typographic, not computational - canvas and
 * WebGL do not move it. Drawing 1000 notes at once is not slow, it is illegible: fit-to-view
 * falls to 0.25x and an 11px label renders at under 3px. So the map is a ZOOMABLE WORLD, and it
 * shows one depth at a time:
 *
 *     far     8-9 constellations, however large the corpus gets
 *     middle  one constellation opened, at most 32 notes (CAP in build_atlas.py)
 *     near    one note, its neighbours drawn in around it
 *
 * Every cluster disc physically contains its members, so going deeper is a real camera move into
 * a real place rather than a screen swap. That is what makes the motion worth having: it carries
 * the sense of where you came from, which a hard cut destroys.
 */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const LEVELS = ["L0", "L1", "L2", "L3"];
  const TAU = Math.PI * 2;

  const state = {
    data: null, nodes: [], links: [], byId: new Map(),
    arrangement: "area", stack: [], selected: null,
    colourMode: "level", labels: true, query: "", hiddenLevels: new Set(),
    lastVisit: null, motion: "full", ambient: true,
    svg: null, world: null, zoom: null, cam: d3.zoomIdentity,
    width: 0, height: 0, view: null, raf: null, t0: performance.now(),
    clusterIndex: new Map(), homeOf: new Map(),
  };

  /* ───────────────────────────── helpers ───────────────────────────── */

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function ago(iso) {
    if (!iso) return "unknown";
    const then = new Date(iso.length <= 10 ? iso + "T12:00:00Z" : iso);
    if (isNaN(then)) return "unknown";
    const s = (Date.now() - then.getTime()) / 1000;
    if (s < 90) return "just now";
    const m = s / 60, h = m / 60, d = h / 24;
    if (m < 60) return `${Math.round(m)} min ago`;
    if (h < 24) return `${Math.round(h)} hr ago`;
    if (d < 31) return `${Math.round(d)} days ago`;
    if (d < 365) return `${Math.round(d / 30.4)} months ago`;
    return `${(d / 365).toFixed(1)} years ago`;
  }

  const cssVar = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#8a867c";
  const levelColour = (l) => cssVar("--" + String(l).toLowerCase());

  function nodeColour(n) {
    if (state.colourMode === "level") return levelColour(n.level);
    const d = n.age_days ?? 999;
    if (d <= 3) return cssVar("--l1");
    if (d <= 14) return cssVar("--l0");
    if (d <= 45) return cssVar("--l2");
    if (d <= 120) return cssVar("--l3");
    return cssVar("--ink-3");
  }

  const briefWithheld = (n) => !n.brief && state.data.mode === "public" &&
    !((state.data.publication?.brief_levels || ["L0"]).includes(n.level));
  const levelLabel = (l) => (state.data.levels[l] && state.data.levels[l].label) || l;
  const tick = (l) =>
    `<span class="tick" data-level="${esc(l)}" style="background:${levelColour(l)}"
      title="${esc(l)}, ${esc(levelLabel(l))}"></span>`;

  /* ───────────────────────────── small motions ───────────────────────────── */

  // Numbers count up to their value. The final text is written first, so anything reading the
  // page (a screen reader, a test, a copy-paste) sees the true number whatever the animation does.
  function countUp(root) {
    if (!root || !dur(1)) return;
    root.querySelectorAll("[data-count]").forEach((el) => {
      const to = +el.dataset.count;
      if (!isFinite(to) || to <= 0) return;
      el.textContent = String(to);
      const t0 = performance.now(), ms = 900;
      const step = (now) => {
        const p = Math.min(1, (now - t0) / ms);
        const e = 1 - Math.pow(1 - p, 3);
        el.textContent = String(Math.round(to * e));
        if (p < 1) requestAnimationFrame(step); else el.textContent = String(to);
      };
      requestAnimationFrame(step);
    });
  }

  // The briefing arrives a word at a time. Each word is wrapped in place, so the markup and the
  // text it reads out stay exactly what renderBriefing wrote.
  function revealWords(root) {
    if (!root || !dur(1)) return;
    let i = 0;
    const walk = (node) => {
      [...node.childNodes].forEach((ch) => {
        if (ch.nodeType === 3) {
          const parts = ch.textContent.split(/(\s+)/);
          const frag = document.createDocumentFragment();
          parts.forEach((p) => {
            if (!p) return;
            if (/^\s+$/.test(p)) { frag.appendChild(document.createTextNode(p)); return; }
            const s = document.createElement("span");
            s.className = "w"; s.style.setProperty("--i", i++); s.textContent = p;
            frag.appendChild(s);
          });
          ch.replaceWith(frag);
        } else if (ch.nodeType === 1) walk(ch);
      });
    };
    walk(root);
  }

  // A pill that moves under the active button of a segmented control.
  function moveThumb(group, activeSel, cls) {
    if (!group) return;
    let th = group.querySelector("." + cls);
    if (!th) {
      th = document.createElement("span");
      th.className = cls; th.setAttribute("aria-hidden", "true");
      group.prepend(th);
      group.classList.add(cls === "tab-thumb" ? "has-thumb" : "has-thumb");
    }
    const b = group.querySelector("button" + activeSel);
    if (!b) return;
    th.style.width = b.offsetWidth + "px";
    th.style.transform = "translateX(" + b.offsetLeft + "px)";
  }

  /* ───────────────────────────── motion budget ───────────────────────────── */

  const reduced = () => window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // One switch the whole file asks. Reduced motion is not "faster", it is "instant": the person
  // asked the operating system not to animate, and a 150ms version of the same movement is still
  // movement.
  const dur = (ms) => (state.motion === "reduced" ? 0 : ms);
  const ambientOn = () => state.motion !== "reduced" && state.ambient;

  /* ───────────────────────────── theme ───────────────────────────── */

  const systemDark = () => !window.matchMedia
    || !window.matchMedia("(prefers-color-scheme: light)").matches;
  const currentTheme = () =>
    document.documentElement.getAttribute("data-theme") || (systemDark() ? "dark" : "light");

  function setTheme(next) {
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("atlas-theme", next); } catch (e) { /* private mode */ }
    $("#theme-btn").setAttribute("aria-label",
      next === "dark" ? "Switch to the light chart" : "Switch to the dark chart");
    paint();
  }

  // Which build to draw. Defaults to the deployed one; `?data=` points at another file beside
  // it, which is how a per-project memory or an older build is previewed. Same-origin relative
  // paths only: a URL from the query string is not a place to go fetching from.
  function dataFile() {
    const raw = new URLSearchParams(location.search).get("data");
    if (!raw) return "data/graph.json";
    if (!/^data\/[A-Za-z0-9._-]+\.json$/.test(raw)) return "data/graph.json";
    return raw;
  }

  /* ───────────────────────────── boot ───────────────────────────── */

  async function boot() {
    let data;
    try {
      const res = await fetch(dataFile(), { cache: "no-store" });
      if (!res.ok) throw new Error(`the server returned ${res.status}`);
      data = await res.json();
    } catch (err) {
      $("#boot").innerHTML =
        `<div class="boot-plot" style="grid-column:1/-1;max-width:56ch">
           <h2 style="font-family:var(--serif);font-weight:500">The map could not load</h2>
           <p style="color:var(--ink-2);line-height:1.6">
             <code>data/graph.json</code> was not readable: ${esc(err.message)}.</p>
           <p style="color:var(--ink-2);line-height:1.6">Generate it from the repository root:<br>
             <code>uv run -q --script scripts/build_atlas.py</code></p>
           <p style="color:var(--ink-3);line-height:1.6">Opening this file straight from disk will
             also fail, because browsers block <code>fetch</code> on <code>file://</code>. Serve
             the folder instead:<br><code>python -m http.server -d web 8080</code></p>
         </div>`;
      $("#boot").removeAttribute("aria-hidden");
      return;
    }

    if (!data.arrangements) {
      $("#boot").innerHTML = `<div class="boot-plot" style="grid-column:1/-1;max-width:56ch">
        <h2 style="font-family:var(--serif);font-weight:500">This data file is too old</h2>
        <p style="color:var(--ink-2);line-height:1.6">It has no <code>arrangements</code>, which
        this version of the map needs. Rebuild it:<br>
        <code>uv run -q --script scripts/build_atlas.py</code></p></div>`;
      $("#boot").removeAttribute("aria-hidden");
      return;
    }

    state.data = data;
    state.motion = reduced() ? "reduced" : "full";
    state.nodes = data.nodes.map((n) => ({ ...n }));
    state.byId = new Map(state.nodes.map((n) => [n.id, n]));
    state.links = data.edges
      .filter((e) => state.byId.has(e.source) && state.byId.has(e.target))
      .map((e) => ({ ...e }));

    state.nodes.forEach((n) => { n._out = []; n._in = []; });
    state.links.forEach((l) => {
      state.byId.get(l.source)._out.push(l);
      state.byId.get(l.target)._in.push(l);
    });
    state.nodes.forEach((n) => { n._deg = n._out.length + n._in.length; });

    indexArrangements();
    readLastVisit();
    renderHeader();
    renderBriefing();
    renderKey();
    renderChanges();
    renderNeeds();
    renderGaps();
    renderHelp();
    buildStage();
    wireUI();
    if (!routeFromHash()) goTo([], { animate: false });
    window.addEventListener("hashchange", () => routeFromHash());
    startAmbient();

    $("#boot").classList.add("gone");
    setTimeout(() => { const b = $("#boot"); if (b) b.style.display = "none"; }, 400);
  }

  /* ─────────────── the two arrangements, indexed for lookup ─────────────── */

  function indexArrangements() {
    for (const kind of ["area", "time"]) {
      const a = state.data.arrangements[kind];
      if (!a) continue;
      const walk = (c, parent) => {
        c._kind = kind; c._parent = parent || null;
        state.clusterIndex.set(kind + "|@|" + c.id, c);
        (c.children || []).forEach((ch) => walk(ch, c));
        (c.members || []).forEach((id) => {
          state.homeOf.set(kind + "|@|" + id, c);
        });
      };
      a.clusters.forEach((c) => walk(c, null));
    }
  }

  const arrangement = () => state.data.arrangements[state.arrangement];
  const cluster = (id) => state.clusterIndex.get(state.arrangement + "|@|" + id);
  const homeOf = (nodeId) => state.homeOf.get(state.arrangement + "|@|" + nodeId);

  // A cluster's absolute position: children sit inside their parent's disc, so the world is one
  // continuous space and going deeper is a camera move rather than a scene change.
  function worldOf(c) {
    let x = 0, y = 0, scale = 1, p = c;
    const chain = [];
    while (p) { chain.unshift(p); p = p._parent; }
    for (const link of chain) {
      x += link.x * scale;
      y += link.y * scale;
      if (link !== chain[chain.length - 1]) scale *= 0.62;
    }
    return { x, y, r: c.r * scale };
  }

  // Members live inside their cluster's disc, at the local unit positions the builder computed.
  // The spread is an ELLIPSE matching the pane, not a circle: a pane is 1.5 times wider than it
  // is tall, and packing notes into a circle threw that room away and made the labels collide.
  const paneAspect = () =>
    Math.max(1, Math.min(1.95, state.width / Math.max(1, state.height)));

  function memberWorld(c, id) {
    const w = worldOf(c);
    const p = (c.pos && c.pos[id]) || [0, 0];
    const a = paneAspect();
    return { x: w.x + p[0] * w.r * 0.92 * a, y: w.y + p[1] * w.r * 0.92, parent: w };
  }

  // Cartographic label placement: walk the notes in order of importance and give a label to
  // every one whose box is still clear. The rest become minor and appear when the camera is
  // close enough to read them. This is measured against the framing the camera is about to
  // take, not against world units, because a label does not scale with the map.
  function thinLabels(notes, k) {
    const placed = [], keep = new Set();
    const order = [...notes].sort((a, b) =>
      (b.n.observations + b.n._deg * 3 + (30 - Math.min(30, b.n.age_days ?? 30)))
      - (a.n.observations + a.n._deg * 3 + (30 - Math.min(30, a.n.age_days ?? 30))));
    // Every note's own mark is an obstacle too: a label is just as unreadable sitting on top of
    // a neighbouring circle as on top of a neighbouring label.
    // A mark blocks a label only where the CIRCLE actually is. Using each circle's bounding
    // square over-blocked by its corners and left nineteen of twenty-four notes unnamed.
    const marks = notes.map((d) => ({ id: d.n.id, cx: d.x * k, cy: d.y * k, r: d.r * k + 2 }));
    const hitsCircle = (b, x, y, w, h) => {
      const nx = Math.max(x, Math.min(b.cx, x + w));
      const ny = Math.max(y, Math.min(b.cy, y + h));
      return (nx - b.cx) ** 2 + (ny - b.cy) ** 2 < b.r * b.r;
    };
    for (const d of order) {
      const text = trim(d.n.title, 20);
      const w = text.length * 5.6, h = 13;
      const x = d.x * k - w / 2, y = d.y * k + d.r * k + 3;
      const onLabel = placed.some((b) =>
        x < b.x + b.w + 3 && x + w + 3 > b.x && y < b.y + b.h + 2 && y + h + 2 > b.y);
      const onMark = marks.some((b) => b.id !== d.n.id && hitsCircle(b, x, y, w, h));
      if (!onLabel && !onMark) {
        placed.push({ x, y, w, h });
        keep.add(d.n.id);
      }
    }
    return keep;
  }

  // Sized from the room available per note, not as a fixed fraction of the parent. A fixed
  // fraction meant twenty-four notes packed shoulder to shoulder with nowhere to put a label.
  function memberRadius(n, hostR, count, aspect) {
    const unit = Math.sqrt((hostR * 0.92 * aspect) * (hostR * 0.92) / Math.max(1, count));
    const weight = 0.17 + 0.09 * Math.min(2.2, Math.sqrt(Math.max(1, n.observations)) / 2.6);
    return Math.max(2.2, Math.min(unit * 0.42, unit * weight * 2));
  }

  /* ─────────────────── since you last looked ─────────────────── */

  function readLastVisit() {
    try {
      const raw = localStorage.getItem("atlas-last-visit");
      state.lastVisit = raw ? new Date(raw) : null;
      if (state.lastVisit && isNaN(state.lastVisit)) state.lastVisit = null;
      localStorage.setItem("atlas-last-visit", new Date().toISOString());
    } catch (e) {
      state.lastVisit = null;
    }
  }

  const isNew = (iso) => {
    if (!state.lastVisit || !iso) return false;
    const t = new Date(iso);
    return !isNaN(t) && t > state.lastVisit;
  };

  /* ─────────────────── the briefing line ─────────────────── */

  function renderBriefing() {
    const q = state.data.queue;
    const open = q.proposals.filter((p) => (p.status || "open") === "open");
    const flagged = q.review_needed;
    const fresh = state.data.activity.filter((a) => isNew(a.at));
    const parts = [];

    if (open.length) {
      const oldest = Math.max(...open.map((p) => p.age_days ?? 0));
      parts.push(`<b>${open.length} proposal${open.length === 1 ? " is" : "s are"} waiting</b>`
        + (oldest > 3 ? `, the oldest for ${oldest} days` : ""));
    }
    if (flagged.length) {
      parts.push(`<b>${flagged.length} note${flagged.length === 1 ? "" : "s"} need${
        flagged.length === 1 ? "s" : ""} re-reading</b> after a planning change`);
    }

    let sentence = parts.length ? parts.join(", and ") + "."
      : `<span class="calm">Nothing is waiting on a person.</span>`;

    if (state.lastVisit) {
      sentence += fresh.length
        ? ` ${fresh.length} change${fresh.length === 1 ? "" : "s"} landed since you last looked.`
        : " Nothing has changed since you last looked.";
    } else {
      sentence += ` ${state.data.activity.length} change${
        state.data.activity.length === 1 ? " is" : "s are"} on record.`;
    }

    $("#briefing").innerHTML = sentence;
    revealWords($("#briefing"));
    $("#since").textContent = state.lastVisit
      ? `Last visit ${ago(state.lastVisit.toISOString())}`
      : "First visit from this browser";
    $("#since").title = "Kept in this browser only. It is not shared and not sent anywhere.";
  }

  /* ───────────────────────────── header ───────────────────────────── */

  function renderHeader() {
    const d = state.data, s = d.stats;
    $("#brand-sub").textContent =
      d.mode === "public" ? `${d.project}, summary view` : `${d.project}, full view`;

    $("#stats").innerHTML = [
      [s.notes, "notes"], [s.observations, "facts"], [s.relations, "links"],
      [s.dependencies, "dependencies"], [s.authors, "authors"],
    ].map(([v, k]) => `<p class="stat"><b data-count="${v}">${v}</b><span>${k}</span></p>`).join("");
    countUp($("#stats"));

    const at = d.source_commit_at || d.generated_at;
    const stale = at && (Date.now() - new Date(at).getTime()) > 48 * 3600e3;
    const f = $("#freshness");
    f.classList.toggle("stale", !!stale);
    f.innerHTML = `Built ${esc(ago(at))} <span class="sha">${esc(d.source_commit)}</span>`;
    f.title = stale
      ? "Older than two days. The rebuild may not have run."
      : `Generated from commit ${d.source_commit}.`;
  }

  function renderKey() {
    $("#key").innerHTML = `<p class="key-title">Who may change a note</p>` +
      LEVELS.filter((l) => state.data.levels[l]).map((l) => {
        const m = state.data.levels[l];
        const n = state.nodes.filter((x) => x.level === l).length;
        if (!n) {
          return `<span class="lg empty" title="${esc(m.may_change.join(" or "))} may change this.">
            <i style="background:${levelColour(l)}"></i><em>${l}</em> ${esc(m.label)}
            <small>none here</small></span>`;
        }
        return `<button class="lg" data-level="${l}" aria-pressed="true"
          title="${esc(m.may_change.join(" or "))} may change this. Select to hide it.">
          <i style="background:${levelColour(l)}"></i><em>${l}</em> ${esc(m.label)}
          <small>${n}</small></button>`;
      }).join("") + `<p class="mag-key">
        <i style="width:5px;height:5px"></i><i style="width:9px;height:9px"></i>
        <i style="width:15px;height:15px"></i>
        <span style="margin-left:4px">size is how much it holds</span></p>`;

    $$(".lg[data-level]").forEach((el) => el.addEventListener("click", () => {
      const l = el.dataset.level;
      const hide = !state.hiddenLevels.has(l);
      hide ? state.hiddenLevels.add(l) : state.hiddenLevels.delete(l);
      el.setAttribute("aria-pressed", String(!hide));
      render();
    }));
  }

  function renderHelp() {
    $("#help-levels").innerHTML = LEVELS.filter((l) => state.data.levels[l]).map((l) => {
      const m = state.data.levels[l];
      return `<li><b style="color:${levelColour(l)}">${l}, ${esc(m.label)}.</b>
        Changed by ${esc(m.may_change.join(" or "))}.</li>`;
    }).join("");

    const w = state.data.withheld || {};
    $("#help-redaction").textContent = state.data.mode === "public"
      ? `This build withholds the contents of ${w.bodies || 0} notes and omits `
        + `${w.restricted || 0} restricted notes completely, along with every commit message. `
        + `You can see what exists, who changed it and how it connects, without the text itself. `
        + `To read the notes, run build_atlas.py --full on your own machine.`
      : "This is the full local build. Nothing is withheld, so do not deploy this file.";
  }

  /* ───────────────────────────── the stage ───────────────────────────── */

  function buildStage() {
    const svg = d3.select("#graph");
    state.svg = svg;
    measure();
    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    const bloom = defs.append("filter").attr("id", "bloom")
      .attr("x", "-70%").attr("y", "-70%").attr("width", "240%").attr("height", "240%");
    bloom.append("feGaussianBlur").attr("stdDeviation", 3.4);

    // a small, bright glow for things made of light (packets, the pulse)
    const glow = defs.append("filter").attr("id", "glow")
      .attr("x", "-200%").attr("y", "-200%").attr("width", "500%").attr("height", "500%");
    glow.append("feGaussianBlur").attr("stdDeviation", 1.6).attr("result", "b");
    const gm = glow.append("feMerge");
    gm.append("feMergeNode").attr("in", "b");
    gm.append("feMergeNode").attr("in", "SourceGraphic");

    // a region is lit from its centre: the fill is a gradient of two paper steps, themed by CSS
    const disc = defs.append("radialGradient").attr("id", "disc-fill").attr("cx", "50%").attr("cy", "42%").attr("r", "62%");
    disc.append("stop").attr("offset", "0%").attr("class", "df-a");
    disc.append("stop").attr("offset", "100%").attr("class", "df-b");

    // The plate's own tooth. A real paper grain sits under everything at an opacity you only
    // notice when it is missing; it is what stops large flat fills reading as a screen.
    const grain = defs.append("filter").attr("id", "grain");
    grain.append("feTurbulence").attr("type", "fractalNoise")
      .attr("baseFrequency", "0.82").attr("numOctaves", "3").attr("stitchTiles", "stitch");
    grain.append("feColorMatrix").attr("type", "saturate").attr("values", "0");

    const field = svg.append("g").attr("class", "field").attr("pointer-events", "none");
    field.append("rect").attr("class", "grain").attr("width", "100%").attr("height", "100%")
      .attr("filter", "url(#grain)");

    defs.append("marker").attr("id", "arrow").attr("viewBox", "0 -4 9 8")
      .attr("refX", 8).attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto")
      .append("path").attr("d", "M0,-3L8,0L0,3").attr("fill", "currentColor");

    const world = svg.append("g").attr("class", "world");
    state.world = world;
    world.append("g").attr("class", "ghosts");     // the level above, kept faintly for orientation
    world.append("g").attr("class", "links");
    world.append("g").attr("class", "packets").attr("pointer-events", "none");
    world.append("g").attr("class", "pulses");
    world.append("g").attr("class", "clusters");
    world.append("g").attr("class", "notes");

    state.zoom = d3.zoom().scaleExtent([0.04, 14])
      .on("zoom", (ev) => {
        state.cam = ev.transform;
        world.attr("transform", ev.transform);
        onCameraMoved();
      });
    svg.call(state.zoom).on("dblclick.zoom", null);

    svg.on("click", (ev) => { if (ev.target === svg.node()) back(); });
  }

  function measure() {
    const box = $("#atlas").getBoundingClientRect();
    state.width = Math.max(320, box.width);
    state.height = Math.max(240, box.height);
  }

  /* ───────────────────────── what is on screen ───────────────────────── */

  // The one invariant this whole file exists to keep: never more than `cap` labelled things.
  function computeView() {
    const a = arrangement();
    const cap = a.cap || 54;
    const depth = state.stack.length;
    const hidden = state.hiddenLevels;
    const visibleNode = (n) => !hidden.has(n.level);

    if (depth === 0) {
      return {
        depth: 0,
        clusters: a.clusters.map((c) => ({ c, w: worldOf(c), open: false })),
        notes: [], ghosts: [], host: null, cap,
        edges: a.edges.map((e) => ({
          a: worldOf(cluster(e.source)), b: worldOf(cluster(e.target)),
          weight: e.weight, dependency: e.dependency, id: e.source + ">" + e.target,
        })).filter((e) => e.a && e.b),
      };
    }

    const host = cluster(state.stack[state.stack.length - 1]);
    if (!host) return computeViewRoot();

    const siblings = (host._parent ? host._parent.children : a.clusters)
      .filter((c) => c.id !== host.id)
      .map((c) => ({ c, w: worldOf(c), open: false, dim: true }));

    if (host.children && host.children.length) {
      return {
        depth, host,
        clusters: host.children.map((c) => ({ c, w: worldOf(c), open: false }))
          .concat(siblings),
        notes: [], ghosts: [], edges: [], cap,
      };
    }

    const shown = (host.members || []).map((id) => state.byId.get(id)).filter(Boolean)
      .filter(visibleNode).slice(0, cap);
    const count = shown.length;
    const notes = shown
      .map((n) => {
        const p = memberWorld(host, n.id);
        return { n, x: p.x, y: p.y,
                 r: memberRadius(n, p.parent.r, count, paneAspect()), host };
      });

    const inside = new Set(notes.map((d) => d.n.id));
    const pos = new Map(notes.map((d) => [d.n.id, d]));
    const edges = [];
    for (const l of state.links) {
      const s = pos.get(l.source), t = pos.get(l.target);
      if (s && t) edges.push({ a: s, b: t, dependency: l.dependency, type: l.type,
                               id: l.source + ">" + l.target + ">" + l.type });
    }
    // relations that leave this constellation become short stubs pointing outward, so a note
    // never looks unconnected just because its partner is off screen
    const stubs = [];
    for (const d of notes) {
      const out = [...d.n._out, ...d.n._in].filter((l) =>
        !inside.has(l.source) || !inside.has(l.target));
      if (out.length) stubs.push({ d, n: out.length });
    }

    const kBase = frameScale(worldOf(host));
    // The container ring is the host itself. Drawing the neighbouring groups here instead put
    // a dim sibling's edge around the notes, which reads as a boundary that is not theirs.
    const ring = [{ c: host, w: worldOf(host), open: true, container: true }];
    return { depth, host, clusters: ring, notes, edges, stubs, ghosts: [], cap,
             kBase, labelled: thinLabels(notes, kBase) };
  }

  const LEAF_FILL = 1.06;   // a constellation of notes should nearly fill the pane, not float in it
  const GROUP_FILL = 1.5;

  // Room reserved, in screen pixels, for the name above a disc and the level bar below it.
  // Without it the camera framed the disc edge to edge and cut the name off the top.
  const CHROME_ROOM = 96;

  const frameScale = (w, fill = LEAF_FILL) =>
    Math.min(14, Math.max(0.04,
      (Math.min(state.width, state.height) - CHROME_ROOM) / (w.r * 2 * fill)));

  function computeViewRoot() { state.stack = []; return computeView(); }

  /* ───────────────────────── drawing ───────────────────────── */

  function render(opts = {}) {
    const view = state.view = computeView();
    if (state.world && dur(1)) {
      // re-trigger the arrival wave for this level
      const w = state.world.node();
      w.classList.remove("ignite");
      void w.getBoundingClientRect();
      w.classList.add("ignite");
      clearTimeout(state.igniteT);
      state.igniteT = setTimeout(() => w.classList.remove("ignite"), 1600);
    }
    const t = (sel) => (dur(1) ? sel.transition().duration(opts.fast ? 240 : 520)
      .ease(d3.easeCubicOut) : sel);

    drawClusters(view, t);
    drawNotes(view, t);
    drawEdges(view, t);
    rescaleChrome();
    drawSelection();
    renderBreadcrumb(view);
    renderScope(view);
  }

  function drawClusters(view, t) {
    const sel = state.world.select(".clusters").selectAll("g.cl")
      .data(view.clusters, (d) => d.c.id);

    // An element on its way out must stop being an element straight away: still clickable and
    // still announced to a screen reader while it fades is a thing that is not there.
    // Removal must not depend on a transition finishing. A fade that is interrupted - by fast
    // navigation, a background tab, anything - left the old level's marks on screen on top of
    // the new one, so the fade is the nice version and the timeout is the guarantee.
    const goneC = sel.exit().classed("leaving", true)
      .attr("aria-hidden", "true").attr("tabindex", null).style("pointer-events", "none");
    if (dur(1)) {
      goneC.transition().duration(300).style("opacity", 0).remove();
      // Only sweep what is STILL leaving. Navigating back within the fade revives an element,
      // and a blind timeout then deleted a live one - which emptied the whole map.
      setTimeout(() => goneC.filter(function () {
        return this.classList.contains("leaving");
      }).remove(), 420);
    } else {
      goneC.remove();
    }

    const enter = sel.enter().append("g").attr("class", "cl");
    // Everything drawn goes in a body that can spring on hover and ignite on arrival; the text
    // stays outside it, so a name is never scaled.
    const body = enter.append("g").attr("class", "cl-body");
    body.append("circle").attr("class", "cl-halo");
    body.append("circle").attr("class", "cl-disc");
    body.append("g").attr("class", "cl-tissue").attr("aria-hidden", "true");
    body.append("circle").attr("class", "cl-edge").attr("pointer-events", "none");
    body.append("circle").attr("class", "cl-tick").attr("fill", "none")
      .attr("pointer-events", "none");
    body.append("circle").attr("class", "cl-flag");
    // Text goes in a counter-scaled group. SVG scales EVERYTHING under a transform, text
    // included, so a label drawn at 14 units renders at 14k pixels: at the framing zoom the
    // names came out three times their size and swallowed the map. Anything meant to be read
    // lives in here and is sized in screen pixels.
    const chrome = enter.append("g").attr("class", "chrome");
    chrome.append("text").attr("class", "cl-name").attr("text-anchor", "middle");
    chrome.append("text").attr("class", "cl-count").attr("text-anchor", "middle");
    chrome.append("g").attr("class", "cl-mix");

    // Anything the join hands back is ALIVE, even if it was fading out a moment ago. Without
    // this, navigating in and straight back out reused a half-removed element and left a
    // constellation on screen that was invisible and could not be clicked - and its scheduled
    // removal still fired afterwards.
    sel.interrupt().classed("leaving", false)
      .attr("aria-hidden", null).style("pointer-events", null).style("opacity", null);

    enter.each(function (d, i) { this.style.setProperty("--i", i); });
    const all = enter.merge(sel);
    all.attr("data-id", (d) => d.c.id)
      .classed("dim", (d) => !!d.dim)
      .classed("container", (d) => !!d.container)
      .attr("tabindex", (d) => (d.dim || d.container ? -1 : 0))
      .attr("role", "button")
      .attr("aria-label", (d) =>
        `${d.c.label}, ${d.c.count} notes${d.c.review_needed ? `, ${d.c.review_needed} need re-reading` : ""}`)
      .attr("transform", (d) => `translate(${d.w.x},${d.w.y})`);

    all.style("opacity", (d) => (d.dim ? 0.20 : d.container ? 0.5 : 1));

    all.select(".cl-halo").attr("r", (d) => d.w.r).attr("fill", (d) => dominant(d.c))
      .attr("filter", "url(#bloom)");
    all.select(".cl-disc").attr("r", (d) => d.w.r)
      .attr("stroke", (d) => dominant(d.c));
    // draw the contents as tissue, at their real relative positions
    all.select(".cl-tissue").each(function (d) {
      const pts = d.c.sample || [];
      const spread = d.w.r * 0.84;
      const rr = Math.max(1.0, Math.min(3.0, d.w.r / 26));
      const sel = d3.select(this).selectAll("circle").data(pts);
      sel.enter().append("circle").merge(sel)
        .attr("cx", (p) => p[0] * spread).attr("cy", (p) => p[1] * spread).attr("r", rr)
        .attr("fill", (p) => levelColour(LEVELS[p[2] || 0]));
      sel.exit().remove();
    });
    all.select(".cl-edge").attr("r", (d) => d.w.r - 3.5);
    all.select(".cl-tick").attr("r", (d) => d.w.r + 5).attr("stroke", (d) => dominant(d.c));
    all.select(".cl-flag")
      .attr("r", (d) => d.w.r + 7)
      .style("display", (d) => (d.c.review_needed ? null : "none"));
    all.select(".cl-name").text((d) => d.c.label);
    all.select(".cl-count").text((d) => d.c.count);

    all.select(".cl-mix")
      .each(function (d) {
        // Only the segments and their colours here. The WIDTH depends on the camera and is set
        // in rescaleChrome: computed here it used whatever scale the camera happened to be at
        // when the draw ran, which at first paint is the identity, and every bar came out more
        // than twice the width of its own disc.
        const g = d3.select(this);
        const s = g.selectAll("path").data(LEVELS.filter((l) => d.c.levels[l]).map((l) => ({ l })));
        s.enter().append("path").merge(s).attr("stroke", (m) => levelColour(m.l));
        s.exit().remove();
      });

    all.on("click", (ev, d) => {
        ev.stopPropagation();
        if (d.container) { back(); return; }
        if (!d.dim) ripple(d.w.x, d.w.y, d.w.r);
        d.dim ? up(d.c) : enter_(d.c);
      })
      .on("keydown", (ev, d) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); enter_(d.c); }
      })
      .on("pointerenter", (ev, d) => showClusterHover(ev, d))
      .on("pointermove", positionHover)
      .on("pointerleave", hideHover);
  }

  function dominant(c) {
    let best = "L0", n = -1;
    for (const l of LEVELS) if ((c.levels[l] || 0) > n) { n = c.levels[l] || 0; best = l; }
    return levelColour(best);
  }

  function drawNotes(view, t) {
    const sel = state.world.select(".notes").selectAll("g.nd")
      .data(view.notes, (d) => d.n.id);

    const goneN = sel.exit().classed("leaving", true)
      .attr("aria-hidden", "true").attr("tabindex", null).style("pointer-events", "none");
    if (dur(1)) {
      const h = view.host ? worldOf(view.host) : { x: 0, y: 0 };
      goneN.transition().duration(260).style("opacity", 0)
        .attr("transform", `translate(${h.x},${h.y}) scale(0.85)`).remove();
      setTimeout(() => goneN.filter(function () {
        return this.classList.contains("leaving");
      }).remove(), 380);
    } else {
      goneN.remove();
    }

    const enter = sel.enter().append("g").attr("class", "nd").style("opacity", 0);
    enter.append("circle").attr("class", "nd-flag");
    // the body springs when pointed at; the label lives outside it and never scales
    const nb = enter.append("g").attr("class", "nd-body");
    nb.append("circle").attr("class", "nd-bloom");
    nb.append("path").attr("class", "proc").attr("pointer-events", "none");
    nb.append("circle").attr("class", "nd-core");
    nb.append("circle").attr("class", "nd-shine").attr("pointer-events", "none");
    nb.append("circle").attr("class", "nd-rim").attr("pointer-events", "none");
    enter.append("circle").attr("class", "nd-breath");
    enter.append("path").attr("class", "reticle");
    enter.append("g").attr("class", "lbl")
      .append("text").attr("class", "nd-label").attr("text-anchor", "middle");

    // UNFURL: new notes are born at the centre of the constellation that contains them and
    // travel out to their place, so opening a cluster reads as its contents emerging from it.
    const host = view.host ? worldOf(view.host) : { x: 0, y: 0 };
    // Never from scale(0): a mark that grows from nothing reads as appearing out of
    // nowhere. Even a deflated balloon has a shape.
    enter.attr("transform", `translate(${host.x},${host.y}) scale(0.85)`);
    // Opacity is set here, not by the transition. A transition that is interrupted, or that
    // never runs, left every note on the map permanently invisible: the unfurl should decide
    // WHERE a note arrives from, never WHETHER it is there.
    enter.style("opacity", 1);

    sel.interrupt().classed("leaving", false)
      .attr("aria-hidden", null).style("pointer-events", null);

    const all = enter.merge(sel);
    all.attr("data-id", (d) => d.n.id)
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", (d) => `${d.n.title}, ${d.n.level}, ${d.n.observations} facts`)
      .classed("flagged", (d) => !!d.n.review_needed)
      .classed("fresh", (d) => (d.n.age_days ?? 999) <= 7);

    if (dur(1)) {
      all.transition().duration(620).delay((d, i) => Math.min(i * 11, 360))
        .ease(d3.easeCubicOut)
        .attr("transform", (d) => `translate(${d.x},${d.y}) scale(1)`);
    } else {
      all.attr("transform", (d) => `translate(${d.x},${d.y}) scale(1)`).style("opacity", 1);
    }

    all.select(".nd-core").attr("r", (d) => d.r).attr("fill", (d) => nodeColour(d.n));
    // a specular highlight, so a mark reads as an object lit from above-left, not a flat dot
    all.select(".nd-shine").attr("r", (d) => d.r * 0.26)
      .attr("cx", (d) => -d.r * 0.36).attr("cy", (d) => -d.r * 0.4);
    all.select(".nd-rim").attr("r", (d) => d.r + 2.5);
    // Processes: short tapered strokes leaving the cell for each relation whose other end is not
    // on this plate. A cell drawn with none of its connections reads as isolated, which is
    // usually a lie about the data.
    const inHere = new Set(view.notes.map((x) => x.n.id));
    all.select(".proc").attr("d", (d) => {
      const away = [...d.n._out, ...d.n._in]
        .filter((l) => !inHere.has(l.source) || !inHere.has(l.target));
      if (!away.length) return null;
      const n = Math.min(away.length, 6);
      const base = (d.n.id.charCodeAt(0) + d.n.id.length * 7) % 360;
      let out = "";
      for (let i = 0; i < n; i++) {
        const a = ((base + i * (360 / n) + 18) * Math.PI) / 180;
        const r0 = d.r + 1.5, r1 = d.r + 7 + (i % 2) * 3;
        out += `M${(Math.cos(a) * r0).toFixed(2)},${(Math.sin(a) * r0).toFixed(2)}`
             + `L${(Math.cos(a) * r1).toFixed(2)},${(Math.sin(a) * r1).toFixed(2)}`;
      }
      return out;
    });
    all.select(".nd-bloom").attr("r", (d) => d.r).attr("fill", (d) => nodeColour(d.n))
      .attr("filter", "url(#bloom)");
    all.select(".nd-breath").attr("r", (d) => d.r + 4).attr("stroke", (d) => nodeColour(d.n));
    all.select(".nd-flag").attr("r", (d) => d.r + 5);
    all.select(".reticle").attr("d", (d) => reticlePath(d.r + 9));
    const keep = view.labelled || new Set(view.notes.map((d) => d.n.id));
    all.classed("minor", (d) => !keep.has(d.n.id));
    all.select(".nd-label")
      .style("display", state.labels ? null : "none")
      .text((d) => trim(d.n.title, 20));
    state.world.attr("data-kbase", view.kBase || 1);

    all.on("click", (ev, d) => { ev.stopPropagation(); select(d.n.id); })
      .on("keydown", (ev, d) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(d.n.id); }
      })
      .on("pointerenter", (ev, d) => showHover(ev, d.n))
      .on("pointermove", positionHover)
      .on("pointerleave", hideHover);
  }

  const trim = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));

  function reticlePath(r) {
    const g = r * 0.42;
    return [
      `M${-r},${-r + g}L${-r},${-r}L${-r + g},${-r}`,
      `M${r - g},${-r}L${r},${-r}L${r},${-r + g}`,
      `M${r},${r - g}L${r},${r}L${r - g},${r}`,
      `M${-r + g},${r}L${-r},${r}L${-r},${r - g}`,
    ].join(" ");
  }

  function drawEdges(view, t) {
    const data = view.depth === 0
      ? view.edges.map((e) => ({ ...e, key: e.id }))
      : view.edges.map((e) => ({ a: { x: e.a.x, y: e.a.y }, b: { x: e.b.x, y: e.b.y },
                                 sid: e.a.n && e.a.n.id, tid: e.b.n && e.b.n.id,
                                 dependency: e.dependency, weight: 1, key: e.id }));

    const sel = state.world.select(".links").selectAll("path.lk").data(data, (d) => d.key);
    sel.exit().remove();
    const enter = sel.enter().append("path").attr("class", "lk");
    const all = enter.merge(sel)
      .classed("dep", (d) => !!d.dependency)
      .classed("hot", false).classed("cold", false)
      .attr("id", (d) => "lk-" + edgeKey(d.key))
      .attr("d", (d) => arc(d.a, d.b, d.dependency))
      .attr("stroke-width", (d) => Math.min(4.5, 0.7 + Math.log2(1 + (d.weight || 1)) * 0.9));

    // LINKS DRAW THEMSELVES: a line that appears all at once reads as decoration; a line that
    // draws from its source to its target reads as a route, which is what a relation is.
    if (dur(1)) {
      enter.each(function () {
        const len = this.getTotalLength ? this.getTotalLength() : 0;
        if (!len) return;
        d3.select(this).attr("stroke-dasharray", len).attr("stroke-dashoffset", len)
          .transition().duration(560).delay(90).ease(d3.easeCubicOut)
          .attr("stroke-dashoffset", 0)
          .on("end", function () { d3.select(this).attr("stroke-dasharray", null); });
      });
    }
    drawPackets(data);
    return all;
  }

  // Keys contain note ids, which can hold any character; an element id may not.
  const edgeKey = (k) => {
    let h = 2166136261;
    for (let i = 0; i < k.length; i++) { h ^= k.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(36);
  };

  // Light running along each dependency, from the note relied on to the note that relies on it:
  // the direction a planning change cascades. Declarative (SVG animateMotion), so it costs no
  // script per frame, and it is never drawn when motion is off.
  function drawPackets(data) {
    const g = state.world.select(".packets");
    g.selectAll("*").remove();
    if (!ambientOn()) return;
    const deps = data.filter((d) => d.dependency).slice(0, 28);
    deps.forEach((d, i) => {
      const len = Math.hypot(d.b.x - d.a.x, d.b.y - d.a.y);
      const secs = Math.max(1.8, Math.min(5.5, len / 60)) + (i % 4) * 0.25;
      const k = state.cam.k || 1;
      const c = g.append("circle").attr("class", "packet").attr("r", Math.max(0.6, 2.1 / k));
      const m = c.append("animateMotion").attr("dur", secs.toFixed(2) + "s")
        .attr("repeatCount", "indefinite").attr("begin", (-(i * 0.37) % secs).toFixed(2) + "s")
        .attr("keyPoints", "1;0").attr("keyTimes", "0;1").attr("calcMode", "linear");
      m.append("mpath").attr("href", "#lk-" + edgeKey(d.key));
    });
  }

  // A click leaves a ring that spreads from where it landed.
  function ripple(x, y, r) {
    if (!dur(1)) return;
    const k = state.cam.k || 1;
    state.world.select(".pulses").append("circle").attr("class", "ripple")
      .attr("cx", x).attr("cy", y).attr("r", r * 0.25).attr("stroke-width", 1.6 / k).style("opacity", 0.9)
      .transition().duration(760).ease(d3.easeCubicOut)
      .attr("r", r * 1.25).style("opacity", 0).remove();
  }

  function arc(a, b, straight) {
    if (straight) return `M${a.x},${a.y}L${b.x},${b.y}`;
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
    return `M${a.x},${a.y}A${d * 1.5},${d * 1.5} 0 0,1 ${b.x},${b.y}`;
  }

  /* ───────────────────────── navigation ───────────────────────── */

  const fillFor = (c) => ((c.children && c.children.length) ? GROUP_FILL : LEAF_FILL);

  function enter_(c) {
    state.stack = chainOf(c).map((x) => x.id);
    state.selected = null;
    writeHash();
    render();
    flyTo(worldOf(c), fillFor(c));
  }

  function up(c) {
    state.stack = chainOf(c).map((x) => x.id);
    state.selected = null;
    writeHash(); render(); flyTo(worldOf(c), fillFor(c));
  }

  function chainOf(c) {
    const out = []; let p = c;
    while (p) { out.unshift(p); p = p._parent; }
    return out;
  }

  function back() {
    if (state.selected) { select(null); return; }
    if (!state.stack.length) return;
    state.stack.pop();
    writeHash(); render();
    const host = state.stack.length ? cluster(state.stack[state.stack.length - 1]) : null;
    host ? flyTo(worldOf(host), fillFor(host)) : fitAll();
  }

  function goTo(stack, opts = {}) {
    state.stack = stack.filter((id) => cluster(id));
    render({ fast: !!opts.fast });
    if (!state.stack.length) fitAll(opts.animate === false ? 0 : 700);
    else {
      const c = cluster(state.stack[state.stack.length - 1]);
      flyTo(worldOf(c), fillFor(c), opts.animate === false ? 0 : 750);
    }
  }

  function renderBreadcrumb(view) {
    const crumbs = [{ id: null, label: state.arrangement === "area" ? "All areas" : "All months" }];
    state.stack.forEach((id) => {
      const c = cluster(id);
      if (c) crumbs.push({ id, label: c.label });
    });
    const el = $("#crumbs");
    el.innerHTML = crumbs.map((c, i) => {
      const last = i === crumbs.length - 1;
      return `<button class="crumb${last ? " here" : ""}" data-i="${i}"${
        last ? " aria-current=\"true\"" : ""}>${esc(c.label)}</button>`
        + (last ? "" : `<span class="crumb-sep" aria-hidden="true">›</span>`);
    }).join("");
    $$("#crumbs .crumb").forEach((b) => b.addEventListener("click", () => {
      goTo(state.stack.slice(0, +b.dataset.i));
      state.selected = null; writeHash();
    }));
    $("#back-btn").disabled = !state.stack.length && !state.selected;
  }

  function renderScope(view) {
    const el = $("#scope");
    if (!view.host) {
      const n = view.clusters.length;
      el.textContent = `${n} ${state.arrangement === "area" ? "areas" : "months"}, `
        + `${state.data.stats.notes} notes. Select one to open it.`;
      return;
    }
    const total = view.host.count;
    const shown = view.notes.length;
    el.textContent = view.host.children && view.host.children.length
      ? `${view.host.children.length} groups inside ${view.host.label}.`
      : shown < total
        ? `${shown} of ${total} notes shown, the most this stays legible at. Filter to see the rest.`
        : `${shown} note${shown === 1 ? "" : "s"} in ${view.host.label}.`;
  }

  /* ───────────────────────── the camera ───────────────────────── */

  // The extent of what this view actually draws. Framing the parent disc instead left a third
  // of the canvas empty, because a parent is packed with padding its children do not use.
  function contentBox(view) {
    const pts = [];
    for (const c of (view.clusters || [])) {
      if (c.dim) continue;
      pts.push([c.w.x - c.w.r, c.w.y - c.w.r], [c.w.x + c.w.r, c.w.y + c.w.r]);
    }
    for (const d of (view.notes || [])) {
      pts.push([d.x - d.r * 3, d.y - d.r * 3], [d.x + d.r * 3, d.y + d.r * 3]);
    }
    if (pts.length < 2) return null;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return { x0: Math.min(...xs), x1: Math.max(...xs),
             y0: Math.min(...ys), y1: Math.max(...ys) };
  }

  function flyToBox(b, ms) {
    const w = Math.max(1, b.x1 - b.x0), h = Math.max(1, b.y1 - b.y0);
    const k = Math.min(14, Math.max(0.04,
      Math.min((state.width - CHROME_ROOM) / w, (state.height - CHROME_ROOM) / h)));
    applyCam(d3.zoomIdentity.translate(state.width / 2, state.height / 2).scale(k)
      .translate(-(b.x0 + b.x1) / 2, -(b.y0 + b.y1) / 2), ms == null ? 500 : ms);
  }

  // cubic-bezier(x1,y1,x2,y2) sampled for d3's easing signature. Newton on x, then evaluate y.
  function bezier(t, x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    let u = t;
    for (let i = 0; i < 6; i++) {
      const x = ((ax * u + bx) * u + cx) * u - t;
      const dx = (3 * ax * u + 2 * bx) * u + cx;
      if (Math.abs(x) < 1e-5 || dx === 0) break;
      u -= x / dx;
    }
    return ((ay * u + by) * u + cy) * u;
  }

  function flyTo(w, fill = GROUP_FILL, ms) {
    const box = contentBox(state.view);
    if (box) { flyToBox(box, ms); return; }
    const k = frameScale(w, fill);
    const t = d3.zoomIdentity
      .translate(state.width / 2, state.height / 2).scale(k).translate(-w.x, -w.y);
    applyCam(t, ms == null ? 500 : ms);
  }

  function fitAll(ms = 700) {
    const cs = arrangement().clusters.map(worldOf);
    if (!cs.length) return;
    const minX = Math.min(...cs.map((c) => c.x - c.r)), maxX = Math.max(...cs.map((c) => c.x + c.r));
    const minY = Math.min(...cs.map((c) => c.y - c.r)), maxY = Math.max(...cs.map((c) => c.y + c.r));
    const k = Math.min(14, Math.max(0.04,
      Math.min((state.width - CHROME_ROOM) / (maxX - minX),
               (state.height - CHROME_ROOM) / (maxY - minY))));
    const t = d3.zoomIdentity.translate(state.width / 2, state.height / 2).scale(k)
      .translate(-(minX + maxX) / 2, -(minY + maxY) / 2);
    applyCam(t, ms);
  }

  function applyCam(t, ms) {
    const s = state.svg;
    if (!dur(1) || !ms) { s.call(state.zoom.transform, t); return; }
    // d3 interpolates zoom along the Van Wijk path, which is why this reads as flight rather
    // than a scale plus a slide.
    // A camera move must be able to change its mind mid-flight. d3's transition retargets from
    // the CURRENT transform when a new one is scheduled, which is why this reads as a course
    // correction rather than a restart. The curve is a long ease-out with no overshoot.
    s.transition().duration(ms)
      .ease((x) => bezier(x, 0.32, 0.72, 0, 1))
      .call(state.zoom.transform, t);
  }

  // Everything meant to be READ is sized in screen pixels, not world units: each chrome group
  // is scaled by 1/k and its offsets multiplied by k, so a name is the same size whether you are
  // looking at the whole map or at one note.
  function rescaleChrome() {
    const k = state.cam.k || 1;
    const inv = 1 / k;

    state.world.select(".clusters").selectAll("g.cl").each(function (d) {
      const g = this.querySelector(".chrome");
      if (!g) return;
      // Inline styles beat the stylesheet, so writing display here was un-hiding the names of
      // every dimmed group and stamping a ghost title across the middle of the map.
      if (d.dim || d.container) {
        g.style.display = "none";
        return;
      }
      g.style.display = "";
      const R = d.w.r * k;                       // the disc's radius in screen pixels
      g.setAttribute("transform", "scale(" + inv + ")");

      // Text lives INSIDE the disc. Placed above it, a name ran into neighbouring discs and
      // their level bars, and no amount of packing padding fixes that in general because a
      // label's width is a screen measurement and the packing happens in world units.
      const name = g.querySelector(".cl-name");
      if (name) {
        // Fit the name to the disc by shrinking it, and only give up when it would fall below
        // readable. Dropping a name the moment it is a few pixels too wide left groups labelled
        // with nothing but a number.
        const chars = Math.max(1, name.textContent.length);
        const room = R * 1.62;
        const size = Math.min(16, R * 0.28, room / (chars * 0.52));
        const fits = R > 22 && size >= 9;
        name.setAttribute("font-size", Math.max(9, size).toFixed(1));
        name.setAttribute("y", (-R * 0.26).toFixed(1));
        name.style.display = fits ? "" : "none";
        this.classList.toggle("unnamed", !fits);
      }
      const count = g.querySelector(".cl-count");
      if (count) {
        const size = Math.max(11, Math.min(26, R * 0.30));
        count.setAttribute("font-size", size.toFixed(1));
        count.setAttribute("y", (R * 0.22).toFixed(1));
        count.style.display = R < 15 ? "none" : "";
      }
      const mix = g.querySelector(".cl-mix");
      if (mix) {
        mix.setAttribute("transform", "translate(0,0)");
        mix.style.display = R < 30 ? "none" : "";
        // The mix rides the rim as an arc across the bottom of the disc. A floating bar inside
        // the disc looked like a stray mark; on the rim it reads as a gauge, which is what it is.
        const rr = R * 0.90;
        const A0 = 148, A1 = 32;                 // degrees, measured with y pointing down
        const total = d.c.count || 1;
        let a = A0;
        mix.querySelectorAll("path").forEach((el) => {
          const lvl = el.__data__ && el.__data__.l;
          const span = ((d.c.levels[lvl] || 0) / total) * (A0 - A1);
          const b = a - span;
          const rad = (deg) => (deg * Math.PI) / 180;
          const p0 = [rr * Math.cos(rad(a)), rr * Math.sin(rad(a))];
          const p1 = [rr * Math.cos(rad(b)), rr * Math.sin(rad(b))];
          el.setAttribute("d", "M" + p0[0].toFixed(2) + "," + p0[1].toFixed(2)
            + "A" + rr.toFixed(2) + "," + rr.toFixed(2) + " 0 0,0 "
            + p1[0].toFixed(2) + "," + p1[1].toFixed(2));
          a = b;
        });
      }
    });

    state.world.select(".notes").selectAll("g.nd").each(function (d) {
      const g = this.querySelector(".lbl");
      if (!g) return;
      g.setAttribute("transform", "scale(" + inv + ")");
      const t = g.querySelector(".nd-label");
      if (t) t.setAttribute("y", (d.r * k + 12).toFixed(1));

      // A mark's radius is a world measurement and should scale. The GAPS around it are read,
      // not measured, so they are screen-constant: left in world units the reticle drifted a
      // long way off its note as the camera came in.
      const flag = this.querySelector(".nd-flag");
      if (flag) flag.setAttribute("r", (d.r + 5 / k).toFixed(2));
      const breath = this.querySelector(".nd-breath");
      if (breath && !breath.dataset.beating) breath.setAttribute("r", (d.r + 4 / k).toFixed(2));
      const ret = this.querySelector(".reticle");
      if (ret) ret.setAttribute("d", reticlePath(d.r + 11 / k));
    });

    state.world.select(".notes").selectAll("g.guest").each(function () {
      const t = this.querySelector(".guest-label");
      const dot = this.querySelector(".guest-dot");
      if (!t || !dot) return;
      const r = (+dot.getAttribute("r") || 3) * k;
      t.setAttribute("transform", "scale(" + inv + ")");
      t.setAttribute("y", (r + 11).toFixed(1));
    });
  }

  function onCameraMoved() {
    // Semantic zoom: a label earns its place by having room. The ones that lost the placement
    // pass are not thrown away, they are waiting for you to come closer - which is the honest
    // behaviour, because the alternative is pretending the map holds fewer notes than it does.
    const k = state.cam.k;
    const base = +(state.world.attr("data-kbase") || 1);
    state.world.classed("tiny", k < 0.34);
    state.world.classed("close", k > base * 1.55);
    rescaleChrome();
    positionCard();
  }

  /* ───────────────────────── selection and the close-up ───────────────────────── */

  function select(id, fromHash) {
    if (!id) {
      state.selected = null;
      state.world.select(".notes").selectAll("g.nd").classed("sel", false).classed("faded", false)
        .classed("near", false);
      state.world.select(".links").selectAll("path.lk").classed("hot", false).classed("cold", false);
      state.world.selectAll(".guest").remove();
      $("#card").hidden = true;
      $("#detail").innerHTML = `<p class="panel-hint">Select a note on the map to read it.</p>`;
      if (!fromHash) writeHash();
      renderBreadcrumb(state.view || computeView());
      return;
    }
    const n = state.byId.get(id);
    if (!n) return;

    // If the note is not in the open constellation, travel to the one that holds it first.
    const home = homeOf(id);
    const chain = home ? chainOf(home).map((c) => c.id) : [];
    const sameScope = state.stack.join("|") === chain.join("|");
    state.selected = id;
    if (!sameScope) {
      state.stack = chain;
      render();
    }
    if (!fromHash) writeHash();

    const view = state.view = computeView();
    const d = view.notes.find((x) => x.n.id === id);
    renderDetail(n);
    showPanel("note");

    if (!d) {                       // filtered out of the current view
      $("#card").hidden = true;
      return;
    }

    // CLOSE-UP: fly to the note, dim its constellation, ring its neighbours around it.
    const nodes = state.world.select(".notes").selectAll("g.nd");
    const near = new Set([id]);
    [...n._out, ...n._in].forEach((l) => { near.add(l.source); near.add(l.target); });
    nodes.classed("sel", (x) => x.n.id === id)
      .classed("near", (x) => near.has(x.n.id) && x.n.id !== id)
      .classed("faded", (x) => !near.has(x.n.id));

    drawGuests(d, n);
    state.world.select(".links").selectAll("path.lk")
      .classed("hot", (e) => e.sid === id || e.tid === id)
      .classed("cold", (e) => e.sid !== id && e.tid !== id);
    if (dur(1)) {
      const g = state.world.select(".pulses");
      const k = state.cam.k || 1;
      g.append("circle").attr("class", "sel-ring")
        .attr("cx", d.x).attr("cy", d.y).attr("r", d.r)
        .transition().duration(620).ease(d3.easeCubicOut)
        .attr("r", d.r + 46 / k).style("opacity", 0).remove();
    }
    flyTo({ x: d.x, y: d.y, r: Math.max(d.r * 7.5, 34) }, 1.0, 500);
    setTimeout(() => { renderCard(n, d); }, dur(1) ? 420 : 0);
    renderBreadcrumb(view);
  }

  // Neighbours that live in other constellations are brought to the note as ghosts in a ring,
  // so a close-up answers "what does this touch" without making you leave to find out.
  function drawGuests(d, n) {
    const g = state.world.select(".notes");
    g.selectAll(".guest").remove();
    const here = new Set((state.view.notes || []).map((x) => x.n.id));
    // Dedupe by id. A pair of notes that reference each other BOTH ways produced two guest
    // markers for the same note, which is why the same name appeared twice on the plate.
    const seen = new Set();
    const outside = [...n._out.map((l) => ({ id: l.target, l, dir: "to" })),
                     ...n._in.map((l) => ({ id: l.source, l, dir: "from" }))]
      .filter((x) => {
        if (x.id === n.id || here.has(x.id) || seen.has(x.id)) return false;
        seen.add(x.id);
        return true;
      })
      .slice(0, 10);
    if (!outside.length) return;

    // Guests ring the whole region, not the selected cell, so their markers and labels can
    // never land on top of the cells actually drawn here.
    const box = contentBox(state.view);
    const reach = box
      ? Math.max(box.x1 - box.x0, box.y1 - box.y0) * 0.56
      : d.r * 5.2;
    const R = Math.max(d.r * 4, reach);
    const sel = g.selectAll("g.guest").data(outside, (x) => x.id);
    const enter = sel.enter().append("g").attr("class", "guest")
      .attr("transform", `translate(${d.x},${d.y}) scale(0.2)`).style("opacity", 0);
    enter.append("line").attr("class", "guest-line");
    enter.append("circle").attr("class", "guest-dot");
    enter.append("text").attr("class", "guest-label").attr("text-anchor", "middle");

    enter.each(function (x, i) {
      const a = (i / outside.length) * TAU - Math.PI / 2;
      const gx = d.x + Math.cos(a) * R, gy = d.y + Math.sin(a) * R;
      const el = d3.select(this);
      el.select(".guest-line")
        .attr("x1", (d.x - gx) * 0.86).attr("y1", (d.y - gy) * 0.86).attr("x2", 0).attr("y2", 0);
      el.select(".guest-dot").attr("r", Math.max(3, d.r * 0.62));
      el.select(".guest-label").attr("y", d.r * 0.62 + 11)
        .text(trim(state.byId.get(x.id)?.title || x.id, 22));
      el.attr("data-target", `${gx},${gy}`);
    });

    const all = enter.merge(sel);
    all.attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", (x) => `${state.byId.get(x.id)?.title || x.id}, ${x.l.type} ${x.dir}`)
      .classed("dep", (x) => !!x.l.dependency)
      .on("click", (ev, x) => { ev.stopPropagation(); select(x.id); })
      .on("keydown", (ev, x) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(x.id); }
      });

    const move = (s) => s.attr("transform", function () {
      const [gx, gy] = this.getAttribute("data-target").split(",").map(Number);
      return `translate(${gx},${gy}) scale(1)`;
    }).style("opacity", 1);

    dur(1) ? all.transition().duration(520).delay((x, i) => 120 + i * 26)
      .ease(d3.easeBackOut.overshoot(1.1)).call(move) : all.call(move);
    rescaleChrome();
  }

  function renderCard(n, d) {
    const card = $("#card");
    const dependents = n._in.filter((l) => l.dependency).length;
    const dependsOn = n._out.filter((l) => l.dependency).length;
    card.innerHTML = `
      <button class="card-x" aria-label="Close this note">×</button>
      <h3>${esc(n.title)}</h3>
      <p class="card-meta">${tick(n.level)} ${esc(n.level)}, ${esc(levelLabel(n.level))}
        <span class="dot">·</span> ${esc(ago(n.updated))}
        ${n.review_needed ? `<span class="warn">needs re-reading</span>` : ""}</p>
      ${n.brief ? `<p class="card-brief">${esc(n.brief)}</p>`
        : `<p class="card-brief muted">${briefWithheld(n)
            ? "The summary line is withheld for " + esc(n.level) + " notes on the published site."
            : "This note has no summary line."}</p>`}
      <p class="card-nums">
        <span><b data-count="${n.observations}">${n.observations}</b>facts</span>
        <span><b data-count="${dependents}">${dependents}</b>depend on it</span>
        <span><b data-count="${dependsOn}">${dependsOn}</b>it depends on</span></p>
      <p class="card-more"><button class="link-btn" id="card-detail">Read the full entry</button></p>`;
    card.hidden = false;
    card.dataset.x = d.x; card.dataset.y = d.y; card.dataset.r = d.r;
    positionCard();
    countUp(card);
    $(".card-x", card).addEventListener("click", () => select(null));
    $("#card-detail").addEventListener("click", () => { showPanel("note"); $("#panel-note").focus(); });
  }

  function positionCard() {
    const card = $("#card");
    if (card.hidden || !card.dataset.x) return;
    const p = state.cam.apply([+card.dataset.x, +card.dataset.y]);
    const r = (+card.dataset.r) * state.cam.k;
    const w = card.offsetWidth || 300, h = card.offsetHeight || 170;
    let left = p[0] + r + 22, top = p[1] - h / 2;
    if (left + w > state.width - 12) left = p[0] - r - 22 - w;
    card.classList.toggle("flip", left < p[0]);
    card.style.left = Math.max(12, Math.min(left, state.width - w - 12)) + "px";
    card.style.top = Math.max(12, Math.min(top, state.height - h - 12)) + "px";
  }

  function drawSelection() {
    if (!state.selected) return;
    const nodes = state.world.select(".notes").selectAll("g.nd");
    nodes.classed("sel", (x) => x.n.id === state.selected);
  }

  /* ───────────────────────── ambient life ───────────────────────── */

  // The map is never completely still, but nothing here invents information: drift is tiny and
  // uniform, and only notes that changed recently breathe. A screensaver would be a lie about
  // where the activity is.
  function startAmbient() {
    const step = () => {
      state.raf = requestAnimationFrame(step);
      if (!ambientOn()) return;
      const t = (performance.now() - state.t0) / 1000;
      const k = state.cam.k || 1;
      const amp = Math.min(2.4, 1.6 / k);

      state.world.select(".notes").selectAll("g.nd").each(function (d, i) {
        const dx = Math.sin(t * 0.36 + i * 1.7) * amp;
        const dy = Math.cos(t * 0.29 + i * 2.3) * amp;
        this.setAttribute("transform", `translate(${d.x + dx},${d.y + dy}) scale(1)`);
        if ((d.n.age_days ?? 999) <= 7) {
          const br = this.querySelector(".nd-breath");
          if (br) {
            br.dataset.beating = "1";
            const phase = 0.5 + 0.5 * Math.sin(t * 1.25 + i * 0.9);
            br.setAttribute("r", (d.r + (4 + phase * 3.4) / (state.cam.k || 1)).toFixed(2));
            br.style.opacity = (0.10 + phase * 0.30).toFixed(3);
          }
        }
      });

      state.world.select(".clusters").selectAll("g.cl").each(function (d, i) {
        const dx = Math.sin(t * 0.22 + i * 1.1) * amp * 0.8;
        const dy = Math.cos(t * 0.19 + i * 1.9) * amp * 0.8;
        this.setAttribute("transform", `translate(${d.w.x + dx},${d.w.y + dy})`);
      });
    };
    state.raf = requestAnimationFrame(step);
  }

  // A change that landed recently runs along the dependency edges it would travel down, which is
  // the same path the cascade takes. It is the one motion on the page that is an argument.
  function pulseRecent() {
    if (!dur(1) || !state.view) return;
    const view = state.view;
    const live = (view.edges || []).filter((e) => e.dependency
      && (e.a.n ? (e.a.n.age_days ?? 99) <= 10 : false));
    const pick = live.slice(0, 6);
    const g = state.world.select(".pulses");
    pick.forEach((e, i) => {
      const path = `M${e.a.x},${e.a.y}L${e.b.x},${e.b.y}`;
      const p = g.append("path").attr("d", path).attr("class", "pulse-path");
      const dot = g.append("circle").attr("class", "pulse-dot").attr("r", 2.6);
      const node = p.node();
      const len = node.getTotalLength ? node.getTotalLength() : 0;
      if (!len) { p.remove(); dot.remove(); return; }
      dot.transition().delay(i * 220).duration(1100).ease(d3.easeCubicOut)
        .attrTween("transform", () => (tt) => {
          const q = node.getPointAtLength(tt * len);
          return `translate(${q.x},${q.y})`;
        })
        .on("end", () => { dot.remove(); p.remove(); });
    });
  }

  /* ───────────────────────── hover ───────────────────────── */

  function showHover(ev, d) {
    if (state.selected === d.id) return;
    const hc = $("#hovercard");
    const dependents = d._in.filter((l) => l.dependency).length;
    const dependsOn = d._out.filter((l) => l.dependency).length;
    hc.innerHTML = `
      <h4>${esc(d.title)}</h4>
      <p style="margin:0;font-size:12px;color:var(--ink-3)">
        ${tick(d.level)} ${esc(d.level)}, ${esc(levelLabel(d.level))}${
          d.review_needed ? `<span style="color:var(--flag)">, needs re-reading</span>` : ""}
      </p>
      ${d.brief ? `<p>${esc(d.brief)}</p>` : `<p style="color:var(--ink-3)">${
        briefWithheld(d) ? "Summary withheld at this level." : "This note has no summary line."}</p>`}
      <div class="hc-foot">
        <span>${d.observations} facts</span>
        <span>${dependents} depend on it</span>
        <span>${dependsOn} it depends on</span>
        <span>changed ${esc(ago(d.updated))}</span>
      </div>`;
    hc.hidden = false;
    positionHover(ev);
  }

  function showClusterHover(ev, d) {
    const hc = $("#hovercard");
    const c = d.c;
    const mix = LEVELS.filter((l) => c.levels[l])
      .map((l) => `${tick(l)} ${c.levels[l]} ${esc(levelLabel(l))}`).join("<br>");
    hc.innerHTML = `
      <h4>${esc(c.label)}</h4>
      <p style="margin:0;font-size:12px;color:var(--ink-3)">${c.count} notes,
        ${c.observations} facts${c.children && c.children.length
          ? `, in ${c.children.length} groups` : ""}</p>
      <p style="font-size:12px;line-height:1.7;margin:8px 0 0">${mix}</p>
      <div class="hc-foot">
        ${c.newest_days == null ? "" : `<span>newest ${c.newest_days} days old</span>`}
        ${c.review_needed ? `<span style="color:var(--flag)">${c.review_needed} need re-reading</span>` : ""}
        ${c.todos ? `<span>${c.todos} placeholders</span>` : ""}
      </div>`;
    hc.hidden = false;
    positionHover(ev);
  }

  function positionHover(ev) {
    const hc = $("#hovercard");
    if (hc.hidden) return;
    const box = $("#atlas").getBoundingClientRect();
    const x = ev.clientX - box.left, y = ev.clientY - box.top;
    hc.style.left = Math.min(Math.max(10, x + 18), box.width - hc.offsetWidth - 10) + "px";
    hc.style.top = Math.min(Math.max(10, y + 14), box.height - hc.offsetHeight - 10) + "px";
  }

  const hideHover = () => { $("#hovercard").hidden = true; };

  /* ───────────────────────── rail ───────────────────────── */

  function showPanel(name) {
    $$(".rail-tabs button").forEach((b) =>
      b.setAttribute("aria-selected", String(b.dataset.panel === name)));
    moveThumb($(".rail-tabs"), '[aria-selected="true"]', "tab-thumb");
    $$(".panel").forEach((p) => {
      const on = p.id === "panel-" + name;
      p.classList.toggle("on", on);
      p.hidden = !on;
    });
  }

  function renderChanges() {
    const acts = state.data.activity;
    if (!acts.length) {
      $("#feed").innerHTML =
        `<p class="panel-hint">No commits yet. The first sync will fill this in.</p>`;
      return;
    }
    $("#feed").classList.add("stagger");
    $("#feed").innerHTML = acts.map((a, i) => `
      <li data-i="${i}" tabindex="0" aria-current="false" class="${isNew(a.at) ? "new" : ""}" style="--i:${Math.min(i, 14)}">
        <div class="f-top">
          ${tick(a.level)}
          <span class="f-who">${esc(a.author)}${a.actor === "agent"
            ? `<span class="f-agent">, using ${esc(a.agent || "an agent")}</span>` : ""}</span>
          <span class="f-when">${esc(ago(a.at))}</span>
        </div>
        <p class="f-msg${a.message ? "" : " withheld"}">${a.message
          ? esc(a.message)
          : `${a.files} file${a.files === 1 ? "" : "s"} changed. The message is not published.`}</p>
        <p class="f-paths">${esc(a.paths.slice(0, 3).join(", "))}${
          a.files > 3 ? `, and ${a.files - 3} more` : ""}</p>
      </li>`).join("");

    const pick = (li) => {
      $$("#feed li").forEach((x) => x.setAttribute("aria-current", "false"));
      li.setAttribute("aria-current", "true");
      const a = acts[+li.dataset.i];
      if (a.touched.length) select(a.touched[0]);
    };
    $$("#feed li").forEach((li) => {
      li.addEventListener("click", () => pick(li));
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(li); }
      });
    });
  }

  function renderNeeds() {
    const { proposals, review_needed } = state.data.queue;
    const open = proposals.filter((p) => (p.status || "open") === "open");
    const total = open.length + review_needed.length;
    const c = $("#needs-count");
    c.textContent = total;
    c.className = "count" + (total === 0 ? " zero" : "");

    const item = (o, why) => `
      <button class="item" data-id="${esc(o.id)}" type="button">
        <h4>${esc(o.title)}</h4>
        ${why ? `<p>${esc(why)}</p>` : ""}
        <span class="meta">${tick(o.level)} <span>${esc(o.level)}</span>
          ${o.author ? `<span>${esc(o.author)}</span>` : ""}
          ${o.age_days == null ? "" : `<span>${o.age_days} days old</span>`}</span>
      </button>`;

    $("#needs").innerHTML = `
      <h3 class="sec-head">Proposals</h3>
      <p class="panel-hint">An agent wrote these and cannot promote them. Someone with the right
        role decides.</p>
      ${open.length ? open.map((p) => item(p, p.brief)).join("")
        : `<p class="settled">Nothing waiting.</p>`}

      <h3 class="sec-head" style="margin-top:30px">Flagged by a change upstream</h3>
      <p class="panel-hint">A planning note these depend on has changed. Re-read each one, then
        update it or clear the flag.</p>
      ${review_needed.length ? review_needed.map((r) => item(r, r.why)).join("")
        : `<p class="settled">Nothing stale.</p>`}`;

    $$("#needs .item").forEach((el) =>
      el.addEventListener("click", () => select(el.dataset.id)));
  }

  function renderGaps() {
    const h = state.data.health;
    const repo = state.data.repo_url;
    const bad = h.counts.orphans + h.counts.placeholders + h.counts.review_needed;
    const c = $("#gaps-count");
    c.textContent = bad;
    c.className = "count" + (bad === 0 ? " zero" : "");

    const verdict = h.score >= 80
      ? "The memory is in good shape."
      : h.score >= 55
        ? "Usable, with parts going out of date."
        : "Much of this memory is still placeholder text, or cannot be reached from any other note.";

    const labels = {
      orphans: "notes nothing links to, so a search through the graph will never reach them",
      placeholders: "unfilled TODO markers, which agents read first and find empty",
      review_needed: "notes flagged by an upstream change and not yet re-read",
      stale: "notes untouched for 90 days or more",
      broken_links: "relations pointing at a note that does not exist",
    };

    const rows = Object.entries(h.counts).filter(([, v]) => v > 0)
      .map(([k, v]) => `<p class="gap-row"><b>${v}</b><span>${labels[k] || k}</span></p>`).join("");

    const worst = h.issues.filter((i) => i.severity === "major").slice(0, 10);

    $("#gaps").innerHTML = `
      <div class="score">
        <svg class="score-ring" viewBox="0 0 100 100" aria-hidden="true">
          <circle class="track" cx="50" cy="50" r="42"/>
          <circle class="fill" id="score-fill" cx="50" cy="50" r="42"
                  style="stroke-dasharray:${(2 * Math.PI * 42).toFixed(1)};stroke-dashoffset:${(2 * Math.PI * 42).toFixed(1)}"/>
        </svg>
        <p class="score-line"><b class="score-num" data-count="${h.score}">${h.score}</b><span class="score-of">out of 100</span></p>
      </div>
      <p class="score-verdict">${esc(verdict)} The score falls for unfilled placeholders,
        unreachable notes, notes going stale, and links that do not resolve.</p>
      ${rows || `<p class="settled">No gaps found.</p>`}
      ${worst.length ? `<h3 class="sec-head" style="margin-top:28px">Fix these first</h3>
        ${worst.map((i) => {
          const node = state.byId.get(i.id);
          const href = repo && node ? `${repo}/blob/main/${node.path}` : null;
          return `<button class="item" data-id="${esc(i.id)}" type="button">
            <h4>${esc(i.title)}</h4><p>${esc(i.detail)}</p>
            <span class="meta">${node ? tick(node.level) : ""}
              ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener"
                 onclick="event.stopPropagation()">Open the file</a>` : `<span>${esc(i.id)}</span>`}
            </span></button>`;
        }).join("")}` : ""}`;

    requestAnimationFrame(() => {
      const f = $("#score-fill");
      if (f) f.style.strokeDashoffset = ((2 * Math.PI * 42) * (1 - h.score / 100)).toFixed(1);
      countUp($("#gaps"));
    });

    $$("#gaps .item").forEach((el) => el.addEventListener("click", () => {
      if (state.byId.has(el.dataset.id)) select(el.dataset.id);
    }));
  }

  function renderDetail(d) {
    const repo = state.data.repo_url;
    const rel = [
      ...d._out.map((l) => ({ l, other: l.target, dir: "to" })),
      ...d._in.map((l) => ({ l, other: l.source, dir: "from" })),
    ];

    $("#detail").innerHTML = `
      <div class="d-head">
        <h2>${esc(d.title)}</h2>
        <p class="d-meta">${tick(d.level)} <span>${esc(d.level)}, ${esc(levelLabel(d.level))}</span>
          <span>${esc(d.type)}</span>
          ${d.status ? `<span>${esc(d.status)}</span>` : ""}
          ${d.confidentiality !== "internal" ? `<span>${esc(d.confidentiality)}</span>` : ""}</p>
      </div>

      ${d.review_needed ? `<p class="notice"><b>Needs re-reading.</b> A planning note this depends
        on changed: <code>${esc(d.review_needed)}</code>. Treat this note as possibly out of date
        and prefer the note it names.</p>` : ""}

      ${d.brief ? `<p class="d-brief">${esc(d.brief)}</p>`
        : briefWithheld(d) ? `<p class="d-brief" style="color:var(--ink-3)">The summary line is
            withheld for ${esc(d.level)} notes on the published site.</p>` : ""}

      <section class="d-sec">
        <h3>Who wrote it</h3>
        <dl class="kv">
          <dt>Created by</dt><dd>${esc(d.author || "not recorded")}</dd>
          <dt>Last edited</dt><dd>${esc(d.updated_by || "not recorded")}${
            d.agent ? `, using ${esc(d.agent)}` : ""}</dd>
          <dt>Created</dt><dd>${esc(d.created || "not recorded")}</dd>
          <dt>Changed</dt><dd>${esc(ago(d.updated))}</dd>
          <dt>File</dt><dd class="mono">${esc(d.path)}</dd>
        </dl>
      </section>

      ${Object.keys(d.categories || {}).length ? `<section class="d-sec">
        <h3>${d.observations} facts</h3>
        <p class="tallies">${Object.entries(d.categories).sort((a, b) => b[1] - a[1])
          .map(([c, n]) => `<span><b>${n}</b> ${esc(c)}</span>`).join("")}</p>
      </section>` : ""}

      ${d.observation_list ? `<section class="d-sec"><h3>What it says</h3>
        <ul class="obs-list">${d.observation_list.map((o) =>
          `<li><span class="oc">${esc(o.category)}</span><span>${esc(o.text)}</span></li>`).join("")}
        </ul></section>`
        : `<section class="d-sec"><p class="notice locked"><b>The text is not published.</b>
            This build shows the summary line above but not the note itself. Run
            <code>build_atlas.py --full</code> on your own machine to read it.</p></section>`}

      <section class="d-sec">
        <h3>${rel.length} relations</h3>
        ${rel.length ? `<ul class="rel-list">${rel.map(({ l, other, dir }) => {
          const o = typeof other === "object" ? other : state.byId.get(other);
          return `<li data-id="${esc(o.id)}" tabindex="0"><span class="rt">${esc(l.type)} ${dir}</span>
            <span>${esc(o.title)}</span></li>`;
        }).join("")}</ul>`
        : `<p class="panel-hint">None. Nothing links to this note, so a search through the graph
            will never reach it. Add a relation to connect it.</p>`}
      </section>

      ${d.tags.length ? `<section class="d-sec"><h3>Tags</h3>
        <p class="tags">${d.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</p>
      </section>` : ""}

      ${repo ? `<section class="d-sec">
        <a href="${esc(repo)}/blob/main/${esc(d.path)}" target="_blank" rel="noopener">
          Open this file on GitHub</a></section>` : ""}`;

    $$("#detail .rel-list li").forEach((li) => {
      const go = () => select(li.dataset.id);
      li.addEventListener("click", go);
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
      });
    });
  }

  /* ───────────────────────── search ───────────────────────── */

  function runSearch(q) {
    state.query = q;
    const box = $("#results");
    const term = q.trim().toLowerCase();
    if (!term) { box.hidden = true; box.innerHTML = ""; return; }
    const hits = state.nodes.filter((n) =>
      n.title.toLowerCase().includes(term) || n.path.toLowerCase().includes(term)
      || (n.tags || []).some((t) => t.toLowerCase().includes(term))
      || (n.brief || "").toLowerCase().includes(term)).slice(0, 12);
    box.hidden = false;
    const mark = (t) => {
      const i = t.toLowerCase().indexOf(term);
      return i < 0 ? esc(t) : esc(t.slice(0, i)) + "<mark>" + esc(t.slice(i, i + term.length)) + "</mark>"
        + esc(t.slice(i + term.length));
    };
    box.innerHTML = hits.length
      ? hits.map((n, i) => `<button class="res${i === 0 ? " hot" : ""}" data-id="${esc(n.id)}" style="--i:${i}">
          ${tick(n.level)}<span class="res-t">${mark(n.title)}</span>
          <span class="res-p">${esc(n.path)}</span></button>`).join("")
      : `<p class="res-none">Nothing matches "${esc(q)}".</p>`;
    $$("#results .res").forEach((b) => b.addEventListener("click", () => {
      $("#search").value = ""; box.hidden = true; select(b.dataset.id);
    }));
  }

  /* ───────────────────────── routing ───────────────────────── */

  function writeHash() {
    const parts = [state.arrangement, ...state.stack];
    const h = "#" + parts.map(encodeURIComponent).join("/")
      + (state.selected ? "~" + encodeURIComponent(state.selected) : "");
    if (location.hash !== h) history.replaceState(null, "", h);
  }

  function routeFromHash() {
    const raw = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (!raw) return false;
    const [pathPart, notePart] = raw.split("~");
    const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
    const kind = parts.shift();
    if (kind === "area" || kind === "time") state.arrangement = kind;
    syncArrangementButtons();
    goTo(parts, { animate: false });
    if (notePart) select(decodeURIComponent(notePart), true);
    return true;
  }

  /* ───────────────────────── arrangement morph ───────────────────────── */

  // Switching arrangement is the one moment the whole map rearranges. It is animated because the
  // point is that these are two views of the SAME corpus: watching Journal split into months is
  // the explanation, and a hard cut would throw it away.
  function setArrangement(kind) {
    if (kind === state.arrangement) return;
    state.arrangement = kind;
    state.stack = [];
    state.selected = null;
    $("#card").hidden = true;
    syncArrangementButtons();
    writeHash();
    render();
    fitAll(dur(820));
  }

  function syncArrangementButtons() {
    $$("#seg-arrange button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.arrange === state.arrangement)));
    moveThumb($("#seg-arrange"), '[aria-pressed="true"]', "seg-thumb");
  }

  /* ───────────────────────── wiring ───────────────────────── */

  function wireUI() {
    $$("#seg-arrange button").forEach((b) =>
      b.addEventListener("click", () => setArrangement(b.dataset.arrange)));

    // a soft light follows the pointer over the map
    const spot = $("#atlas .spot");
    if (spot) $("#atlas").addEventListener("pointermove", (ev) => {
      const r = $("#atlas").getBoundingClientRect();
      spot.style.setProperty("--mx", (ev.clientX - r.left) + "px");
      spot.style.setProperty("--my", (ev.clientY - r.top) + "px");
    });
    requestAnimationFrame(() => {
      moveThumb($("#seg-arrange"), '[aria-pressed="true"]', "seg-thumb");
      moveThumb($("#seg-colour"), '[aria-pressed="true"]', "seg-thumb");
      moveThumb($(".rail-tabs"), '[aria-selected="true"]', "tab-thumb");
    });

    $$("#seg-colour button").forEach((b) => b.addEventListener("click", () => {
      $$("#seg-colour button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      moveThumb($("#seg-colour"), '[aria-pressed="true"]', "seg-thumb");
      state.colourMode = b.dataset.mode;
      paint();
    }));

    $("#labels-toggle").addEventListener("change", (e) => {
      state.labels = e.target.checked;
      state.world.select(".notes").selectAll(".nd-label")
        .style("display", state.labels ? null : "none");
    });

    $("#motion-toggle").addEventListener("change", (e) => {
      state.ambient = e.target.checked;
      document.documentElement.classList.toggle("still", !state.ambient);
      if (state.view) drawEdges(state.view, (x) => x);   // packets come and go with motion
      if (!state.ambient) {   // put everything back exactly on its mark
        state.world.select(".notes").selectAll("g.nd")
          .attr("transform", (d) => `translate(${d.x},${d.y}) scale(1)`);
        state.world.select(".clusters").selectAll("g.cl")
          .attr("transform", (d) => `translate(${d.w.x},${d.w.y})`);
      }
    });

    $("#back-btn").addEventListener("click", back);
    $("#fit-btn").addEventListener("click", () => {
      if (state.stack.length) {
        const c = cluster(state.stack[state.stack.length - 1]);
        flyTo(worldOf(c), fillFor(c));
      } else fitAll();
    });

    let t;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(t);
      const v = e.target.value;
      t = setTimeout(() => runSearch(v), 110);
    });
    $("#search").addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.target.value = ""; runSearch(""); e.target.blur(); }
      if (e.key === "Enter") { const f = $("#results .res.hot") || $("#results .res"); if (f) f.click(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const items = $$("#results .res");
        if (!items.length) return;
        e.preventDefault();
        let i = items.findIndex((x) => x.classList.contains("hot"));
        i = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((x, j) => x.classList.toggle("hot", j === i));
        items[i].scrollIntoView && items[i].scrollIntoView({ block: "nearest" });
      }
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".search-wrap")) $("#results").hidden = true;
    });

    const tabs = $$(".rail-tabs button");
    tabs.forEach((b, i) => {
      b.addEventListener("click", () => showPanel(b.dataset.panel));
      b.addEventListener("keydown", (e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        e.preventDefault();
        const next = tabs[(i + step + tabs.length) % tabs.length];
        next.focus(); showPanel(next.dataset.panel);
      });
    });

    $("#help-btn").addEventListener("click", () => $("#help").showModal());
    $("#theme-btn").addEventListener("click", (ev) => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      if (!document.startViewTransition || !dur(1)) { setTheme(next); return; }
      const r = ev.currentTarget.getBoundingClientRect();
      document.documentElement.style.setProperty("--vx", (r.left + r.width / 2) + "px");
      document.documentElement.style.setProperty("--vy", (r.top + r.height / 2) + "px");
      document.startViewTransition(() => setTheme(next));
    });

    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
        if (!document.documentElement.getAttribute("data-theme")) paint();
      });
      window.matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", (e) => {
        state.motion = e.matches ? "reduced" : "full";
        $("#motion-row").hidden = e.matches;
      });
    }
    $("#motion-row").hidden = state.motion === "reduced";

    document.addEventListener("keydown", (e) => {
      // e.target is whatever has focus, which is not always an Element: a keydown dispatched at
      // the document itself has no `matches`, and calling it there threw and killed every
      // keyboard shortcut on the page.
      const t = e.target;
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault(); $("#search").focus(); $("#search").select(); return;
      }
      if (t && typeof t.matches === "function" && t.matches("input, textarea, select")) return;
      if (e.key === "Escape") back();
      if (e.key === "/") { e.preventDefault(); $("#search").focus(); }
      if (e.key === "Backspace") { e.preventDefault(); back(); }
    });

    let rt;
    window.addEventListener("resize", () => {
      clearTimeout(rt);
      rt = setTimeout(() => {
        measure();
        if (state.stack.length) {
          const c = cluster(state.stack[state.stack.length - 1]);
          flyTo(worldOf(c), fillFor(c), 0);
        } else fitAll(0);
        positionCard();
      }, 160);
    });

    setInterval(pulseRecent, 9000);
  }

  // Colours come from CSS custom properties, so a theme change has to re-read them.
  function paint() {
    if (!state.world) return;
    state.world.select(".notes").selectAll(".nd-core").attr("fill", (d) => nodeColour(d.n));
    state.world.select(".notes").selectAll(".nd-bloom").attr("fill", (d) => nodeColour(d.n));
    state.world.select(".notes").selectAll(".nd-breath").attr("stroke", (d) => nodeColour(d.n));
    state.world.select(".clusters").selectAll(".cl-disc").attr("stroke", (d) => dominant(d.c));
    state.world.select(".clusters").selectAll(".cl-halo").attr("fill", (d) => dominant(d.c));
    state.world.select(".clusters").selectAll(".cl-mix path")
      .attr("stroke", function () { return levelColour(this.__data__.l); });
    $$(".tick").forEach((el) => {
      const lvl = el.dataset.level;
      if (lvl) el.style.background = levelColour(lvl);
    });
    $$(".lg i").forEach((el) => {
      const lvl = el.parentElement.dataset.level;
      if (lvl) el.style.background = levelColour(lvl);
    });
  }

  boot();
})();
