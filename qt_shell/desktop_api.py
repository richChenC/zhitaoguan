"""desktopAPI 的 Qt 实现（20 个方法，对应 preload.cjs / main.cjs 的 18 个 handle）。

QWebChannel 只暴露一个通用 Slot ``invoke(envelope_json) -> result_json``，
避免 18 个签名不一致的 Slot；shim 侧把 20 个方法映射到它。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QStandardPaths, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from .artifact_save import (
    ArtifactSaveError, artifact_name, sanitize_filename, save_artifact, with_png_author,
)
from .authorized_export import ExportAuthError, authorized_export
from .constants import (
    APP_ICON, CORE_IMAGE_MAX_BYTES, DOCS_DIR, EXCEL_EXTENSIONS, EXCEL_SCAN_LIMIT,
    HEADER_MAX_BYTES, OFFICE_MAX_BYTES, PNG_SIGNATURE, RUNTIME,
    SETTINGS_SECTIONS, USER_DATA, VISUALIZATION_PANELS, VIS_IMAGE_MAX_BYTES, ZIP_SIGNATURE,
)
from .factory_reset import schedule as schedule_factory_reset


def _documents_dir() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)


def _decode_bytes(value) -> bytes:
    if isinstance(value, dict) and "__qt_b64__" in value:
        return base64.b64decode(value["__qt_b64__"] or "")
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (list, tuple)):
        return bytes(value)
    raise ArtifactSaveError("导出文件内容无效，请重新导出。")


class DesktopAPI(QObject):
    downloadStatus = Signal(str)
    settingsSection = Signal(str)

    def __init__(self, profile_provider) -> None:
        super().__init__()
        self._profile = profile_provider
        self._shell = None
        self._last_href = ""

    def set_shell(self, shell) -> None:
        self._shell = shell

    def emit_download_status(self, payload_json: str) -> None:
        self.downloadStatus.emit(payload_json)

    def emit_settings_section(self, section: str) -> None:
        self.settingsSection.emit(section)

    # ---- QWebChannel 入口 ---------------------------------------------
    @Slot(str, result=str)
    def invoke(self, envelope: str) -> str:
        try:
            request = json.loads(envelope)
            method = str(request.get("method") or "")
            self._last_href = str(request.get("href") or "")
            value = self._dispatch(method, request.get("payload"))
            return json.dumps({"value": value}, ensure_ascii=False, default=str)
        except Exception as exc:  # 任何异常都要回传可读文案给前端
            return json.dumps({"__qt_error__": str(exc)}, ensure_ascii=False)

    def _owner(self):
        return QApplication.activeWindow() or None

    def _cookie(self) -> str:
        profile = self._profile() if callable(self._profile) else self._profile
        return profile.cookie_header() if profile else ""

    def _require_local_href(self) -> None:
        if not self._last_href.startswith(RUNTIME.base_url + "/"):
            raise RuntimeError("导出请求来源无效")

    # ---- 分发 ---------------------------------------------------------
    def _dispatch(self, method: str, payload):
        if method == "__qt_ping":
            return {"pong": True, "instance": RUNTIME.base_url}

        if method == "factory-reset":
            origin = urlsplit(self._last_href)
            base = urlsplit(RUNTIME.base_url)
            if (origin.scheme, origin.hostname, origin.port) != (base.scheme, base.hostname, base.port):
                raise RuntimeError("请求来源无效")
            request = urllib.request.Request(RUNTIME.base_url + "/api/auth/me", headers={"Cookie": self._cookie()})
            with urllib.request.urlopen(request, timeout=10) as response:
                user = json.loads(response.read().decode("utf-8")).get("user") or {}
            if "users.manage" not in user.get("permissions", []):
                raise RuntimeError("只有管理员可以恢复出厂设置")
            text, confirmed = QInputDialog.getText(
                self._owner(), "恢复出厂设置",
                "下次启动将清空当前账户、检测数据和软件设置，并重新创建管理员。"
                "\n原数据库将保存至本机备份目录；已有备份和导出文件保留。"
                "\n软件将关闭，请先保存未完成的工作。\n\n输入“恢复出厂”以确认：",
            )
            if not confirmed or text != "恢复出厂":
                return {"scheduled": False}
            if not self._shell:
                raise RuntimeError("软件窗口尚未就绪")
            schedule_factory_reset(USER_DATA)
            QTimer.singleShot(500, self._shell.request_exit)
            return {"scheduled": True}

        if method == "select-directory":
            path = QFileDialog.getExistingDirectory(
                self._owner(), "选择指套管检测数据文件夹", ""
            )
            return path or None

        if method == "select-excel":
            paths, _ = QFileDialog.getOpenFileNames(
                self._owner(), "选择指套管解析结果 Excel（可多选）", "",
                "Excel 工作簿 (*.xlsx *.xlsm *.xls)",
            )
            return list(paths or [])

        if method == "select-excel-folder":
            folder = QFileDialog.getExistingDirectory(
                self._owner(), "选择包含解析结果 Excel 的文件夹", ""
            )
            if not folder:
                return None
            files = _scan_excel_files(Path(folder))
            return {"folder": folder, "files": files, "truncated": len(files) >= EXCEL_SCAN_LIMIT}

        if method in ("save-core-image", "save-visualization-image"):
            return self._save_png(method, payload or {})

        if method in ("save-ledger", "save-office-file"):
            return self._save_office(method, payload or {})

        if method == "save-provenance":
            return self._save_provenance(payload or {})

        if method == "open-report-header":
            path, _ = QFileDialog.getOpenFileName(
                self._owner(), "导入报告表头设置", "", "报告表头设置 (*.json)"
            )
            if not path:
                return None
            target = Path(path)
            if not target.is_file() or target.stat().st_size > HEADER_MAX_BYTES:
                raise RuntimeError("报告表头设置文件过大或无效")
            return target.read_text(encoding="utf-8")

        if method == "save-report-header":
            return self._save_report_header(payload or {})

        if method == "select-backup-directory":
            return QFileDialog.getExistingDirectory(
                self._owner(), "选择数据库备份的保存文件夹", ""
            ) or None

        if method == "select-backup-file":
            path, _ = QFileDialog.getOpenFileName(
                self._owner(), "选择要恢复的数据库备份文件", "", "数据库备份 (*.db)"
            )
            return path or None

        if method == "open-local-document":
            return self._open_local_document(str(payload or ""))

        if method == "open-documents-folder":
            if not DOCS_DIR.is_dir():
                raise RuntimeError("说明文档目录不存在。")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(DOCS_DIR)))
            return {"path": str(DOCS_DIR)}

        if method == "open-settings-window":
            section = str(payload or "settingsDataPane")
            if section not in SETTINGS_SECTIONS:
                section = "settingsDataPane"
            if self._shell:
                self._shell.open_settings_window(section)
            return None

        if method == "open-visualization-window":
            return self._open_visualization_window(payload or {})

        if method == "close-settings-window":
            if self._shell:
                self._shell.close_settings_window()
            return None

        if method == "get-workspace-report-scope":
            # shim 已在渲染进程直接读 DOM；此处为兜底
            return {"scope": {}, "records": []}

        raise RuntimeError(f"未知的桌面接口：{method}")

    # ---- 导出 ---------------------------------------------------------
    def _export_auth(self):
        self._require_local_href()
        return authorized_export(self._cookie())

    def _save_export(self, file_path: str, content: bytes) -> str:
        session = self._export_auth()
        if file_path.lower().endswith(".png"):
            content = with_png_author(content, (session.get("user") or {}).get("username", ""))
        save_artifact(file_path, content)
        try:
            authorized_export(self._cookie(), {
                "name": Path(file_path).name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            })
        except ExportAuthError as exc:
            QMessageBox.warning(
                self._owner(), "导出记录未登记",
                f"文件已保存，导出记录暂未登记。\n\n保存位置：{file_path}\n"
                f"原因：{exc}\n文件可正常使用，无需重复导出。",
            )
        return file_path

    def _save_png(self, method: str, payload: dict) -> str | None:
        self._export_auth()
        match = re.fullmatch(r"data:image/png;base64,([A-Za-z0-9+/=]+)", str(payload.get("dataUrl") or ""))
        if not match:
            raise RuntimeError("管板图片数据格式无效" if method == "save-core-image"
                               else "可视化图片数据格式无效")
        image = base64.b64decode(match.group(1))
        limit = CORE_IMAGE_MAX_BYTES if method == "save-core-image" else VIS_IMAGE_MAX_BYTES
        if len(image) < 100 or len(image) > limit or image[:8] != PNG_SIGNATURE:
            raise RuntimeError("管板图片数据校验失败" if method == "save-core-image"
                               else "可视化图片数据校验失败")
        if method == "save-core-image":
            kind, scope, title = "管板缺陷分布", "当前范围", "导出指套管缺陷分布图"
        else:
            kind, scope, title = "可视化图表", "当前范围", "导出可视化图表 PNG"
        default_name = sanitize_filename(
            payload.get("defaultName") or artifact_name(kind, scope, "png")
        )
        path, _ = QFileDialog.getSaveFileName(
            self._owner(), title, str(Path(_documents_dir()) / default_name), "PNG 图片 (*.png)"
        )
        if not path:
            return None
        return self._save_export(path, image)

    def _save_office(self, method: str, payload: dict) -> str | None:
        self._export_auth()
        workbook = _decode_bytes(payload.get("bytes"))
        if len(workbook) < 4 or len(workbook) > OFFICE_MAX_BYTES:
            raise RuntimeError("导出文件大小或格式无效，请重新导出。")
        if workbook[:4] != ZIP_SIGNATURE:
            raise RuntimeError("导出文件格式无效，请重新导出。")
        name = sanitize_filename(payload.get("defaultName") or "")
        ext = Path(name).suffix.lower()
        if ext not in (".xlsx", ".docx"):
            raise RuntimeError("不支持的导出文件格式。")
        label = "Excel 工作簿" if ext == ".xlsx" else "Word 文档"
        title = "保存管子综合台账" if method == "save-ledger" else "保存导出文件"
        path, _ = QFileDialog.getSaveFileName(
            self._owner(), title, str(Path(_documents_dir()) / name), f"{label} (*{ext})"
        )
        if not path:
            return None
        return self._save_export(path, workbook)

    def _save_provenance(self, payload: dict) -> str | None:
        self._export_auth()
        content = _decode_bytes(payload.get("bytes"))
        if not content or len(content) > OFFICE_MAX_BYTES:
            raise RuntimeError("来源凭证大小或格式无效，请重新导出。")
        name = sanitize_filename(payload.get("defaultName") or "")
        if not name.lower().endswith(".provenance.json"):
            raise RuntimeError("来源凭证文件名无效。")
        try:
            evidence = json.loads(content.decode("utf-8"))
            sha = (evidence or {}).get("sha256")
            if not (
                evidence
                and (isinstance(evidence.get("export_kind"), str)
                     or isinstance(evidence.get("snapshot_id"), str))
                and isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha, re.I)
            ):
                raise ValueError
        except (ValueError, UnicodeDecodeError, AttributeError) as exc:
            raise RuntimeError("来源凭证内容无效，请重新导出。") from exc
        path, _ = QFileDialog.getSaveFileName(
            self._owner(), "保存来源与核查凭证",
            str(Path(_documents_dir()) / name), "JSON 凭证 (*.json)",
        )
        if not path:
            return None
        return self._save_export(path, content)

    def _save_report_header(self, payload: dict) -> str | None:
        self._export_auth()
        content = str(payload.get("content") or "")
        if not content or len(content.encode("utf-8")) > HEADER_MAX_BYTES:
            raise RuntimeError("报告表头设置内容无效")
        try:
            json.loads(content)
        except ValueError as exc:
            raise RuntimeError("报告表头设置内容无效") from exc
        default_name = sanitize_filename(
            payload.get("defaultName") or artifact_name("报告表头设置", "指套管", "json")
        )
        path, _ = QFileDialog.getSaveFileName(
            self._owner(), "导出报告表头设置",
            str(Path(_documents_dir()) / default_name), "报告表头设置 (*.json)",
        )
        if not path:
            return None
        return self._save_export(path, content.encode("utf-8"))

    # ---- 文档 / 窗口 --------------------------------------------------
    @staticmethod
    def _open_local_document(relative_path: str) -> dict:
        root = DOCS_DIR.resolve()
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError("文档路径无效。")
        if not target.is_file():
            raise RuntimeError("文档不存在，请检查 docs 文件夹。")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        return {"path": str(target)}

    def _open_visualization_window(self, payload: dict) -> None:
        self._require_local_href()
        panel = str(payload.get("panel") or "")
        if panel not in VISUALIZATION_PANELS:
            raise RuntimeError("可视化窗口参数无效")
        state = json.dumps(payload.get("state") or {}, ensure_ascii=False)
        if len(state) > 16000:
            raise RuntimeError("可视化筛选条件过长")
        if self._shell:
            self._shell.open_visualization_window(panel, state)
        return None


def _scan_excel_files(directory: Path, depth: int = 0, collected: list[str] | None = None) -> list[str]:
    """对应 main.cjs:471-489。"""
    result = collected if collected is not None else []
    if len(result) >= EXCEL_SCAN_LIMIT or depth > 4:
        return result
    try:
        entries = list(directory.iterdir())
    except OSError:
        return result
    for entry in entries:
        if len(result) >= EXCEL_SCAN_LIMIT:
            break
        if entry.is_file() and entry.suffix.lower() in EXCEL_EXTENSIONS:
            result.append(str(entry))
        elif entry.is_dir() and depth < 4 and not entry.name.startswith("."):
            _scan_excel_files(entry, depth + 1, result)
    return result
