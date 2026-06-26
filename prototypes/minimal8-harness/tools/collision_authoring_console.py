#!/usr/bin/env python3
"""Local operator console for resolving minimal8 residual clean-field collisions.

Part of the Ingestion–Runtime Separation slice-6 cutover. The legacy bootstrap
(`scripts/legacy_semantic_bootstrap.py`) fails loud on identical-pixel tiles that
carry conflicting *clean* visual values — the placement-contaminated residue of
the hand-curated `tiles.json`. This console renders each colliding content-hash
group, surfaces the contaminated legacy values as *reference only*, and lets the
operator author the one true clean value per conflicting field. Decisions persist
to a durable, committable resolutions file the cutover then merges into the
authored semantic catalogue.

This tool is local and disposable (CLAUDE.md): it reads ingest data and writes a
small JSON decision artefact. It does NOT run the cutover, generate runtime
assets, or mutate any pipeline state.

Status / precedent: built once to resolve the minimal8 slice-6 residual
collisions. It may never run again — its durable output (the committed
``collision-resolutions.json``) is what the pipeline consumes, not this script.
It is kept in-tree as a worked precedent for operator authoring consoles: a
zero-dependency stdlib pattern (load ingest data -> render tiles -> surface
contaminated values as reference -> capture operator decisions to a durable,
committable artefact) worth building from if a richer semantic-authoring or
detector-review UI is needed later. Treat as a reference, not a maintained
surface.

Run:
    python3 prototypes/minimal8-harness/tools/collision_authoring_console.py
then open http://127.0.0.1:8765/ .
"""

from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PIL import Image  # noqa: E402

from semantic_catalogue_ingest import (  # noqa: E402
    INGEST_SEMANTIC_FIELDS,
    SEMANTIC_CATALOGUE_SCHEMA_VERSION,
    _SEQUENCE_FACT_FIELDS,
)
from tile_family_ingest import load_source_tile_family  # noqa: E402
from tile_family_runtime import resolve_canonical_tile_image  # noqa: E402

FAMILY_DIR = REPO_ROOT / "prototypes/minimal8-harness/tile-families/minimal8"
COLLISIONS_PATH = (
    REPO_ROOT
    / "prototypes/minimal8-harness/scratch.local/semantic-bootstrap/minimal8-clean-fields"
    / "bootstrap-collisions.json"
)
# Durable, committable operator-decision artefact — NOT scratch.local. The
# slice-6 cutover merges these resolutions into the authored semantic catalogue.
RESOLUTIONS_PATH = (
    REPO_ROOT
    / "prototypes/minimal8-harness/semantic-catalogue/minimal8-clean-fields"
    / "collision-resolutions.json"
)

CLEAN_FIELDS = tuple(sorted(INGEST_SEMANTIC_FIELDS))
MULTI_FIELDS = frozenset(_SEQUENCE_FACT_FIELDS)

# Pixel-grounded proposals authored by reading the rendered tiles. These are
# *prefills for operator sign-off*, not auto-derived truth — the collisions
# exist because the legacy values are placement-contaminated, so the dominant
# legacy value is not trustworthy. Only conflicting fields need a proposal;
# agreed fields prefill from the (consistent) legacy value.
PROPOSALS: dict[str, dict[str, object]] = {
    # Group 0 — fully transparent blank tile (alpha bbox empty). No visual facts.
    "content-sha256:17d1cd8514f7a1850b500edd072b5160d5f6dfe5d34449f0dec80d105d0beea6": {
        "contrast": None,
        "facing": None,
        "noise": None,
        "pose": None,
        "semantics": [],
        "style": None,
        "temperature": None,
    },
    # Group 1 — broken/dashed horizontal mark, bright on empty.
    "content-sha256:5abac92647a33057620dd781afe8238fc63481651557383c522175a19b76a635": {
        "contrast": "high",
        "facing": None,
        "pose": None,
    },
    # Group 2 — solid full-width horizontal rule, bright on empty.
    "content-sha256:8f7ea9c0aa482a6d31e36bf868ddf9a010a484b27e1e8fc8c88c5a5077586961": {
        "contrast": "high",
        "facing": None,
        "pose": None,
    },
    # Group 3 — scattered speckle/noise terrain texture.
    "content-sha256:ddaade7967086f46d37c858926d783e5ee16b04bed511faa3b343d9d15b79515": {
        "contrast": "high",
        "noise": "dense",
        "semantics": [],
        "temperature": "neutral",
    },
}


def _canonical(value: object) -> object:
    """JSON-friendly canonical form: tuple/list -> list, leave scalars/None."""
    if isinstance(value, (tuple, list)):
        return list(value)
    return value


@dataclass(frozen=True)
class GroupField:
    field: str
    kind: str  # "single" | "multi"
    conflict: bool
    agreed_value: object  # used when not conflict
    options: list[dict]  # [{value, count}] when conflict
    proposed: object  # prefill for the editor


class ConsoleState:
    def __init__(self) -> None:
        self.family = load_source_tile_family(FAMILY_DIR)
        self.default_variant_id = self.family.runtime_unit.default_variant_id
        self.variant_ids = sorted(self.family.variants)
        self._image_cache: dict[Path, Image.Image] = {}
        raw = json.loads(COLLISIONS_PATH.read_text(encoding="utf-8"))
        self.collisions = raw["collisions"] if isinstance(raw, dict) else raw
        self.groups = [self._analyse_group(i, g) for i, g in enumerate(self.collisions)]
        self._by_hash = {g["content_hash"]: g for g in self.groups}

    def _analyse_group(self, index: int, collision: Mapping) -> dict:
        content_hash = collision["content_hash"]
        tile_ids = list(collision["tile_ids"])
        differing = collision.get("differing_fields", {})
        proposal = PROPOSALS.get(content_hash, {})
        fields: list[dict] = []
        for field in CLEAN_FIELDS:
            kind = "multi" if field in MULTI_FIELDS else "single"
            if field in differing:
                options = [
                    {"value": _render_value_key(vk), "count": len(ids)}
                    for vk, ids in differing[field].items()
                ]
                options.sort(key=lambda o: o["count"], reverse=True)
                fields.append(
                    {
                        "field": field,
                        "kind": kind,
                        "conflict": True,
                        "agreed_value": None,
                        "options": options,
                        "proposed": _canonical(proposal.get(field, [] if kind == "multi" else None)),
                    }
                )
            else:
                # Non-conflicting: every tile in the group agrees. Read one.
                agreed = _canonical(getattr(self.family.tiles[tile_ids[0]], field))
                fields.append(
                    {
                        "field": field,
                        "kind": kind,
                        "conflict": False,
                        "agreed_value": agreed,
                        "options": [],
                        "proposed": agreed,
                    }
                )
        blank = self._is_blank(tile_ids[0])
        conflict_count = sum(1 for f in fields if f["conflict"])
        if blank:
            description = (
                "This tile is fully transparent — a blank cell. It has no visual content, "
                "so every clean field should be empty/null."
            )
        else:
            description = (
                f"{len(tile_ids)} tiles across the sheet share these exact pixels. "
                f"{conflict_count} field(s) disagreed in the old hand-entered data and need your decision."
            )
        return {
            "index": index,
            "content_hash": content_hash,
            "tile_count": len(tile_ids),
            "representative_tile_id": tile_ids[0],
            "blank": blank,
            "description": description,
            "fields": fields,
        }

    def _is_blank(self, tile_id: str) -> bool:
        tile = self.family.tiles[tile_id]
        image = resolve_canonical_tile_image(
            tile,
            variant=self.family.variants[self.default_variant_id],
            root=self.family.root,
            tile_width=self.family.tile_width,
            tile_height=self.family.tile_height,
            image_cache=self._image_cache,
        )
        return image.getchannel("A").getbbox() is None

    def render_tile_png(self, content_hash: str, variant_id: str) -> bytes:
        group = self._by_hash[content_hash]
        tile = self.family.tiles[group["representative_tile_id"]]
        variant = self.family.variants.get(variant_id) or self.family.variants[self.default_variant_id]
        image = resolve_canonical_tile_image(
            tile,
            variant=variant,
            root=self.family.root,
            tile_width=self.family.tile_width,
            tile_height=self.family.tile_height,
            image_cache=self._image_cache,
        )
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def load_resolutions(self) -> dict[str, dict]:
        if not RESOLUTIONS_PATH.exists():
            return {}
        raw = json.loads(RESOLUTIONS_PATH.read_text(encoding="utf-8"))
        return {p["content_hash"]: p["facts"] for p in raw.get("patches", [])}

    def save_resolution(self, content_hash: str, facts: dict) -> int:
        if content_hash not in self._by_hash:
            raise KeyError(content_hash)
        resolutions = self.load_resolutions()
        resolutions[content_hash] = facts
        # Preserve group order for a stable, reviewable diff.
        patches = [
            {"content_hash": g["content_hash"], "facts": resolutions[g["content_hash"]]}
            for g in self.groups
            if g["content_hash"] in resolutions
        ]
        RESOLUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": SEMANTIC_CATALOGUE_SCHEMA_VERSION, "patches": patches}
        RESOLUTIONS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return len(patches)


def _render_value_key(value_key: str) -> object:
    """Decode a bootstrap fact_value_key ('null' | 'string:x' | 'tuple:[json]')."""
    if value_key == "null":
        return None
    if value_key.startswith("string:"):
        return value_key[len("string:") :]
    if value_key.startswith("tuple:"):
        return json.loads(value_key[len("tuple:") :])
    return value_key


STATE: ConsoleState | None = None


def state() -> ConsoleState:
    assert STATE is not None
    return STATE


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>minimal8 — residual collision authoring</title>
<style>
  :root { --bg:#14161a; --card:#1e2229; --line:#2c313b; --ink:#e7ebf0; --muted:#98a2b3;
          --conflict:#3a1f24; --conflict-line:#7a2f3a; --ok:#1f3a26; --ok-line:#2f7a44; --accent:#5b8def; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
           padding:16px 24px; display:flex; align-items:center; gap:16px; z-index:10; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .progress { color:var(--muted); font-size:13px; }
  .progress b { color:var(--ink); }
  main { max-width:980px; margin:0 auto; padding:24px; display:grid; gap:24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  .card.resolved { border-color:var(--ok-line); }
  .card-head { display:flex; gap:20px; padding:18px 20px; border-bottom:1px solid var(--line); align-items:flex-start; }
  .tile-wrap { flex:0 0 auto; }
  .tile { width:128px; height:128px; image-rendering:pixelated; border-radius:6px;
          background-image:
            linear-gradient(45deg,#33384200 25%,transparent 0,transparent 75%,#33384200 0),
            linear-gradient(45deg,#33384200 25%,transparent 0,transparent 75%,#33384200 0);
          background-color:#262b33;
          background-size:16px 16px; background-position:0 0,8px 8px;
          border:1px solid var(--line); display:block; }
  .checker { background-color:#2a2f38;
             background-image:
               linear-gradient(45deg,#363c46 25%,transparent 25%,transparent 75%,#363c46 75%),
               linear-gradient(45deg,#363c46 25%,transparent 25%,transparent 75%,#363c46 75%);
             background-size:16px 16px; background-position:0 0,8px 8px; }
  .meta { flex:1 1 auto; min-width:0; }
  .meta h2 { margin:0 0 4px; font-size:15px; }
  .meta .hash { color:var(--muted); font-size:11px; font-family:ui-monospace,Menlo,monospace; word-break:break-all; }
  .meta .count { margin-top:6px; color:var(--muted); }
  .variant-row { margin-top:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  select, input[type=text] { background:#12151a; color:var(--ink); border:1px solid var(--line);
           border-radius:6px; padding:5px 8px; font:inherit; }
  .badge { font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }
  .badge.ok { background:var(--ok); border-color:var(--ok-line); color:#bff0cf; }
  .fields { padding:8px 20px 4px; }
  .field { display:grid; grid-template-columns:130px 1fr; gap:12px; align-items:start;
           padding:10px 0; border-bottom:1px solid var(--line); }
  .field:last-child { border-bottom:none; }
  .field .label { color:var(--muted); padding-top:6px; }
  .field.conflict .label { color:#f3b6c0; }
  .field.conflict { background:var(--conflict); margin:0 -20px; padding:10px 20px; border-bottom:1px solid var(--conflict-line); }
  .contaminated { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
  .chip { font-size:11px; padding:2px 8px; border-radius:6px; background:#2a1115; border:1px solid var(--conflict-line);
          color:#f0c2c9; font-family:ui-monospace,Menlo,monospace; }
  .chip .n { color:#b97; margin-left:4px; }
  .hint { color:var(--muted); font-size:12px; margin:2px 0 8px; }
  .card-foot { padding:14px 20px; display:flex; gap:12px; align-items:center; justify-content:flex-end;
               border-top:1px solid var(--line); }
  button { background:var(--accent); color:#fff; border:none; border-radius:7px; padding:8px 16px;
           font:inherit; font-weight:600; cursor:pointer; }
  button.secondary { background:transparent; border:1px solid var(--line); color:var(--ink); font-weight:500; }
  button:disabled { opacity:.5; cursor:default; }
  .saved-note { color:#8fd0a3; font-size:12px; }
  .clean-val { font-family:ui-monospace,Menlo,monospace; color:#cdd5df; }
  .intro { max-width:980px; margin:24px auto -4px; padding:18px 22px; background:var(--card);
           border:1px solid var(--line); border-radius:10px; }
  .intro h2 { margin:0 0 8px; font-size:15px; }
  .intro p { margin:6px 0; color:#c4ccd6; }
  .intro ol { margin:8px 0 4px; padding-left:20px; color:#c4ccd6; }
  .intro li { margin:4px 0; }
  .legend { display:flex; gap:18px; flex-wrap:wrap; margin-top:12px; padding-top:12px; border-top:1px solid var(--line); }
  .legend .item { display:flex; align-items:center; gap:7px; font-size:12px; color:var(--muted); }
  .legend .sw { width:14px; height:14px; border-radius:4px; border:1px solid var(--line); }
  .legend .sw.conflict { background:var(--conflict); border-color:var(--conflict-line); }
  .legend .sw.agreed { background:var(--card); }
  .desc { margin:8px 0 0; color:#c4ccd6; font-size:13px; }
  .fieldhelp { color:var(--muted); font-size:11px; margin-top:2px; }
  .tile { width:160px; height:160px; }
  .blank-note { margin-top:6px; font-size:12px; color:#8fb4f0; }
</style>
</head>
<body>
<header>
  <h1>minimal8 · residual clean-field collisions</h1>
  <div class="progress">Resolved <b id="resolved">0</b> / <span id="total">0</span></div>
</header>
<section class="intro">
  <h2>What this is</h2>
  <p>Minimal8 has thousands of tiles. Some have <b>pixel-for-pixel identical artwork</b> but were given
  <b>different descriptive metadata</b> by hand over time. Each card below is one such group of identical tiles.
  The old metadata disagreed with itself, so we can't auto-pick a value — you decide the one correct
  visual description, once, for the whole group.</p>
  <p>You're describing <b>what the little tile picture looks like</b> — nothing about where it's used.
  There are only <b id="total2">4</b> groups, and most are trivial (a blank tile, a plain line).</p>
  <ol>
    <li>Look at the rendered tile on the left of each card (switch preview colour if it helps).</li>
    <li>For each <span style="color:#f3b6c0">⚠ highlighted field</span>, the red chips show the old conflicting values (reference only — don't trust them). I've pre-filled a proposed clean value.</li>
    <li>Adjust if you disagree, then <b>Save resolution</b>. Leave a field blank to mean "none / null".</li>
  </ol>
  <div class="legend">
    <div class="item"><span class="sw conflict"></span> conflicting field — needs your decision</div>
    <div class="item"><span class="sw agreed"></span> agreed field — already consistent, pre-filled</div>
    <div class="item"><span class="chip" style="margin:0">old value<span class="n">×N</span></span> contaminated legacy value (reference only)</div>
  </div>
</section>
<main id="main"></main>
<script>
const MULTI = new Set(__MULTI_FIELDS__);
const FIELD_HELP = {
  contrast: "How much light/dark contrast the artwork shows: high, medium, low.",
  facing: "Direction the artwork points, if any: left or right (blank if it doesn't face a way).",
  motifs: "Recurring decorative motifs present (comma-separated; usually blank).",
  noise: "Amount of textural speckle/noise: none, medium, dense.",
  orientation: "Overall orientation of the shape, if meaningful (e.g. horizontal/vertical).",
  pose: "Posture for figure-like tiles: tall or short (blank if not a figure).",
  semantics: "What the tile depicts / is — its kinds and uses (comma-separated, e.g. door, arch).",
  style: "Stylistic descriptor, if any (e.g. quiet). Usually blank.",
  temperature: "Colour temperature of the artwork: warm, cool, or neutral.",
};
let STATE = null;

function valToInput(v){ if (v === null || v === undefined) return ""; if (Array.isArray(v)) return v.join(", "); return String(v); }
function inputToVal(field, raw){
  raw = raw.trim();
  if (MULTI.has(field)) return raw === "" ? [] : raw.split(",").map(s=>s.trim()).filter(Boolean);
  return raw === "" ? null : raw;
}
function fmtClean(v){ if (v===null||v===undefined) return "∅ (null)"; if (Array.isArray(v)) return v.length? "["+v.join(", ")+"]" : "[] (empty)"; return String(v); }

async function load(){
  STATE = await (await fetch("/api/state")).json();
  document.getElementById("total").textContent = STATE.groups.length;
  render();
}
function render(){
  document.getElementById("resolved").textContent = STATE.groups.filter(g=>g.resolved).length;
  const main = document.getElementById("main");
  main.innerHTML = "";
  for (const g of STATE.groups) main.appendChild(card(g));
}
function card(g){
  const el = document.createElement("section");
  el.className = "card" + (g.resolved ? " resolved" : "");
  const variants = STATE.variant_ids;
  el.innerHTML = `
   <div class="card-head">
     <div class="tile-wrap">
       <img class="tile checker" id="img-${g.index}" alt="tile" />
     </div>
     <div class="meta">
       <h2>Group ${g.index} ${g.resolved ? '<span class="badge ok">resolved</span>' : '<span class="badge">needs decision</span>'}</h2>
       <div class="count">${g.tile_count} identical-pixel tiles</div>
       <div class="desc">${g.description}</div>
       <div class="hash" title="${g.representative_tile_id}">${g.content_hash}</div>
       <div class="variant-row">
         <span class="hint">preview variant:</span>
         <select id="var-${g.index}">${variants.map(v=>`<option ${v===STATE.default_variant_id?'selected':''}>${v}</option>`).join("")}</select>
       </div>
     </div>
   </div>
   <div class="fields" id="fields-${g.index}"></div>
   <div class="card-foot">
     <span class="saved-note" id="note-${g.index}"></span>
     <button class="secondary" id="reset-${g.index}">Reset to proposed</button>
     <button id="save-${g.index}">Save resolution</button>
   </div>`;
  const fieldsEl = el.querySelector(`#fields-${g.index}`);
  for (const f of g.fields) fieldsEl.appendChild(fieldRow(g, f));
  const img = el.querySelector(`#img-${g.index}`);
  const setImg = ()=>{ img.src = `/api/tile?hash=${encodeURIComponent(g.content_hash)}&variant=${encodeURIComponent(el.querySelector(`#var-${g.index}`).value)}&t=${Date.now()}`; };
  setImg();
  el.querySelector(`#var-${g.index}`).addEventListener("change", setImg);
  el.querySelector(`#save-${g.index}`).addEventListener("click", ()=>save(g, el));
  el.querySelector(`#reset-${g.index}`).addEventListener("click", ()=>{ fillInputs(g, el, true); });
  return el;
}
function fieldRow(g, f){
  const row = document.createElement("div");
  row.className = "field" + (f.conflict ? " conflict" : "");
  const initial = g.resolved && g.resolution ? g.resolution[f.field] : f.proposed;
  let inner = `<div class="label">${f.field}${f.conflict?' ⚠':''}<div class="fieldhelp">${FIELD_HELP[f.field]||''}</div></div><div>`;
  if (f.conflict){
    inner += `<div class="contaminated">` +
      f.options.map(o=>`<span class="chip">${fmtClean(o.value)}<span class="n">×${o.count}</span></span>`).join("") +
      `</div><div class="hint">contaminated legacy values above (reference only) · proposed: <span class="clean-val">${fmtClean(f.proposed)}</span></div>`;
  } else {
    inner += `<div class="hint">agreed across group: <span class="clean-val">${fmtClean(f.agreed_value)}</span></div>`;
  }
  inner += `<input type="text" id="in-${g.index}-${f.field}" value="${valToInput(initial).replace(/"/g,'&quot;')}" placeholder="${MULTI.has(f.field)?'comma,separated or empty':'value or empty for null'}"></div>`;
  row.innerHTML = inner;
  return row;
}
function fillInputs(g, el, proposed){
  for (const f of g.fields){
    const v = proposed ? f.proposed : (g.resolution ? g.resolution[f.field] : f.proposed);
    el.querySelector(`#in-${g.index}-${f.field}`).value = valToInput(v);
  }
}
async function save(g, el){
  const facts = {};
  for (const f of g.fields) facts[f.field] = inputToVal(f.field, el.querySelector(`#in-${g.index}-${f.field}`).value);
  const note = el.querySelector(`#note-${g.index}`);
  note.textContent = "saving…";
  const res = await fetch("/api/resolve", {method:"POST", headers:{"content-type":"application/json"},
    body: JSON.stringify({content_hash: g.content_hash, facts})});
  if (!res.ok){ note.textContent = "error: " + (await res.text()); return; }
  const data = await res.json();
  g.resolved = true; g.resolution = facts;
  note.textContent = "saved ✓";
  document.getElementById("resolved").textContent = data.resolved_count;
  el.classList.add("resolved");
  el.querySelector(".meta h2").innerHTML = `Group ${g.index} <span class="badge ok">resolved</span>`;
}
load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = INDEX_HTML.replace("__MULTI_FIELDS__", json.dumps(sorted(MULTI_FIELDS)))
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            resolutions = state().load_resolutions()
            groups = []
            for g in state().groups:
                resolved = g["content_hash"] in resolutions
                groups.append({**g, "resolved": resolved, "resolution": resolutions.get(g["content_hash"])})
            payload = {
                "default_variant_id": state().default_variant_id,
                "variant_ids": state().variant_ids,
                "groups": groups,
            }
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        if parsed.path == "/api/tile":
            q = parse_qs(parsed.query)
            content_hash = q.get("hash", [""])[0]
            variant_id = q.get("variant", [state().default_variant_id])[0]
            try:
                png = state().render_tile_png(content_hash, variant_id)
            except KeyError:
                self._send(404, b"unknown content hash", "text/plain")
                return
            self._send(200, png, "image/png")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/resolve":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            content_hash = body["content_hash"]
            facts = body["facts"]
            count = state().save_resolution(content_hash, facts)
        except KeyError as exc:
            self._send(400, f"bad request: {exc}".encode(), "text/plain")
            return
        except Exception as exc:  # surface authoring errors to the operator
            self._send(500, f"{type(exc).__name__}: {exc}".encode(), "text/plain")
            return
        self._send(200, json.dumps({"resolved_count": count}).encode(), "application/json")


def main() -> None:
    global STATE
    STATE = ConsoleState()
    host = "127.0.0.1"
    port = int(os.environ.get("COLLISION_CONSOLE_PORT", "8765"))
    print(f"minimal8 collision authoring console — {len(STATE.groups)} groups")
    print(f"  collisions: {COLLISIONS_PATH.relative_to(REPO_ROOT)}")
    print(f"  writing:    {RESOLUTIONS_PATH.relative_to(REPO_ROOT)}")
    print(f"  open:       http://{host}:{port}/")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
