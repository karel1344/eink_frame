#!/usr/bin/env python3
"""Interactive E-Ink preview web UI.

슬라이더를 움직이면 E-Ink 변환 결과가 실시간으로 업데이트됩니다.

Usage:
    python scripts/preview_web.py
    # 브라우저에서 http://localhost:7860 열기

    python scripts/preview_web.py --port 8080

Dependencies: pip install Pillow fastapi uvicorn python-multipart
"""

from __future__ import annotations

import argparse
import base64
import io
import sys

try:
    from PIL import Image, ImageEnhance
except ImportError:
    print("ERROR: pip install Pillow")
    sys.exit(1)

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("ERROR: pip install fastapi uvicorn python-multipart")
    sys.exit(1)

# ── Display spec & palette (must match driver.py) ────────────────────────────
DISPLAY_W, DISPLAY_H = 800, 480

PALETTE_RGB = [
    (  0,   0,   0),   # 0: Black
    (255, 255, 255),   # 1: White
    (207, 212,   4),   # 2: Yellow
    (150,  28,  23),   # 3: Red
    (  0,   0,   0),   # 4: unused
    ( 12,  84, 172),   # 5: Blue
    ( 29,  90,  72),   # 6: Green
]
COLOR_NAMES = ["Black", "White", "Yellow", "Red", "(unused)", "Blue", "Green"]

# In-memory image store (single-user dev tool)
_stored: Image.Image | None = None

app = FastAPI()


# ── Image processing helpers ──────────────────────────────────────────────────

def _build_palette() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat = [c for rgb in PALETTE_RGB for c in rgb] + [0] * (3 * (256 - len(PALETTE_RGB)))
    pal.putpalette(flat)
    return pal


def _to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _exif_rotate(img: Image.Image) -> Image.Image:
    try:
        from PIL import ExifTags
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        exif = img._getexif()  # type: ignore[attr-defined]
        if exif:
            ori = exif.get(tag_map.get("Orientation", 0))
            if ori in {3: 180, 6: 270, 8: 90}:
                return img.rotate({3: 180, 6: 270, 8: 90}[ori], expand=True)
    except Exception:
        pass
    return img


def _resize_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    img.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


def _resize_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    sr = img.width / img.height
    dr = w / h
    if sr > dr:
        nw, nh = int(img.width * h / img.height), h
    else:
        nw, nh = w, int(img.height * w / img.width)
    img = img.resize((nw, nh), Image.LANCZOS)
    return img.crop(((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))


def _apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    lut = [int((i / 255) ** (1.0 / gamma) * 255 + 0.5) for i in range(256)]
    return img.point(lut * 3)


def _apply_warmth(img: Image.Image, warmth: float) -> Image.Image:
    r, g, b = img.split()
    r = r.point([min(255, int(i * warmth)) for i in range(256)])
    b = b.point([min(255, int(i / warmth)) for i in range(256)])
    return Image.merge("RGB", (r, g, b))


def run_pipeline(img: Image.Image, p: dict) -> tuple[Image.Image, dict]:
    if p.get("fill"):
        img = _resize_fill(img, DISPLAY_W, DISPLAY_H)
    else:
        img = _resize_fit(img, DISPLAY_W, DISPLAY_H)

    img = img.convert("RGB")

    if (v := p.get("brightness", 1.0)) != 1.0:
        img = ImageEnhance.Brightness(img).enhance(v)
    if (v := p.get("gamma", 1.0)) != 1.0:
        img = _apply_gamma(img, v)
    if (v := p.get("contrast", 1.0)) != 1.0:
        img = ImageEnhance.Contrast(img).enhance(v)
    if (v := p.get("saturation", 1.0)) != 1.0:
        img = ImageEnhance.Color(img).enhance(v)
    if (v := p.get("sharpness", 1.0)) != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(v)
    if (v := p.get("warmth", 1.0)) != 1.0:
        img = _apply_warmth(img, v)

    dither_flag = Image.Dither.FLOYDSTEINBERG if p.get("dither", "fs") == "fs" else Image.Dither.NONE
    quantized = img.quantize(palette=_build_palette(), dither=dither_flag)

    raw = quantized.tobytes("raw")
    total = len(raw)
    counts = [0] * len(PALETTE_RGB)
    for b in raw:
        if b < len(counts):
            counts[b] += 1
    stats = {COLOR_NAMES[i]: round(counts[i] / total * 100, 1)
             for i in range(len(PALETTE_RGB)) if COLOR_NAMES[i] != "(unused)"}

    return quantized.convert("RGB"), stats


# ── API routes ────────────────────────────────────────────────────────────────

class Params(BaseModel):
    brightness: float = 1.0
    gamma: float = 1.0
    contrast: float = 1.2
    saturation: float = 1.5
    sharpness: float = 1.3
    warmth: float = 1.0
    dither: str = "fs"
    fill: bool = False


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    global _stored
    try:
        data = await file.read()
        img = Image.open(io.BytesIO(data))
        img = _exif_rotate(img).convert("RGB")
        _stored = img
        thumb = img.copy()
        thumb.thumbnail((DISPLAY_W, DISPLAY_H), Image.LANCZOS)
        return {"original_b64": _to_b64(thumb), "width": img.width, "height": img.height}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/process")
async def process(params: Params):
    if _stored is None:
        raise HTTPException(status_code=400, detail="이미지를 먼저 업로드하세요")
    simulated, stats = run_pipeline(_stored.copy(), params.model_dump())
    return {"simulated_b64": _to_b64(simulated), "stats": stats}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


# ── Embedded UI ───────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-Ink Preview</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#161616;color:#ddd;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
header{background:#1e1e1e;border-bottom:1px solid #2e2e2e;padding:11px 20px;display:flex;align-items:center;justify-content:space-between}
h1{font-size:15px;font-weight:600;color:#e8e8e8}
.upload-label{background:#2563eb;color:#fff;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px;user-select:none;transition:background .15s}
.upload-label:hover{background:#1d4ed8}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}
.panel{background:#1e1e1e;border-radius:8px;overflow:hidden;border:1px solid #2a2a2a}
.panel-hd{padding:7px 12px;font-size:11px;color:#777;background:#222;display:flex;justify-content:space-between;border-bottom:1px solid #2a2a2a}
.img-wrap{position:relative;aspect-ratio:800/480;background:#111;display:flex;align-items:center;justify-content:center;overflow:hidden}
.drop-zone{width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;border:2px dashed #333;cursor:pointer;color:#555;font-size:13px;transition:border-color .2s,color .2s}
.drop-zone.over{border-color:#2563eb;color:#2563eb}
.panel img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:none}
.panel img.loaded{display:block}
.spinner{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.45)}
.spinner.show{display:flex}
.dot{width:7px;height:7px;border-radius:50%;background:#2563eb;margin:0 3px;animation:blink 1s ease infinite}
.dot:nth-child(2){animation-delay:.15s}
.dot:nth-child(3){animation-delay:.3s}
@keyframes blink{0%,80%,100%{transform:scale(.7);opacity:.3}40%{transform:scale(1.15);opacity:1}}
.controls{margin:0 14px 14px;background:#1e1e1e;border-radius:8px;padding:16px;border:1px solid #2a2a2a}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px 28px}
.ctrl{display:flex;flex-direction:column;gap:6px}
.ctrl-hd{display:flex;justify-content:space-between;font-size:11px}
.ctrl-name{color:#888}
.ctrl-val{color:#fff;font-weight:700;font-variant-numeric:tabular-nums;min-width:36px;text-align:right}
input[type=range]{width:100%;accent-color:#2563eb;cursor:pointer;height:3px}
.row{display:flex;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap}
select{background:#2a2a2a;color:#ddd;border:1px solid #3a3a3a;padding:5px 8px;border-radius:5px;font-size:12px;cursor:pointer}
.tog{background:#2a2a2a;color:#999;border:1px solid #3a3a3a;padding:5px 12px;border-radius:5px;font-size:12px;cursor:pointer;transition:all .15s}
.tog.on{background:#1e3a5f;border-color:#2563eb;color:#93c5fd}
.rst{background:#2a2a2a;color:#888;border:1px solid #3a3a3a;padding:5px 12px;border-radius:5px;font-size:12px;cursor:pointer}
.rst:hover{background:#333}
.dl{margin-left:auto;background:#14532d;color:#86efac;border:none;padding:7px 16px;border-radius:6px;font-size:13px;cursor:pointer;transition:background .15s}
.dl:hover{background:#166534}
.dl:disabled{opacity:.35;cursor:default}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;padding-top:14px;border-top:1px solid #2a2a2a}
.stat{display:flex;align-items:center;gap:5px;font-size:11px}
.swatch{width:10px;height:10px;border-radius:2px;border:1px solid rgba(255,255,255,.1)}
.sname{color:#888}
.spct{color:#ddd;font-weight:600;font-variant-numeric:tabular-nums}
</style>
</head>
<body>
<header>
  <h1>E-Ink Display Preview</h1>
  <label class="upload-label">
    이미지 선택
    <input type="file" id="fi" accept="image/*" style="display:none">
  </label>
</header>

<div class="panels">
  <div class="panel">
    <div class="panel-hd"><span>원본</span><span id="sz" style="color:#444">—</span></div>
    <div class="img-wrap" id="dz">
      <div class="drop-zone" id="dm">
        <span style="font-size:28px">🖼</span>
        <span>이미지를 드래그하거나 클릭해서 업로드</span>
        <span style="font-size:11px;color:#444">JPEG · PNG · HEIC</span>
      </div>
      <img id="orig" alt="original">
    </div>
  </div>
  <div class="panel">
    <div class="panel-hd"><span>E-Ink 시뮬레이션</span><span style="color:#444">800 × 480</span></div>
    <div class="img-wrap">
      <img id="sim" alt="simulated">
      <div class="spinner" id="sp"><div style="display:flex"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div>
    </div>
  </div>
</div>

<div class="controls">
  <div class="grid" id="sliders"></div>
  <div class="row">
    <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#888">
      dither
      <select id="dither">
        <option value="fs">Floyd-Steinberg</option>
        <option value="none">None (포스터)</option>
      </select>
    </div>
    <button class="tog" id="fillBtn" onclick="toggleFill()">fit</button>
    <button class="rst" onclick="resetAll()">초기화</button>
    <button class="dl" id="dlBtn" disabled onclick="download()">다운로드</button>
  </div>
  <div class="stats" id="stats"></div>
</div>

<script>
const SLIDERS = [
  {id:'brightness', label:'brightness', min:0.3, max:3.0, step:0.05, def:1.0},
  {id:'gamma',      label:'gamma',      min:0.3, max:3.0, step:0.05, def:1.0},
  {id:'contrast',   label:'contrast',   min:0.5, max:3.0, step:0.05, def:1.2},
  {id:'saturation', label:'saturation', min:0.0, max:4.0, step:0.1,  def:1.5},
  {id:'sharpness',  label:'sharpness',  min:0.0, max:3.0, step:0.1,  def:1.3},
  {id:'warmth',     label:'warmth',     min:0.3, max:3.0, step:0.05, def:1.0},
];

const SWATCHES = {Black:'#2a2a2a',White:'#e0e0e0',Yellow:'#cfce04',Red:'#961c17',Blue:'#0c54ac',Green:'#1d5a48'};

let fillMode=false, simB64=null, hasImg=false, timer=null;

// Build slider HTML
const grid = document.getElementById('sliders');
SLIDERS.forEach(s => {
  grid.innerHTML += `
    <div class="ctrl">
      <div class="ctrl-hd">
        <span class="ctrl-name">${s.label}</span>
        <span class="ctrl-val" id="${s.id}V">${s.def.toFixed(2)}</span>
      </div>
      <input type="range" id="${s.id}" min="${s.min}" max="${s.max}" step="${s.step}" value="${s.def}">
    </div>`;
});

SLIDERS.forEach(s => {
  document.getElementById(s.id).addEventListener('input', e => {
    document.getElementById(s.id+'V').textContent = parseFloat(e.target.value).toFixed(2);
    schedule();
  });
});
document.getElementById('dither').addEventListener('change', schedule);

function schedule() {
  if (!hasImg) return;
  clearTimeout(timer);
  timer = setTimeout(update, 180);
}

function params() {
  const p = {fill: fillMode, dither: document.getElementById('dither').value};
  SLIDERS.forEach(s => { p[s.id] = parseFloat(document.getElementById(s.id).value); });
  return p;
}

async function update() {
  if (!hasImg) return;
  document.getElementById('sp').classList.add('show');
  try {
    const r = await fetch('/process', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(params())
    });
    const d = await r.json();
    const img = document.getElementById('sim');
    img.src = 'data:image/png;base64,' + d.simulated_b64;
    img.classList.add('loaded');
    simB64 = d.simulated_b64;
    document.getElementById('dlBtn').disabled = false;
    renderStats(d.stats);
  } finally {
    document.getElementById('sp').classList.remove('show');
  }
}

function renderStats(stats) {
  const el = document.getElementById('stats');
  el.innerHTML = Object.entries(stats).map(([n,v]) =>
    `<div class="stat">
       <div class="swatch" style="background:${SWATCHES[n]||'#888'}"></div>
       <span class="sname">${n}</span>
       <span class="spct">${v}%</span>
     </div>`
  ).join('');
}

function toggleFill() {
  fillMode = !fillMode;
  const b = document.getElementById('fillBtn');
  b.textContent = fillMode ? 'fill' : 'fit';
  b.classList.toggle('on', fillMode);
  schedule();
}

function resetAll() {
  SLIDERS.forEach(s => {
    document.getElementById(s.id).value = s.def;
    document.getElementById(s.id+'V').textContent = s.def.toFixed(2);
  });
  document.getElementById('dither').value = 'fs';
  fillMode = false;
  document.getElementById('fillBtn').textContent = 'fit';
  document.getElementById('fillBtn').classList.remove('on');
  schedule();
}

function download() {
  if (!simB64) return;
  const a = document.createElement('a');
  a.href = 'data:image/png;base64,' + simB64;
  a.download = 'eink_preview.png';
  a.click();
}

async function handleFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  document.getElementById('dm').style.display = 'none';
  document.getElementById('sp').classList.add('show');
  try {
    const r = await fetch('/upload', {method:'POST', body:fd});
    const d = await r.json();
    if (d.detail) { alert('오류: ' + d.detail); return; }
    const img = document.getElementById('orig');
    img.src = 'data:image/png;base64,' + d.original_b64;
    img.classList.add('loaded');
    document.getElementById('sz').textContent = d.width + ' × ' + d.height;
    hasImg = true;
    update();
  } catch(e) {
    alert('업로드 실패: ' + e.message);
    document.getElementById('sp').classList.remove('show');
  }
}

document.getElementById('fi').addEventListener('change', e => handleFile(e.target.files[0]));
document.getElementById('dz').addEventListener('click', () => { if (!hasImg) document.getElementById('fi').click(); });

document.addEventListener('dragover', e => { e.preventDefault(); document.getElementById('dm').classList.add('over'); });
document.addEventListener('dragleave', () => document.getElementById('dm').classList.remove('over'));
document.addEventListener('drop', e => {
  e.preventDefault();
  document.getElementById('dm').classList.remove('over');
  handleFile(e.dataTransfer.files[0]);
});
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="E-Ink preview web UI")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"E-Ink Preview UI → http://{args.host}:{args.port}")
    print("브라우저에서 열고, 이미지를 드래그하거나 클릭해서 업로드하세요.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
