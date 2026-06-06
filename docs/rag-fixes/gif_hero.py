"""Capture a fresh hero GIF of the current build, $0 (no API spend).

One headless-Chrome CDP session: dismiss the onboarding card, capture several
frames of the live office (agents walking), then open the Evaluator scorecard
(now showing real current numbers) and dwell on it. Frames are downscaled and
palette-quantized with Pillow so the GIF stays lean (< 3MB). The server must be
running key-unset on :8001 with the current scorecard already saved.
"""
import base64
import io
import json
import os
import subprocess
import time
import urllib.request

import websocket
from PIL import Image

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9224
PROFILE = r"C:\Users\KalataTheBest\AppData\Local\Temp\chrome-rag-gif"
URL = "http://127.0.0.1:8001/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero-demo.gif")
W, H = 1280, 800
SCALE_W = 760  # downscaled GIF width (keeps size down)

_SKIP_ONBOARD = (
    "try{localStorage.setItem('ac_onboarded_v1','1');"
    "var o=document.getElementById('onboarding');if(o)o.classList.add('hidden');}catch(e){}"
)


def _send(ws, mid, method, params=None):
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid:
            return m


def _shot(ws, mid):
    resp = _send(ws, mid, "Page.captureScreenshot", {"format": "png"})
    return base64.b64decode(resp["result"]["data"])


def main():
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}", f"--window-size={W},{H}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = []
    try:
        ws_url = None
        for _ in range(40):
            try:
                data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                pages = [t for t in data if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]; break
            except Exception:
                pass
            time.sleep(0.25)
        ws = websocket.create_connection(ws_url, timeout=30, max_size=None)
        mid = 0
        mid += 1; _send(ws, mid, "Page.enable")
        mid += 1; _send(ws, mid, "Runtime.enable")
        mid += 1; _send(ws, mid, "Page.navigate", {"url": URL})
        time.sleep(5.0)
        mid += 1; _send(ws, mid, "Runtime.evaluate", {"expression": _SKIP_ONBOARD})
        time.sleep(1.0)

        # Office motion frames.
        for _ in range(9):
            mid += 1; frames.append((_shot(ws, mid), 420))
            time.sleep(0.42)
        # Open the Evaluator scorecard, let it load, dwell on it.
        mid += 1; _send(ws, mid, "Runtime.evaluate", {"expression": "window.openEvaluatorPopup()"})
        time.sleep(1.4)
        mid += 1; frames.append((_shot(ws, mid), 1400))
        mid += 1; frames.append((_shot(ws, mid), 2600))  # final dwell on real numbers
        ws.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    # Assemble: downscale + palette-quantize for a lean GIF.
    imgs, durations = [], []
    for png, dur in frames:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = im.size
        im = im.resize((SCALE_W, int(h * SCALE_W / w)), Image.LANCZOS)
        imgs.append(im.quantize(colors=128, method=Image.MEDIANCUT))
        durations.append(dur)
    imgs[0].save(OUT, save_all=True, append_images=imgs[1:], duration=durations,
                 loop=0, optimize=True, disposal=2)
    size = os.path.getsize(OUT)
    print(f"wrote {OUT} ({size/1e6:.2f} MB, {len(imgs)} frames)")


if __name__ == "__main__":
    main()
