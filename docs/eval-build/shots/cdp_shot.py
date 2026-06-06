"""Tiny CDP screenshot helper for verifying the Agent Central UI.

Launches headless Chrome with remote debugging, navigates to a URL, dismisses the
first-visit onboarding overlay, optionally runs a JS snippet (e.g. open a popup),
waits, and writes a PNG. No third-party browser-automation deps (just the
websocket-client + Chrome already on the machine).

Usage:
  python cdp_shot.py --url http://127.0.0.1:8001/ --out office.png
  python cdp_shot.py --url http://127.0.0.1:8001/ --out card.png \
      --js "window.openEvaluatorPopup()" --settle 1500
"""
import argparse
import base64
import json
import os
import subprocess
import time
import urllib.request

import websocket  # websocket-client (sync)

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9223
PROFILE = r"C:\Users\KalataTheBest\AppData\Local\Temp\chrome-eval-cdp"

# Hide the cold-open onboarding card so the office/canvas is visible in one shot.
_SKIP_ONBOARD = (
    "try{localStorage.setItem('ac_onboarded_v1','1');"
    "var o=document.getElementById('onboarding');if(o)o.classList.add('hidden');}"
    "catch(e){}"
)


def _send(ws, mid, method, params=None):
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--js", default="")
    ap.add_argument("--wait", type=int, default=4500, help="ms after navigate")
    ap.add_argument("--settle", type=int, default=1200, help="ms after setup JS")
    ap.add_argument("--w", type=int, default=1600)
    ap.add_argument("--h", type=int, default=1000)
    args = ap.parse_args()

    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}", f"--window-size={args.w},{args.h}",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(40):
            try:
                data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                pages = [t for t in data if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if not ws_url:
            raise RuntimeError("could not find a CDP page target")

        ws = websocket.create_connection(ws_url, timeout=30, max_size=None)
        mid = 0
        mid += 1; _send(ws, mid, "Page.enable")
        mid += 1; _send(ws, mid, "Runtime.enable")
        mid += 1; _send(ws, mid, "Page.navigate", {"url": args.url})
        time.sleep(args.wait / 1000.0)
        mid += 1; _send(ws, mid, "Runtime.evaluate", {"expression": _SKIP_ONBOARD})
        if args.js:
            mid += 1; _send(ws, mid, "Runtime.evaluate", {"expression": args.js})
        time.sleep(args.settle / 1000.0)
        mid += 1
        resp = _send(ws, mid, "Page.captureScreenshot", {"format": "png"})
        b64 = resp["result"]["data"]
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "wb") as f:
            f.write(base64.b64decode(b64))
        ws.close()
        print(f"wrote {args.out}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
