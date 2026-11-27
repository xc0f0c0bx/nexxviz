"""Visualizer selector for the HiFiBerryOS web UI.

Serves a small page and JSON API on 127.0.0.1:8099. nginx proxies
``/visualizer/`` here. Choosing a shader writes the persistent selection
(``/var/lib/nexxhub/visualizer``), which ``nexxvis`` watches; ``auto``
restores the 300 s cycle.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:  # the learner lives next to us in /usr/local/lib/nexxhub
    import evolve
except Exception:  # pragma: no cover
    evolve = None

SHADER_DIR = Path(os.environ.get("NV_SHADER_DIR", "/usr/local/share/nexxvis/shaders"))
SELECTION = Path(os.environ.get("NV_SHADER_SELECT", "/var/lib/nexxhub/visualizer"))
PORT = int(os.environ.get("NV_WEBUI_PORT", "8099"))
EMBED_FILE = Path(__file__).with_name("embed.js")
GENOME = Path(os.environ.get("NB_GENOME", "/run/nexxbeat/genome"))
SPECTRUM = Path(os.environ.get("NB_SPECTRUM", "/run/nexxbeat/spectrum"))
FEEDBACK = Path(os.environ.get("NB_FEEDBACK", "/run/nexxbeat/feedback"))


def shader_files() -> list[str]:
    try:
        return sorted(p.name for p in SHADER_DIR.glob("*.frag"))
    except OSError:
        return []


def friendly(name: str) -> str:
    base = name[:-5] if name.endswith(".frag") else name
    base = re.sub(r"^\d+[-_]?", "", base)
    return base.replace("-", " ").replace("_", " ").title()


def current_selection() -> str:
    try:
        value = SELECTION.read_text().strip()
    except OSError:
        return "auto"
    return value if value in shader_files() else "auto"


def set_selection(value: str) -> bool:
    if value != "auto" and value not in shader_files():
        return False
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(SELECTION) + ".tmp")
    tmp.write_text(value + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, SELECTION)
    return True


def state() -> dict:
    return {
        "current": current_selection(),
        "shaders": [{"file": f, "name": friendly(f)} for f in shader_files()],
        "feedback": feedback_count(),
    }


def current_genome() -> list[float]:
    try:
        g = [float(x) for x in GENOME.read_text().split()]
    except (OSError, ValueError):
        return []
    return g if len(g) == 8 else []


def feedback_count() -> int:
    try:
        return sum(1 for _ in FEEDBACK.open("r", encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def add_feedback(reward: int) -> int:
    """Append one rated genome for the learner; returns the new sample count."""
    g = current_genome() or [420.0, 6.0, 0.66, 0.90, 1.35, 1.10, 0.82, 0.35]
    f = {"flatness": 0.0, "centroid": 0.0, "energy": 0.0, "conf": 0.0}
    if evolve is not None:
        try:
            f = evolve.read_features(SPECTRUM)
        except Exception:
            pass
    line = json.dumps({"reward": 1 if reward > 0 else -1, "genome": g,
                       "features": f, "t": time.time()})
    FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return feedback_count()


def page() -> str:
    cur = current_selection()
    rows = ['<label class="row"><input type="radio" name="shader" value="auto"%s>'
            '<span>Auto cycle</span><small>rotates every 300 s</small></label>'
            % (" checked" if cur == "auto" else "")]
    for f in shader_files():
        checked = " checked" if cur == f else ""
        rows.append(
            f'<label class="row"><input type="radio" name="shader" '
            f'value="{html.escape(f)}"{checked}><span>{html.escape(friendly(f))}</span>'
            f'<small>{html.escape(f)}</small></label>'
        )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visualizer — nexxxen</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin:0; background:#0b0d12; color:#e8eaf2;
       font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:640px; margin:0 auto; padding:28px 18px 60px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }}
p.sub {{ color:#8f97ad; margin:0 0 22px; }}
.card {{ background:#141824; border:1px solid #232a3a; border-radius:16px; padding:8px; }}
.row {{ display:grid; grid-template-columns:auto 1fr; gap:0 12px; align-items:center;
        padding:12px 14px; border-radius:11px; cursor:pointer; }}
.row:hover {{ background:#1a2030; }}
.row input {{ grid-row:1 / span 2; accent-color:#38bdf8; }}
.row span {{ font-weight:600; }}
.row small {{ color:#7c859c; font-size:.8rem; }}
button {{ margin-top:16px; width:100%; padding:13px; border:0; border-radius:12px;
          background:#38bdf8; color:#06121c; font-weight:700; font-size:1rem; }}
button:disabled {{ opacity:.6; }}
#msg {{ min-height:1.4em; color:#8f97ad; margin-top:12px; }}
.fb {{ display:flex; gap:10px; margin-top:12px; }}
.fb button {{ margin:0; flex:1; }}
.fb .like {{ background:#34d399; }}
.fb .dislike {{ background:#f87171; }}
</style>
<main>
<h1>Visualizer</h1>
<p class="sub">Choose the shader shown on the TV.</p>
<form id="f" class="card">{''.join(rows)}</form>
<button form="f" id="apply">Apply</button>
<div class="fb">
  <button type="button" id="like">Like this look</button>
  <button type="button" id="dislike">Dislike</button>
</div>
<p id="msg"></p>
</main>
<script>
const f=document.getElementById('f'), msg=document.getElementById('msg'),
      apply=document.getElementById('apply');
async function refresh(){{
  const s=await (await fetch('api/state')).json();
  for (const r of f.querySelectorAll('input')) r.checked=(r.value===s.current);
}}
f.addEventListener('submit', async e=>{{
  e.preventDefault(); apply.disabled=true; msg.textContent='Applying…';
  const body=new URLSearchParams(new FormData(f));
  try {{
    const r=await fetch('api/select',{{method:'POST',body}});
    const s=await r.json();
    if(!r.ok) throw new Error(s.error||'failed');
    msg.textContent='Active: '+(s.current==='auto' ? 'auto cycle' : s.current);
    await refresh();
  }} catch(err) {{ msg.textContent='Error: '+err.message; }}
  apply.disabled=false;
}});
const like=document.getElementById('like'), dislike=document.getElementById('dislike');
async function feedback(reward){{
  try {{
    const r=await fetch('api/feedback',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{reward}})}});
    const s=await r.json();
    if(!r.ok) throw new Error(s.error||'failed');
    msg.textContent=(reward>0?'Noted: like':'Noted: dislike')+' · '+s.n+' samples';
  }} catch(err) {{ msg.textContent='Error: '+err.message; }}
}}
like.addEventListener('click',()=>feedback(1));
dislike.addEventListener('click',()=>feedback(-1));
</script>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, page().encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send(200, json.dumps(state()).encode(), "application/json")
        elif self.path == "/embed.js":
            try:
                body = EMBED_FILE.read_bytes()
            except OSError:
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            self._send(200, body, "application/javascript")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:
        if self.path == "/api/feedback":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", "replace")
            ctype = self.headers.get("Content-Type", "")
            reward = 0
            if "application/json" in ctype:
                try:
                    reward = int(json.loads(raw).get("reward", 0))
                except (ValueError, TypeError):
                    reward = 0
            else:
                reward = int((parse_qs(raw).get("reward") or ["0"])[0] or 0)
            if reward not in (1, -1):
                self._send(400, b'{"error":"reward must be 1 or -1"}',
                           "application/json")
                return
            try:
                n = add_feedback(reward)
            except OSError as e:
                self._send(503, json.dumps({"error": str(e)}).encode(),
                           "application/json")
                return
            self._send(200, json.dumps({"ok": True, "n": n}).encode(),
                       "application/json")
            return
        if self.path != "/api/select":
            self._send(404, b'{"error":"not found"}', "application/json")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        value = ""
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                value = str(json.loads(raw).get("shader", ""))
            except ValueError:
                value = ""
        else:
            value = (parse_qs(raw).get("shader") or [""])[0]
        if not set_selection(value):
            self._send(400, b'{"error":"unknown shader"}', "application/json")
            return
        self._send(200, json.dumps(state()).encode(), "application/json")

    def log_message(self, fmt: str, *args) -> None:
        print(f"webui: {fmt % args}", flush=True)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"webui: listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
