"""阶段 0 硬门禁：实测 QtWebEngine 的 Chromium 内核能力。

前端（零改动）依赖 importmap / 100dvh / :has() / crypto.randomUUID /
Array.prototype.at / BroadcastChannel / WebGL。任一为 false 都必须停下上报，
不得擅自改写前端。

探针用 127.0.0.1 的临时 HTTP 服务（secure context，且不碰业务库）提供页面，
由 QWebEngineView 加载并回传检测结果。产物只写 QT/验证/01_启动与环境/。
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QTimer, QUrl, qVersion
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ROOT = Path("D:/work-projects/在役检查系统-指套管数据管理工具")
OUT = ROOT / "08_Qt移植版" / "验证" / "01_启动与环境"
OUT.mkdir(parents=True, exist_ok=True)

HTML = b"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<script type="importmap">{"imports":{"three":"/vendor/three.module.min.js"}}</script>
<title>Qt kernel capability probe</title></head><body><div id="probe"></div></body></html>"""

JS = r"""(function () {
  function safe(fn) { try { return !!fn(); } catch (e) { return false; } }
  var canvas = document.createElement('canvas');
  var webgl = safe(function () { return canvas.getContext('webgl2') || canvas.getContext('webgl'); });
  return JSON.stringify({
    userAgent: navigator.userAgent,
    secureContext: window.isSecureContext === true,
    importmap: safe(function () { return window.HTMLScriptElement && HTMLScriptElement.supports && HTMLScriptElement.supports('importmap'); }),
    dvh: safe(function () { return CSS.supports('height', '100dvh'); }),
    hasSelector: safe(function () { return CSS.supports('selector(:has(*))'); }),
    randomUUID: typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function',
    arrayAt: typeof [].at === 'function',
    replaceAll: typeof ''.replaceAll === 'function',
    broadcastChannel: typeof BroadcastChannel !== 'undefined',
    structuredClone: typeof structuredClone !== 'undefined',
    resizeObserver: typeof ResizeObserver !== 'undefined',
    webgl: webgl,
    esModules: 'noModule' in document.createElement('script'),
    dialogElement: typeof HTMLDialogElement !== 'undefined'
  });
})()"""


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *_args):
        pass


def main() -> int:
    app = QApplication(sys.argv)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    state: dict = {"done": False}
    view = QWebEngineView()
    view.resize(1000, 700)
    page = view.page()

    def finish(payload: dict) -> None:
        if state["done"]:
            return
        state["done"] = True
        state["payload"] = payload
        try:
            server.shutdown()
        except Exception:
            pass
        QTimer.singleShot(0, app.quit)

    def on_js(raw) -> None:
        payload = {"load_ok": True}
        try:
            payload["capabilities"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception as exc:
            payload["js_error"] = str(exc)
        finish(payload)

    def on_load(ok: bool) -> None:
        if not ok:
            finish({"load_ok": False, "error": "page load failed"})
            return
        page.runJavaScript(JS, on_js)

    page.loadFinished.connect(on_load)
    page.load(QUrl(f"http://127.0.0.1:{port}/probe"))
    QTimer.singleShot(30000, lambda: finish({"load_ok": False, "error": "timeout 30s"}) if not state["done"] else None)
    app.exec()

    payload = state.get("payload", {"load_ok": False, "error": "no result"})
    caps = payload.get("capabilities", {})
    ua = caps.get("userAgent", "")
    m = re.search(r"Chrome/(\d+)\.", ua)
    chromium_major = int(m.group(1)) if m else 0

    required = {
        "importmap": "Chromium >= 89（三维页两处 importmap）",
        "dvh": "Chromium >= 108（20+ 处 100dvh 主布局）",
        "hasSelector": "Chromium >= 105（15 处 :has() 交互态样式）",
        "randomUUID": "Chromium >= 92（task-progress.js 硬调用）",
        "arrayAt": "Chromium >= 92（analysis-center.js / tube-state-workspace.js）",
        "broadcastChannel": "登录态跨窗口同步",
        "webgl": "Three.js 三维渲染",
        "esModules": "50 个 ESM 模块",
    }
    checks = {k: bool(caps.get(k)) for k in required}
    passed = payload.get("load_ok") is True and chromium_major >= 108 and all(checks.values())

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pyside6": PYSIDE_VERSION,
        "qt": qVersion(),
        "chromium_major": chromium_major,
        "probe_url": f"http://127.0.0.1:{port}/probe",
        "capabilities": caps,
        "required": required,
        "checks": checks,
        "passed": passed,
        "raw": payload,
    }
    (OUT / "内核能力.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 阶段 0 内核能力探针", "",
        "- 时间：" + report["generated_at"],
        "- PySide6 " + PYSIDE_VERSION + " / Qt " + qVersion() + " / Chromium " + str(chromium_major),
        "- UA：" + ua,
        "- 页面加载：" + str(payload.get("load_ok")),
        "", "## 必需能力", "",
        "| 能力 | 结果 | 说明 |", "|---|---|---|",
    ]
    for k, note in required.items():
        lines.append("| " + k + " | " + ("✅" if checks[k] else "❌") + " | " + note + " |")
    lines += [
        "", "## 其他观测", "",
        "- secureContext: " + str(caps.get("secureContext")),
        "- structuredClone: " + str(caps.get("structuredClone")),
        "- resizeObserver: " + str(caps.get("resizeObserver")),
        "- replaceAll: " + str(caps.get("replaceAll")),
        "- dialogElement: " + str(caps.get("dialogElement")),
        "", "**门禁判定：" + ("通过 — 可继续（前端零改动 1:1 成立）" if passed else "未通过 — 停止实施并上报") + "**",
    ]
    (OUT / "内核能力结论.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("PySide6", PYSIDE_VERSION, "Qt", qVersion(), "Chromium", chromium_major)
    print("UA", ua)
    for k, v in checks.items():
        print("  ", "OK " if v else "FAIL", k, v)
    print("PASSED", passed)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
