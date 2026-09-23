#!/usr/bin/env python3
"""Themy PyQt6 desktop frontend.

The GUI is intentionally a frontend: Matugen/themy CLI remain the single source
of truth for palette generation and applying GTK 3/4, Qt 5/6 and Yazi themes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import re
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget, QInputDialog, QCheckBox, QStackedWidget,
    QDialog,
)


INTERNALS_DIR = Path(__file__).resolve().parents[1] / "internals"
if str(INTERNALS_DIR) not in sys.path:
    sys.path.insert(0, str(INTERNALS_DIR))
def read_template_metadata(path: Path) -> dict:
    meta = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            meta[key.strip()] = value.strip().strip("\"'")
    except OSError:
        pass
    return meta
from color_utils import hex_color


def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    path = Path(value).expanduser() if value else Path(default)
    if not path.is_absolute():
        # The CLI rejects relative XDG roots. Fail consistently instead of
        # letting the GUI write to a cwd-relative and different location.
        raise ValueError(f"{name} must be an absolute path: {path}")
    return path


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

def clean_process_text(value: str) -> str:
    return _ANSI_RE.sub("", value or "").strip()


def write_palette_matugen_config() -> Path:
    THEMY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".matugen-config-", suffix=".toml", dir=THEMY_CONFIG_DIR)
    path = Path(name)
    os.close(fd)
    source = Path(__file__).resolve().parents[1] / "internals" / "matugen-config.toml"
    try:
        shutil.copyfile(source, path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path

XDG_CONFIG_HOME = env_path("XDG_CONFIG_HOME", Path.home() / ".config")
XDG_DATA_HOME = env_path("XDG_DATA_HOME", Path.home() / ".local" / "share")
XDG_STATE_HOME = env_path("XDG_STATE_HOME", Path.home() / ".local" / "state")
THEMY_CONFIG_DIR = XDG_CONFIG_HOME / "themy"
TEMPLATES_DIR = THEMY_CONFIG_DIR / "templates"
CACHE_DIR = THEMY_CONFIG_DIR / "cache" / "palettes"
GUI_STATE = THEMY_CONFIG_DIR / "gui.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif"}
DEFAULTS = {
    "surface": "#141414", "surface_low": "#1c1c1c", "surface_high": "#252525",
    "hover": "#303030", "text": "#f3f3f3", "muted": "#a8a8a8",
    "outline": "#3b3b3b", "primary": "#8ad6b7", "on_primary": "#102019",
}


def mix(a: str, b: str, amount: float) -> str:
    aa, bb = QColor(a), QColor(b)
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(aa.red()*(1-amount)+bb.red()*amount),
        round(aa.green()*(1-amount)+bb.green()*amount),
        round(aa.blue()*(1-amount)+bb.blue()*amount),
    ).name()


class WorkerSignals(QObject):
    finished = pyqtSignal(bool, object)


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            self.signals.finished.emit(True, self.fn())
        except Exception as exc:
            self.signals.finished.emit(False, exc)


class PreviewFailure(RuntimeError):
    def __init__(self, generation: int, wallpaper: str, mode: str, cause: Exception):
        super().__init__(str(cause))
        self.generation = generation
        self.wallpaper = wallpaper
        self.mode = mode


class PaletteChip(QFrame):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("paletteChip")
        lay = QHBoxLayout(self); lay.setContentsMargins(9, 6, 9, 6); lay.setSpacing(7)
        sw = QLabel(); sw.setFixedSize(26, 26); sw.setStyleSheet(f"background:{color}; border-radius:8px;")
        txt = QVBoxLayout(); txt.setSpacing(0)
        l1 = QLabel(label); l1.setObjectName("muted")
        l2 = QLabel(color.upper()); l2.setObjectName("hex")
        txt.addWidget(l1); txt.addWidget(l2); lay.addWidget(sw); lay.addLayout(txt)


class SchemeCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, item: dict, selected: bool, parent=None):
        super().__init__(parent)
        self.sid = item["id"]
        self.setProperty("selected", selected)
        self.setObjectName("schemeCard")
        lay = QVBoxLayout(self); lay.setContentsMargins(12, 9, 12, 9); lay.setSpacing(6)
        top = QHBoxLayout()
        title = QLabel(item.get("name", self.sid)); title.setObjectName("cardTitle")
        self.tag = QLabel("Selected" if selected else "Preview")
        self.tag.setObjectName("selectedTag" if selected else "muted")
        top.addWidget(title); top.addStretch(); top.addWidget(self.tag); lay.addLayout(top)
        chips = QHBoxLayout(); chips.setSpacing(8)
        for key, label in (("primary", "Primary"), ("secondary", "Secondary"), ("tertiary", "Tertiary")):
            chips.addWidget(PaletteChip(label, hex_color(item.get(key), "#555555")))
        lay.addLayout(chips)
        self.setFixedHeight(102)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, selected: bool):
        self.setProperty("selected", selected)
        self.tag.setText("Selected" if selected else "Preview")
        self.tag.setObjectName("selectedTag" if selected else "muted")
        self.style().unpolish(self); self.style().polish(self); self.tag.style().unpolish(self.tag); self.tag.style().polish(self.tag)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.sid)
        super().mousePressEvent(event)

class ProgramCatalogDialog(QDialog):
    """Browser dialog to fetch and install new template collection from a Git repository."""

    def __init__(self, parent=None, colors=None):
        super().__init__(parent)
        self.setWindowTitle("Add Programs")
        self.setMinimumSize(640, 520)
        self.repo_file = THEMY_CONFIG_DIR / "repo_url.txt"
        self.colors = colors or DEFAULTS
        self.setStyleSheet(self.stylesheet())
        self.catalog_templates = []
        self.init_ui()
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self.fetch_repo)

    def stylesheet(self):
        c = self.colors
        return f"""
        QDialog {{ background:{c['surface']}; color:{c['text']}; }}
        QLabel {{ color:{c['text']}; background:transparent; }}
        QLabel#muted {{ color:{c['muted']}; }}
        QLabel#cardTitle {{ font-size:13px; font-weight:700; }}
        QLabel#selectedTag {{ color:{c['primary']}; font-weight:700; }}
        QLineEdit {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:9px; padding:9px 12px; }}
        QPushButton {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:9px; padding:8px 16px; }}
        QPushButton:hover {{ background:{c['hover']}; }}
        QPushButton:disabled {{ color:{c['muted']}; }}
        QScrollArea {{ background:{c['surface']}; border:none; }}
        QScrollArea > QWidget > QWidget {{ background:transparent; }}
        QFrame#programRow {{ background:{c['surface_high']}; border:1px solid {c['outline']}; border-radius:12px; }}
        QScrollBar:vertical {{ background:transparent; width:10px; }}
        QScrollBar::handle:vertical {{ background:{c['outline']}; border-radius:5px; min-height:24px; }}
        """

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        lbl = QLabel("Repository URL:")
        top_bar.addWidget(lbl)

        default_url = "https://github.com/Impairon/themy_templates"
        if self.repo_file.is_file():
            saved = self.repo_file.read_text(encoding="utf-8").strip()
            if saved:
                default_url = saved

        self.repo_input = QLineEdit(default_url)
        top_bar.addWidget(self.repo_input, 1)

        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.clicked.connect(self.fetch_repo)
        top_bar.addWidget(self.fetch_btn)
        layout.addLayout(top_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        self.status_lbl = QLabel("Fetching templates…")
        self.status_lbl.setObjectName("muted")
        footer.addWidget(self.status_lbl, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    def get_ignore_list(self) -> set:
        """Default ignored folders plus any names listed in ~/.config/themy/ignore_templates.txt"""
        ignore = {".git", ".github", "docs", ".cache", "__pycache__"}
        ignore_file = THEMY_CONFIG_DIR / "ignore_templates.txt"
        if ignore_file.is_file():
            try:
                for line in ignore_file.read_text(encoding="utf-8").splitlines():
                    line = line.split("#")[0].strip()
                    if line:
                        ignore.add(line)
            except Exception:
                pass
        return ignore

    @staticmethod
    def parse_github_owner_repo(url):
        url = url.strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        match = re.search(r"github\.com[/:]([^/]+)/([^/]+)", url)
        if match:
            return match.group(1), match.group(2)
        return None, None

    def fetch_repo(self):
        url = self.repo_input.text().strip()
        if not url:
            self.status_lbl.setText("Repository URL cannot be empty.")
            return

        self.repo_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_file.write_text(url, encoding="utf-8")

        self.fetch_btn.setEnabled(False)
        self.status_lbl.setText("Fetching repository templates...")
        QApplication.processEvents()

        owner, repo = self.parse_github_owner_repo(url)
        if owner and repo:
            self.fetch_github_api(owner, repo)
        else:
            self.fetch_git_clone_fallback(url)

        self.fetch_btn.setEnabled(True)

    def fetch_github_api(self, owner, repo):
        import urllib.request

        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        req = urllib.request.Request(api_url, headers={"User-Agent": "Themy-App"})

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                contents = json.loads(resp.read().decode("utf-8"))

            ignored = self.get_ignore_list()
            dirs = [
                item
                for item in contents
                if item.get("type") == "dir"
                and item["name"] not in ignored
                and not item["name"].startswith(".")
            ]

            self.catalog_templates = []
            for entry in dirs:
                d = entry["name"]
                meta = self.fetch_remote_conf(owner, repo, d)
                self.catalog_templates.append({
                    "id": d,
                    "name": meta.get("name", d.replace("_", " ").replace("-", " ").title()),
                    "description": meta.get("description", "Themy template"),
                    "version": meta.get("version", ""),
                    "owner": owner,
                    "repo": repo,
                    "source_sha": entry.get("sha", ""),
                    "is_remote_archive": True,
                })

            self.populate_items()
            new_count = sum(1 for m in self.catalog_templates if not (TEMPLATES_DIR / m["id"]).exists())
            update_count = sum(1 for m in self.catalog_templates if self.template_needs_update(m))
            self.status_lbl.setText(f"Found {len(self.catalog_templates)} templates; {new_count} new, {update_count} update{'s' if update_count != 1 else ''}.")
        except Exception as exc:
            self.status_lbl.setText(f"GitHub API error: {exc}")

    def fetch_remote_conf(self, owner, repo, directory):
        import urllib.request

        conf_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{directory}/template.conf"
        req = urllib.request.Request(conf_url, headers={"User-Agent": "Themy-App"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                lines = resp.read().decode("utf-8").splitlines()
                meta = {}
                for line in lines:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        meta[k.strip()] = v.strip().strip("'").strip('"')
                return meta
        except Exception:
            return {}

    def fetch_git_clone_fallback(self, url):
        cache_dir = THEMY_CONFIG_DIR / "cache" / "repo_catalog"
        try:
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                ["git", "clone", "--depth", "1", url, str(cache_dir)],
                capture_output=True, text=True, timeout=120,
            )
            if res.returncode != 0:
                err = (res.stderr or res.stdout).strip().splitlines()
                self.status_lbl.setText(f"Error: {err[-1] if err else 'Git clone failed'}")
                return

            ignored = self.get_ignore_list()
            self.catalog_templates = []
            for entry in sorted(cache_dir.iterdir(), key=lambda p: p.name.lower()):
                if not entry.is_dir() or entry.name in ignored or entry.name.startswith("."):
                    continue
                conf = entry / "template.conf"
                meta = read_template_metadata(conf) if conf.is_file() else {}
                self.catalog_templates.append({
                    "id": entry.name,
                    "name": meta.get("name", entry.name.replace("_", " ").replace("-", " ").title()),
                    "description": meta.get("description", "Themy template"),
                    "version": meta.get("version", ""),
                    "path": entry,
                    "source_sha": "",
                    "is_remote_archive": False,
                })
            self.populate_items()
            new_count = sum(1 for m in self.catalog_templates if not (TEMPLATES_DIR / m["id"]).exists())
            self.status_lbl.setText(f"Found {len(self.catalog_templates)} templates; {new_count} new.")
        except Exception as exc:
            self.status_lbl.setText(f"Error: {exc}")

    def installed_source(self, template_id):
        path = TEMPLATES_DIR / template_id / ".themy-source.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def template_needs_update(self, item):
        target = TEMPLATES_DIR / str(item.get("id", ""))
        if not target.is_dir():
            return False
        remote_sha = str(item.get("source_sha", ""))
        if not remote_sha:
            return False
        local = self.installed_source(item["id"])
        return bool(local.get("sha") and local.get("sha") != remote_sha)

    def installed_template(self, template_id):
        return (TEMPLATES_DIR / template_id).is_dir()

    def populate_items(self):
        while self.cards_layout.count() > 1:
            child = self.cards_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.catalog_templates:
            lbl = QLabel("No templates found in this repository.")
            lbl.setObjectName("muted")
            self.cards_layout.insertWidget(0, lbl)
            return

        for item in self.catalog_templates:
            card = QFrame()
            card.setObjectName("programRow")
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(12, 10, 12, 10)

            info = QVBoxLayout()
            title = QLabel(item["name"])
            title.setObjectName("cardTitle")
            sub = item["description"]
            if item["version"]:
                sub += f" - v{item['version']}"
            subtitle = QLabel(sub)
            subtitle.setObjectName("muted")
            info.addWidget(title)
            info.addWidget(subtitle)
            c_lay.addLayout(info, 1)

            installed = self.installed_template(item["id"])
            updating = installed and self.template_needs_update(item)
            btn = QPushButton("Update" if updating else ("Installed" if installed else "Download"))
            btn.setEnabled(not installed or updating)
            btn.clicked.connect(lambda _, it=item, c=card, b=btn: self.install_item(it, c, b))
            c_lay.addWidget(btn)

            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def closeEvent(self, event):
        parent = self.parent()
        if parent is not None and hasattr(parent, "load_templates"):
            parent.load_templates()
        super().closeEvent(event)

    def install_item(self, item, card_widget, btn):
        template_id = str(item.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", template_id):
            self.status_lbl.setText("Install refused: invalid template name.")
            return
        target = TEMPLATES_DIR / template_id
        if target.is_symlink():
            self.status_lbl.setText("Install refused: template path is a symbolic link.")
            return
        try:
            btn.setEnabled(False)
            self.status_lbl.setText(f"Downloading {item['name']}...")
            QApplication.processEvents()

            TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

            if item.get("is_remote_archive"):
                import urllib.request
                import tarfile
                import io

                tar_url = f"https://api.github.com/repos/{item['owner']}/{item['repo']}/tarball/HEAD"
                req = urllib.request.Request(tar_url, headers={"User-Agent": "Themy-App"})

                # Extract into a private staging directory first. GitHub archives
                # have a synthetic root such as `Impairon-themy_templates-<sha>/`;
                # the template directory itself is therefore the second path part.
                # The directory entry for that template is valid and must not be
                # mistaken for an empty/unsafe relative path.
                staging = Path(tempfile.mkdtemp(prefix=f".download-{template_id}-", dir=TEMPLATES_DIR))
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz") as tar:
                            found_template = False
                            for member in tar.getmembers():
                                name = member.name.replace("\\", "/")
                                parts = Path(name).parts
                                if not parts or Path(name).is_absolute() or ".." in parts:
                                    raise RuntimeError(f"unsafe archive path: {member.name}")
                                if len(parts) < 2 or parts[1] != template_id:
                                    continue

                                # The archive's own template directory is expected.
                                if len(parts) == 2:
                                    if not member.isdir():
                                        raise RuntimeError(f"unsafe template archive member: {member.name}")
                                    found_template = True
                                    continue

                                if member.issym() or member.islnk() or member.isdev():
                                    raise RuntimeError(f"unsafe archive member: {member.name}")

                                rel_path = Path(*parts[2:])
                                if rel_path.is_absolute() or not rel_path.parts or ".." in rel_path.parts:
                                    raise RuntimeError(f"unsafe archive path: {member.name}")

                                dest = (staging / rel_path).resolve()
                                if staging.resolve() not in dest.parents and dest != staging.resolve():
                                    raise RuntimeError(f"archive escapes template directory: {member.name}")

                                if member.isdir():
                                    dest.mkdir(parents=True, exist_ok=True)
                                elif member.isfile():
                                    if member.size > 8 * 1024 * 1024:
                                        raise RuntimeError(f"archive member is too large: {member.name}")
                                    dest.parent.mkdir(parents=True, exist_ok=True)
                                    extracted = tar.extractfile(member)
                                    if extracted is None:
                                        raise RuntimeError(f"could not read archive member: {member.name}")
                                    data = extracted.read()
                                    if len(data) != member.size:
                                        raise RuntimeError(f"short archive read: {member.name}")
                                    dest.write_bytes(data)
                                    if member.mode & 0o111:
                                        dest.chmod(dest.stat().st_mode | 0o755)

                            if not found_template:
                                raise RuntimeError(f"template directory not found in archive: {template_id}")

                    # Only replace the installed template after the complete archive
                    # has been validated and extracted successfully.
                    if target.exists():
                        shutil.rmtree(target)
                    staging.rename(target)
                    staging = None
                finally:
                    if staging is not None:
                        shutil.rmtree(staging, ignore_errors=True)
            else:
                staging = Path(tempfile.mkdtemp(prefix=f".download-{template_id}-", dir=TEMPLATES_DIR))
                try:
                    shutil.copytree(item["path"], staging, dirs_exist_ok=True)
                    if target.exists():
                        shutil.rmtree(target)
                    staging.rename(target)
                    staging = None
                finally:
                    if staging is not None:
                        shutil.rmtree(staging, ignore_errors=True)

            for hook in ("render", "apply", "doctor", "backup", "restore"):
                hook_file = target / hook
                if hook_file.is_file():
                    hook_file.chmod(hook_file.stat().st_mode | 0o755)

            # Every downloaded directory is a template. Metadata is optional in the
            # repository, so create a local template.conf when the repository does not
            # provide one. This keeps the on-disk template contract self-describing.
            try:
                conf = target / "template.conf"
                if not conf.is_file():
                    conf.write_text(
                        "# Generated by Themy\n"
                        f"id={template_id}\n"
                        f"name={item.get('name', template_id)}\n"
                        f"version={item.get('version', '')}\n"
                        f"description={item.get('description', 'Themy template')}\n",
                        encoding="utf-8",
                    )
            except Exception:
                pass

            # Record where this template came from so future fetches can detect updates.
            try:
                source = {
                    "repository": f"https://github.com/{item.get('owner', '')}/{item.get('repo', '')}" if item.get("owner") else str(self.repo_input.text().strip()),
                    "id": template_id,
                    "sha": str(item.get("source_sha", "")),
                    "version": str(item.get("version", "")),
                }
                (target / ".themy-source.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass

            # Auto-enable newly installed template in templates.json
            try:
                state_file = THEMY_CONFIG_DIR / "templates.json"
                states = {}
                if state_file.is_file():
                    states = json.loads(state_file.read_text(encoding="utf-8"))
                states[template_id] = True
                tmp_state = state_file.with_suffix(".json.tmp")
                tmp_state.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
                tmp_state.chmod(0o600)
                tmp_state.replace(state_file)
            except Exception:
                pass

            self.status_lbl.setText(f"Installed {item['name']} successfully.")
            self.populate_items()
            if self.parent() is not None and hasattr(self.parent(), "load_templates"):
                self.parent().load_templates()
        except Exception as exc:
            btn.setEnabled(True)
            self.status_lbl.setText(f"Install failed: {exc}")


class ThemyWindow(QMainWindow):
    def __init__(self, cli: str):
        super().__init__()
        self.cli = Path(cli).expanduser().resolve()
        self.pool = QThreadPool.globalInstance()
        self.folder: Path | None = None
        self.wallpaper: Path | None = None
        self.images: list[Path] = []
        self.filtered: list[Path] = []
        self.favorites: set[str] = set()
        self.recent: list[str] = []
        self.schemes: list[dict] = []
        self.selected_scheme: str | None = None
        self.scheme_choices: dict[str, str] = {}
        self.scheme_cards: dict[str, SchemeCard] = {}
        self._transition = None
        self._has_palette = False
        self._preview_generation = 0
        self.mode = "dark"
        self.busy = False
        self._thumb_cache: dict[str, QIcon] = {}
        THEMY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        self.load_state()
        self.setWindowTitle("Themy 3.3.8")
        self.resize(1400, 900); self.setMinimumSize(1050, 700)
        self.build_ui(); self.apply_palette(DEFAULTS, animate=False)
        self.scan_folder()

    def closeEvent(self, event):
        # Keep the on-disk template inventory/state current when the GUI closes.
        try:
            self.load_templates()
            self.save_state()
        finally:
            super().closeEvent(event)

    # ---------- state ----------
    def load_state(self):
        try:
            data = json.loads(GUI_STATE.read_text(encoding="utf-8"))
            f = data.get("folder"); self.folder = Path(f).expanduser() if f else None
            w = data.get("wallpaper"); self.wallpaper = Path(w).expanduser() if w else None
            self.mode = data.get("mode", "dark") if data.get("mode") in ("dark", "light") else "dark"
            self.favorites = set(data.get("favorites", []))
            self.recent = list(data.get("recent", []))[:20]
            self.scheme_choices = dict(data.get("scheme_choices", {}))
        except Exception:
            pass

    def save_state(self):
        try:
            THEMY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({
                "folder": str(self.folder) if self.folder else "",
                "wallpaper": str(self.wallpaper) if self.wallpaper else "",
                "mode": self.mode, "favorites": sorted(self.favorites), "recent": self.recent[:20],
                "scheme_choices": dict(list(self.scheme_choices.items())[-100:]),
            }, indent=2)
            tmp = GUI_STATE.with_name(f".{GUI_STATE.name}.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(GUI_STATE)
            try:
                GUI_STATE.chmod(0o600)
            except OSError:
                pass
        except OSError:
            pass

    def backup_available(self):
        return (XDG_STATE_HOME / "themy" / "backup").is_dir()

    def restore_backup(self):
        if self.busy or not self.backup_available():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restore previous theme")
        box.setText("Restore the previous GTK, Qt and Yazi configuration?")
        box.setInformativeText("The current configuration will be replaced by the one saved before the last successful apply.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.setStyleSheet(self.dialog_stylesheet())
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.busy = True; self.apply_btn.setEnabled(False); self.restore_btn.setEnabled(False); self.status.setText("Restoring previous configuration…")
        w = Worker(lambda: self.run_cli(["restore-backup"]))
        w.signals.finished.connect(self.restore_done)
        self.pool.start(w)

    # ----------------- delete logic ----------------------
    def delete_template(self, item: dict):
        if self.busy:
            return
        template_id = item["id"]
        template_name = item["name"]
        target = Path(item["path"])

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete template")
        box.setText(f"Delete '{template_name}' template?")
        box.setInformativeText(f"This will remove the template folder from:\n{target}\n\nAre you sure?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setStyleSheet(self.dialog_stylesheet())

        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        try:
            if target.exists():
                shutil.rmtree(target)

            # Clean from templates.json if tracked
            state_file = THEMY_CONFIG_DIR / "templates.json"
            if state_file.is_file():
                try:
                    states = json.loads(state_file.read_text(encoding="utf-8"))
                    if template_id in states:
                        del states[template_id]
                        state_file.write_text(json.dumps(states, indent=2), encoding="utf-8")
                except Exception:
                    pass

            self.status.setText(f"Deleted template '{template_name}'.")
            self.load_templates()
        except Exception as exc:
            self.show_message(QMessageBox.Icon.Critical, "Delete failed", f"Could not delete template:\n{exc}")

    def restore_done(self, ok, result):
        self.busy = False
        if not ok:
            self.status.setText("Restore failed.")
            self.show_message(QMessageBox.Icon.Critical, "Themy", str(result))
        elif result.returncode == 0:
            self.status.setText("Previous GTK, Qt and Yazi configuration restored.")
            self.show_message(QMessageBox.Icon.Information, "Themy", "Previous GTK, Qt and Yazi configuration restored successfully.")
        else:
            self.status.setText("Restore failed.")
            self.show_message(QMessageBox.Icon.Critical, "Themy", (result.stderr or result.stdout or "Themy failed.")[-4000:])
        self.restore_btn.setEnabled(self.backup_available())
        self.apply_btn.setEnabled(bool(self.selected_scheme))

    # ---------- UI ----------
    def build_ui(self):
        root = QWidget(); root.setObjectName("root"); self._root = root; self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(26, 22, 26, 18); outer.setSpacing(14)

        header = QHBoxLayout(); header.setSpacing(12)
        titlebox = QVBoxLayout(); titlebox.setSpacing(1)
        self.title = QLabel("Themy"); self.title.setObjectName("title")
        self.subtitle = QLabel("Wallpaper-driven desktop themes")
        self.subtitle.setObjectName("subtitle")
        titlebox.addWidget(self.title); titlebox.addWidget(self.subtitle); header.addLayout(titlebox); header.addStretch()
        self.mode_box = QComboBox(); self.mode_box.addItems(["Dark", "Light"]); self.mode_box.setCurrentText("Dark" if self.mode == "dark" else "Light")
        self.mode_box.currentTextChanged.connect(self.mode_changed); header.addWidget(QLabel("Mode")); header.addWidget(self.mode_box)
        outer.addLayout(header)

        nav = QHBoxLayout(); nav.setSpacing(6)
        self.themes_nav = QPushButton("Themes"); self.themes_nav.setCheckable(True); self.themes_nav.clicked.connect(lambda: self.switch_page(0))
        self.programs_nav = QPushButton("Programs"); self.programs_nav.setCheckable(True); self.programs_nav.clicked.connect(lambda: self.switch_page(1))
        nav.addWidget(self.themes_nav); nav.addWidget(self.programs_nav); nav.addStretch(); outer.addLayout(nav)

        self.pages = QStackedWidget(); outer.addWidget(self.pages, 1)
        self.pages.addWidget(self.build_themes_page())
        self.pages.addWidget(self.build_programs_page())
        self.switch_page(0)
        self.load_templates()

    def build_themes_page(self):
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(0,0,0,0); outer.setSpacing(12)
        toolbar = QHBoxLayout(); toolbar.setSpacing(8)
        self.folder_btn = QPushButton("Choose wallpaper folder"); self.folder_btn.clicked.connect(self.choose_folder)
        self.refresh_btn = QPushButton("↻ Refresh"); self.refresh_btn.clicked.connect(self.scan_folder)
        self.folder_label = QLabel(); self.folder_label.setObjectName("muted"); self.folder_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search wallpapers…"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.filter_images); self.search.setMaximumWidth(300)
        toolbar.addWidget(self.folder_btn); toolbar.addWidget(self.refresh_btn); toolbar.addWidget(self.folder_label); toolbar.addWidget(self.search); outer.addLayout(toolbar)

        split = QSplitter(Qt.Orientation.Horizontal); split.setChildrenCollapsible(False)
        lib = QWidget(); ll = QVBoxLayout(lib); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        lh = QHBoxLayout(); lab = QLabel("Wallpaper library"); lab.setObjectName("sectionTitle"); self.count = QLabel(); self.count.setObjectName("muted"); lh.addWidget(lab); lh.addStretch(); lh.addWidget(self.count); ll.addLayout(lh)
        views = QHBoxLayout(); self.view_buttons = {}
        for key, text in (("all", "All"), ("favorites", "★ Favorites"), ("recent", "◷ Recent")):
            b = QPushButton(text); b.setCheckable(True); b.clicked.connect(lambda checked, k=key: self.set_view(k)); views.addWidget(b); self.view_buttons[key]=b
        views.addStretch(); ll.addLayout(views)
        self.view = "all"; self.wall_list = QListWidget(); self.wall_list.setViewMode(QListWidget.ViewMode.IconMode); self.wall_list.setResizeMode(QListWidget.ResizeMode.Adjust); self.wall_list.setIconSize(QSize(190, 115)); self.wall_list.setGridSize(QSize(220, 155)); self.wall_list.setSpacing(8); self.wall_list.itemClicked.connect(self.wall_clicked); ll.addWidget(self.wall_list)
        split.addWidget(lib)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(12)
        self.preview = QLabel("Select a wallpaper"); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(280); self.preview.setObjectName("preview"); self.preview.setScaledContents(False); rl.addWidget(self.preview)
        meta = QHBoxLayout(); self.wall_name = QLabel("No wallpaper selected"); self.wall_name.setObjectName("sectionTitle"); meta.addWidget(self.wall_name); meta.addStretch()
        self.favorite = QPushButton("☆ Favorite"); self.favorite.clicked.connect(self.toggle_favorite); self.pick_file = QPushButton("Pick file"); self.pick_file.clicked.connect(self.browse_file); meta.addWidget(self.favorite); meta.addWidget(self.pick_file); rl.addLayout(meta)
        sh = QHBoxLayout(); st = QLabel("Color schemes"); st.setObjectName("sectionTitle"); hint = QLabel("Select a scheme to preview it"); hint.setObjectName("muted"); sh.addWidget(st); sh.addStretch(); sh.addWidget(hint); rl.addLayout(sh)
        self.scheme_area = QScrollArea(); self.scheme_area.setObjectName("schemeScroll"); self.scheme_area.setWidgetResizable(True); self.scheme_container = QWidget(); self.scheme_container.setObjectName("schemeContainer"); self.scheme_layout = QVBoxLayout(self.scheme_container); self.scheme_layout.setContentsMargins(2,2,8,2); self.scheme_layout.setSpacing(5); self.scheme_layout.addStretch(); self.scheme_area.setWidget(self.scheme_container); rl.addWidget(self.scheme_area, 1)
        split.addWidget(right); split.setSizes([500, 800]); outer.addWidget(split, 1)

        bottom = QHBoxLayout(); self.status = QLabel("Choose a wallpaper to get started."); self.status.setObjectName("statusPill"); bottom.addWidget(self.status); bottom.addStretch()
        self.restore_btn = QPushButton("Restore previous"); self.restore_btn.setObjectName("restore"); self.restore_btn.setToolTip("Restore the configuration saved before the last successful apply."); self.restore_btn.setEnabled(self.backup_available()); self.restore_btn.clicked.connect(self.restore_backup); bottom.addWidget(self.restore_btn)
        self.apply_btn = QPushButton("Apply theme"); self.apply_btn.setObjectName("apply"); self.apply_btn.setEnabled(False); self.apply_btn.clicked.connect(self.apply_theme); bottom.addWidget(self.apply_btn); outer.addLayout(bottom)
        self.update_view_buttons()
        return page

    def build_programs_page(self):
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(0,0,0,0); outer.setSpacing(12)
        head = QHBoxLayout()
        title = QLabel("Programs"); title.setObjectName("sectionTitle")
        hint = QLabel(f"Templates: {TEMPLATES_DIR}"); hint.setObjectName("muted")
        head.addWidget(title); head.addWidget(hint); head.addStretch()
        self.add_template_btn = QPushButton("＋ Add program"); self.add_template_btn.setToolTip("Fetch a Themy template repository into the templates directory."); self.add_template_btn.clicked.connect(self.add_template); head.addWidget(self.add_template_btn)
        outer.addLayout(head)
        self.program_area = QScrollArea(); self.program_area.setWidgetResizable(True); self.program_area.setObjectName("programScroll")
        self.program_container = QWidget(); self.program_container.setObjectName("programContainer")
        self.program_layout = QVBoxLayout(self.program_container); self.program_layout.setContentsMargins(2,2,8,2); self.program_layout.setSpacing(8); self.program_layout.addStretch()
        self.program_area.setWidget(self.program_container); outer.addWidget(self.program_area, 1)
        return page

    def switch_page(self, index):
        self.pages.setCurrentIndex(index)
        self.themes_nav.setChecked(index == 0); self.programs_nav.setChecked(index == 1)
        if index == 1: self.load_templates()

    def load_templates(self):
        if not hasattr(self, "program_layout"):
            return
        try:
            TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
            templates = []
            for d in sorted(TEMPLATES_DIR.iterdir(), key=lambda p: p.name.lower()):
                if not d.is_dir():
                    continue
                conf = d / "template.conf"
                meta = read_template_metadata(conf) if conf.is_file() else {}
                templates.append({
                    "id": meta.get("id", d.name),
                    "name": meta.get("name", d.name),
                    "version": meta.get("version", ""),
                    "description": meta.get("description", ""),
                    "path": str(d),
                    "valid": os.access(d / "render", os.X_OK) and os.access(d / "apply", os.X_OK),
                    "enabled": True,
                })

            # Themy's canonical module state is templates.json.
            state_file = THEMY_CONFIG_DIR / "templates.json"
            try:
                states = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                states = {}
            for item in templates:
                item["enabled"] = bool(states.get(Path(item["path"]).name, True))

            self._template_items = templates
            self.templates_loaded(True, templates)
        except Exception as exc:
            self.templates_loaded(False, exc)

    def templates_loaded(self, ok, payload):
        while self.program_layout.count() > 1:
            item = self.program_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not ok:
            label = QLabel(f"Could not load templates: {payload}")
            label.setObjectName("muted")
            self.program_layout.insertWidget(0, label)
            return

        templates = payload
        if not templates:
            label = QLabel("No templates installed yet. Add a Git repository to extend Themy.")
            label.setObjectName("muted")
            self.program_layout.insertWidget(0, label)
            return

        for item in templates:
            row = QFrame()
            row.setObjectName("programRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(14, 11, 14, 11)
            text = QVBoxLayout()
            title = QLabel(item["name"])
            title.setObjectName("cardTitle")
            detail = item["description"] or f"Template {item['id']}"
            if item["version"]:
                detail += f" · v{item['version']}"
            subtitle = QLabel(detail)
            subtitle.setObjectName("muted")
            text.addWidget(title)
            text.addWidget(subtitle)
            layout.addLayout(text, 1)

            health = QLabel("Ready" if item["valid"] else "Incomplete")
            health.setObjectName("selectedTag" if item["valid"] else "muted")
            layout.addWidget(health)

            check = QCheckBox("Enabled")
            check.setProperty("programId", Path(item["path"]).name)
            check.setChecked(item["enabled"] and item["valid"])
            check.setEnabled(item["valid"] and not self.busy)
            check.toggled.connect(self.template_toggled)
            layout.addWidget(check)

            # Trash / Delete button
            del_btn = QPushButton("🗑")
            del_btn.setObjectName("deleteProgramBtn")
            del_btn.setToolTip(f"Delete template {item['name']}")
            del_btn.setEnabled(not self.busy)
            del_btn.clicked.connect(lambda _, tpl=item: self.delete_template(tpl))
            layout.addWidget(del_btn)

            self.program_layout.insertWidget(self.program_layout.count() - 1, row)


    def template_toggled(self, enabled):
        check = self.sender()
        name = check.property("programId") if check else None
        if not name or self.busy:
            return
        try:
            state_file = THEMY_CONFIG_DIR / "templates.json"
            THEMY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            try:
                states = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                states = {}
            states[str(name)] = bool(enabled)
            tmp = state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
            tmp.replace(state_file)
            self.status.setText(f"{name}: control {'enabled' if enabled else 'disabled'}")
        except OSError as exc:
            self.show_message(QMessageBox.Icon.Critical, "Program control failed", str(exc))
            self.load_templates()

    def add_template(self):
        if self.busy:
            return

        # The catalog dialog fetches GitHub repositories through the API, so
        # opening it must not depend on git being installed. Non-GitHub URLs
        # are handled by the dialog's clone fallback and report their own error.
        dialog = ProgramCatalogDialog(self, getattr(self, "colors", DEFAULTS))
        dialog.exec()

        # Reload the Programs tab so newly downloaded templates appear immediately
        self.load_templates()



    def stylesheet(self, c):
        return f"""
        QWidget#root {{ background:{c['surface']}; color:{c['text']}; }}
        QLabel {{ color:{c['text']}; }} QLabel#muted, QLabel#muted {{ color:{c['muted']}; }}
        QLabel#title {{ font-size:30px; font-weight:800; }} QLabel#sectionTitle {{ font-size:15px; font-weight:600; }}
        QPushButton, QComboBox, QLineEdit {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:9px; padding:8px 12px; }}
        QPushButton:hover, QComboBox:hover {{ background:{c['hover']}; }} QPushButton:checked {{ background:{c['primary']}; color:{c['on_primary']}; border-color:{c['primary']}; }}
        QPushButton#restore {{ background:{c['surface_high']}; color:{c['text']}; }} QPushButton#restore:hover {{ background:{c['hover']}; }}
        QPushButton#apply {{ background:{c['primary']}; color:{c['on_primary']}; font-weight:800; padding:11px 26px; border:none; }}
        QPushButton#apply:disabled {{ background:{c['surface_high']}; color:{c['muted']}; }}
        QLineEdit {{ padding:9px 12px; }} QComboBox QAbstractItemView {{ background:{c["surface_high"]}; color:{c["text"]}; border:1px solid {c["outline"]}; selection-background-color:{c["primary"]}; selection-color:{c["on_primary"]}; }}
        QListWidget, QScrollArea {{ background:{c["surface"]}; border:none; }} QScrollArea#schemeScroll {{ background:{c["surface"]}; }} QWidget#schemeContainer {{ background:{c["surface"]}; }} QListWidget::viewport {{ background:{c["surface"]}; }}
        QListWidget::item {{ border-radius:10px; padding:4px; }} QListWidget::item:selected {{ background:{mix(c['primary'],c['surface_high'],.20)}; }}
        QFrame#schemeCard {{ background:{c['surface_high']}; border:1px solid {c['outline']}; border-radius:12px; }}
        QFrame#schemeCard[selected="true"] {{ border:2px solid {c['primary']}; background:{mix(c['primary'],c['surface_high'],.10)}; }}
        QFrame#paletteChip {{ background:{c['surface_low']}; border:1px solid {c['outline']}; border-radius:9px; }}
        QFrame#programRow {{ background:{c['surface_high']}; border:1px solid {c['outline']}; border-radius:12px; }} QScrollArea#programScroll, QWidget#programContainer {{ background:{c['surface']}; border:none; }} QCheckBox {{ color:{c['text']}; spacing:8px; }} QCheckBox::indicator {{ width:20px; height:20px; }} QCheckBox::indicator:checked {{ background:{c['primary']}; border:1px solid {c['primary']}; border-radius:6px; }} QCheckBox::indicator:unchecked {{ background:{c['surface_low']}; border:1px solid {c['outline']}; border-radius:6px; }}
        QLabel#cardTitle {{ font-size:13px; font-weight:700; }} QLabel#hex {{ font-weight:700; }}
        QLabel#selectedTag {{ color:{c['primary']}; font-weight:700; }}
        QLabel#preview {{ background:{c['surface_low']}; border:1px solid {c['outline']}; border-radius:14px; }}
        QSplitter::handle {{ background:{c['outline']}; width:1px; }}
        QScrollArea#schemeScroll {{ padding:0px; }} QScrollBar:vertical {{ background:transparent; width:10px; }} QScrollBar::handle:vertical {{ background:{c['outline']}; border-radius:5px; }}
        QPushButton#deleteProgramBtn {{
            background: transparent;
            color: #888888;
            border: 1px solid transparent;
            border-radius: 8px;
            padding: 6px 10px;
            font-size: 14px;
        }}
        QPushButton#deleteProgramBtn:hover {{
            background: rgba(239, 68, 68, 0.18);
            color: #ef4444;
            border: 1px solid #ef4444;
        }}
        QLabel#subtitle {{ color:{c['muted']}; font-size:12px; }}
        QLabel#statusPill {{ background:{c['surface_high']}; color:{c['muted']}; border:1px solid {c['outline']}; border-radius:10px; padding:7px 11px; }}
        QPushButton {{ min-height:34px; }}
        QPushButton:hover {{ border-color:{mix(c['primary'],c['outline'],.35)}; }}
        QPushButton:pressed {{ padding-top:9px; padding-bottom:7px; }}
        QPushButton:disabled {{ background:{c['surface_low']}; color:{c['muted']}; border-color:{c['outline']}; }}
        QPushButton:checked {{ font-weight:700; }}
        QListWidget {{ outline:0; padding:5px; }}
        QListWidget::item {{ background:transparent; border:1px solid transparent; border-radius:12px; margin:2px; padding:5px; }}
        QListWidget::item:hover {{ background:{c['surface_high']}; border-color:{c['outline']}; }}
        QListWidget::item:selected {{ background:{mix(c['primary'],c['surface_high'],.20)}; border:1px solid {c['primary']}; }}
        QFrame#schemeCard:hover {{ border-color:{mix(c['primary'],c['outline'],.45)}; }}
        QFrame#programRow:hover {{ border-color:{mix(c['primary'],c['outline'],.35)}; }}
        QSplitter::handle:hover {{ background:{c['primary']}; }}
        QToolTip {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; padding:6px 8px; }}
        QComboBox::drop-down {{ border:0; width:26px; }}
        QScrollBar:vertical {{ background:transparent; width:9px; margin:3px; }}
        QScrollBar::handle:vertical {{ background:{c['outline']}; border-radius:4px; min-height:28px; }}
        QScrollBar::handle:vertical:hover {{ background:{c['primary']}; }}
        """

    def apply_palette(self, palette: dict, animate: bool = True):
        surface = hex_color(palette.get("surface"), DEFAULTS["surface"])
        primary = hex_color(palette.get("primary_container") or palette.get("primary"), DEFAULTS["primary"])
        onp = hex_color(palette.get("on_primary_container"), "#ffffff")
        c = {
            "surface": surface,
            "surface_low": hex_color(palette.get("surface_container_low"), mix(surface, primary, .05)),
            "surface_high": hex_color(palette.get("surface_container_high"), mix(surface, primary, .11)),
            "hover": mix(hex_color(palette.get("surface_container_high"), surface), primary, .15),
            "text": hex_color(palette.get("on_surface"), "#f3f3f3"),
            "muted": mix(hex_color(palette.get("on_surface"), "#f3f3f3"), surface, .48),
            "outline": hex_color(palette.get("outline"), "#454545"), "primary": primary, "on_primary": onp,
        }
        root = getattr(self, "_root", None)
        old = root.grab() if animate and root and not root.size().isEmpty() else None
        self.setStyleSheet(self.stylesheet(c)); self.colors = c
        if old is not None:
            overlay = QLabel(root)
            overlay.setPixmap(old)
            overlay.setGeometry(root.rect())
            overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            effect = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(effect)
            overlay.show(); overlay.raise_()
            anim = QPropertyAnimation(effect, b"opacity", overlay)
            anim.setDuration(180)
            anim.setStartValue(1.0); anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(overlay.deleteLater)
            self._transition = anim
            anim.start()

    # ---------- wallpapers ----------
    def wallpaper_key(self, p: Path | None = None) -> str | None:
        p = p or self.wallpaper
        if not p or not p.is_file(): return None
        digest = self.wallpaper_hash(p)
        return f"{digest}:{self.mode}" if digest else None

    def file_dialog_stylesheet(self):
        c = getattr(self, "colors", DEFAULTS)
        return f"""
        QFileDialog {{ background:{c['surface']}; color:{c['text']}; }}
        QFileDialog QLabel {{ color:{c['text']}; }}
        QFileDialog QLineEdit, QFileDialog QComboBox {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:8px; padding:7px 9px; }}
        QFileDialog QTreeView, QFileDialog QListView {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['outline']}; alternate-background-color:{c['surface_low']}; }}
        QFileDialog QTreeView::item, QFileDialog QListView::item {{ padding:5px; border-radius:6px; }}
        QFileDialog QTreeView::item:hover, QFileDialog QListView::item:hover {{ background:{c['hover']}; }}
        QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected {{ background:{c['primary']}; color:{c['on_primary']}; }}
        QFileDialog QPushButton, QFileDialog QToolButton {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:8px; padding:7px 13px; }}
        QFileDialog QPushButton:hover, QFileDialog QToolButton:hover {{ background:{c['hover']}; }}
        QFileDialog QPushButton:default {{ background:{c['primary']}; color:{c['on_primary']}; border-color:{c['primary']}; }}
        QFileDialog QScrollBar:vertical {{ background:transparent; width:10px; }}
        QFileDialog QScrollBar::handle:vertical {{ background:{c['outline']}; border-radius:5px; min-height:30px; }}
        """

    def open_file_dialog(self, directory=False):
        dlg = QFileDialog(self)
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dlg.setWindowTitle("Choose wallpaper folder" if directory else "Choose wallpaper")
        dlg.setDirectory(str(self.folder or Path.home()))
        dlg.setStyleSheet(self.file_dialog_stylesheet())
        if directory:
            dlg.setFileMode(QFileDialog.FileMode.Directory)
            dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
        else:
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
            dlg.setNameFilter("Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)")
        return dlg

    def choose_folder(self):
        dlg = self.open_file_dialog(directory=True)
        if dlg.exec():
            files = dlg.selectedFiles()
            if files:
                self.folder = Path(files[0]).resolve(); self.save_state(); self.scan_folder()

    def browse_file(self):
        dlg = self.open_file_dialog()
        if dlg.exec():
            files = dlg.selectedFiles()
            if files:
                p = Path(files[0]).resolve(); self.folder = p.parent; self.set_wallpaper(p); self.save_state(); self.scan_folder()

    def scan_folder(self):
        if not self.folder or not self.folder.is_dir():
            if self.wallpaper and self.wallpaper.is_file(): self.folder = self.wallpaper.parent
            else: self.folder_label.setText("No wallpaper folder selected"); self.wall_list.clear(); return
        self.folder_label.setText(str(self.folder));
        try: self.images = sorted([p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS], key=lambda p:p.name.lower())
        except OSError: self.images=[]
        self._thumb_cache.clear(); self.filter_images()
        if self.wallpaper and self.wallpaper.is_file():
            self.selected_scheme = self.scheme_choices.get(self.wallpaper_key(self.wallpaper))
            self.show_wallpaper(self.wallpaper, preview=False)
            self.preview_palettes()
        elif self.images: self.set_wallpaper(self.images[0])
        elif self.folder: self.status.setText("No supported images found in this folder.")

    def set_view(self, view): self.view=view; self.update_view_buttons(); self.filter_images()
    def update_view_buttons(self):
        for k,b in getattr(self,"view_buttons",{}).items(): b.setChecked(k==self.view)

    def filter_images(self):
        q=self.search.text().strip().lower()
        if self.view=="favorites": base=[p for p in self.images if str(p) in self.favorites]
        elif self.view=="recent": base=[Path(p) for p in self.recent if Path(p).is_file()]
        else: base=self.images
        self.filtered=[p for p in base if not q or q in p.name.lower()]
        self.wall_list.clear(); self.count.setText(f"{len(self.filtered)} wallpapers")
        for p in self.filtered:
            item=QListWidgetItem(self.thumbnail(p), p.name); item.setData(Qt.ItemDataRole.UserRole, str(p)); item.setToolTip(str(p)); self.wall_list.addItem(item)
        if self.wallpaper:
            for i in range(self.wall_list.count()):
                if self.wall_list.item(i).data(Qt.ItemDataRole.UserRole)==str(self.wallpaper): self.wall_list.setCurrentRow(i); break

    def thumbnail(self,p:Path):
        key=str(p)
        if key in self._thumb_cache: return self._thumb_cache[key]
        pix=QPixmap(str(p));
        if pix.isNull(): return QIcon()
        pix=pix.scaled(190,115,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation)
        icon=QIcon(pix); self._thumb_cache[key]=icon; return icon

    def wall_clicked(self,item): self.set_wallpaper(Path(item.data(Qt.ItemDataRole.UserRole)))

    def set_wallpaper(self,p:Path):
        p=p.expanduser().resolve()
        if not p.is_file(): return
        self.wallpaper=p; self.recent=[str(p)]+[x for x in self.recent if x!=str(p)]; self.recent=self.recent[:20]
        self.selected_scheme = self.scheme_choices.get(self.wallpaper_key(p))
        self.show_wallpaper(p); self.save_state(); self.filter_images(); self.preview_palettes()

    def show_wallpaper(self,p,preview=True):
        self.wall_name.setText(p.name); self.favorite.setText("★ Favorite" if str(p) in self.favorites else "☆ Favorite")
        pix=QPixmap(str(p));
        if pix.isNull(): self.preview.setText("Unable to preview this image"); return
        self.preview.setPixmap(pix.scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        if preview: self.status.setText(f"Selected {p.name}")

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.wallpaper: self.show_wallpaper(self.wallpaper,False)

    def toggle_favorite(self):
        if not self.wallpaper:return
        s=str(self.wallpaper)
        if s in self.favorites:self.favorites.remove(s)
        else:self.favorites.add(s)
        self.favorite.setText("★ Favorite" if s in self.favorites else "☆ Favorite"); self.save_state(); self.filter_images()

    # ---------- Palette cache / Matugen ----------
    def wallpaper_hash(self, p: Path | None = None) -> str | None:
        p = p or self.wallpaper
        if not p or not p.is_file():
            return None
        h = hashlib.sha256()
        try:
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def palette_cache_file(self, p: Path | None = None, mode: str | None = None) -> Path | None:
        digest = self.wallpaper_hash(p)
        if not digest:
            return None
        mode = mode or self.mode
        return CACHE_DIR / digest / f"{mode}.json"

    def load_palette_cache(self, p: Path | None = None, mode: str | None = None):
        path = self.palette_cache_file(p, mode)
        if not path or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != 2:
                return None
            if data.get("wallpaper_hash") != self.wallpaper_hash(p):
                return None
            if data.get("mode") != (mode or self.mode):
                return None
            if not isinstance(data.get("schemes"), list):
                return None
            return data
        except Exception:
            return None

    def save_palette_cache(self, p: Path, mode: str, schemes: list[dict]):
        path = self.palette_cache_file(p, mode)
        if not path:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "wallpaper_hash": self.wallpaper_hash(p),
            "wallpaper": str(p),
            "mode": mode,
            "schemes": schemes,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def generate_schemes(self, p: Path, mode: str):
        cached = self.load_palette_cache(p, mode)
        if cached:
            return cached["schemes"], True

        matugen_cfg = write_palette_matugen_config()
        try:
            schemes = []
            for sid in [
                "scheme-tonal-spot", "scheme-expressive", "scheme-fidelity",
                "scheme-fruit-salad", "scheme-monochrome", "scheme-neutral",
                "scheme-rainbow", "scheme-content",
            ]:
                r = subprocess.run(
                    [
                        "matugen", "-c", str(matugen_cfg), "image", str(p),
                        "-m", mode, "-t", sid, "--source-color-index", "0",
                        "--json", "hex",
                    ],
                    text=True,
                    capture_output=True,
                    timeout=180,
                    env=os.environ.copy(),
                )
                if r.returncode != 0:
                    detail = clean_process_text(r.stderr or r.stdout)
                    raise RuntimeError(detail or f"Matugen failed for {sid}")
                try:
                    raw = json.loads(r.stdout)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Matugen returned invalid JSON for {sid}: {exc}") from exc

                palette = self.extract_palette(raw, mode)
                if not palette:
                    raise RuntimeError(f"Matugen output did not contain a Material palette for {sid}")
                palette["id"] = sid
                palette["name"] = self.scheme_name(sid)
                schemes.append(palette)

            self.save_palette_cache(p, mode, schemes)
            return schemes, False
        finally:
            try:
                matugen_cfg.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def scheme_name(sid: str) -> str:
        return sid.removeprefix("scheme-").replace("-", " ").title()

    @staticmethod
    def extract_palette(raw, mode: str | None = None):
        def is_palette(x):
            return isinstance(x, dict) and all(k in x for k in ("primary", "secondary", "tertiary", "surface"))

        colors = raw.get("colors") if isinstance(raw, dict) else None
        if isinstance(colors, dict) and mode in colors and is_palette(colors[mode]):
            return colors[mode]

        def walk(x):
            if is_palette(x):
                return x
            if isinstance(x, dict):
                for v in x.values():
                    found = walk(v)
                    if found:
                        return found
            elif isinstance(x, list):
                for v in x:
                    found = walk(v)
                    if found:
                        return found
            return None

        found = walk(raw)
        if not found:
            return None
        # Normalize every role to a plain "#rrggbb" string so cache files never
        # depend on Matugen's object layout and always render in the GUI.
        clean = {}
        for key, val in found.items():
            parsed = hex_color(val, "")
            if parsed:
                clean[key] = parsed
        if not all(k in clean for k in ("primary", "secondary", "tertiary", "surface")):
            return None
        return clean

    def mode_changed(self,text):
        if self.busy:
            self.mode_box.blockSignals(True)
            self.mode_box.setCurrentText("Dark" if self.mode == "dark" else "Light")
            self.mode_box.blockSignals(False)
            return
        self.mode="dark" if text=="Dark" else "light"
        self._preview_generation += 1
        self.selected_scheme = self.scheme_choices.get(self.wallpaper_key()) if self.wallpaper else None
        self.save_state()
        if self.wallpaper:self.preview_palettes()

    def run_cli(self,args):
        env=os.environ.copy()
        # Normalize XDG/Themy paths so an empty shell variable cannot make the
        # GUI and CLI resolve different directories.
        env["XDG_CONFIG_HOME"] = str(XDG_CONFIG_HOME)
        env["XDG_DATA_HOME"] = str(XDG_DATA_HOME)
        env["XDG_STATE_HOME"] = str(XDG_STATE_HOME)
        env["THEMY_TEMPLATES_DIR"] = str(TEMPLATES_DIR)
        return subprocess.run([str(self.cli)]+args,text=True,capture_output=True,timeout=180,env=env)

    def preview_palettes(self):
        if not self.wallpaper or not self.wallpaper.is_file() or self.busy:
            return
        self.busy = True
        self._preview_generation += 1
        generation = self._preview_generation
        self.apply_btn.setEnabled(False)
        cached = self.load_palette_cache(self.wallpaper, self.mode)
        self.status.setText(
            "Loading cached color schemes…" if cached else "Generating color schemes with Matugen…"
        )
        p = self.wallpaper
        mode = self.mode

        def preview_task():
            try:
                return generation, str(p), mode, self.generate_schemes(p, mode)
            except Exception as exc:
                raise PreviewFailure(generation, str(p), mode, exc) from exc

        w = Worker(preview_task)
        w.signals.finished.connect(self.preview_done)
        self.pool.start(w)

    def preview_done(self, ok, payload):
        self.busy = False
        if not ok:
            if isinstance(payload, PreviewFailure):
                current_path = str(self.wallpaper) if self.wallpaper else ""
                if (
                    payload.generation != self._preview_generation
                    or payload.wallpaper != current_path
                    or payload.mode != self.mode
                ):
                    if self.wallpaper and self.wallpaper.is_file():
                        self.preview_palettes()
                    return
            detail = clean_process_text(str(payload))
            self.status.setText(f"Preview failed: {detail}")
            self.show_message(QMessageBox.Icon.Warning, "Themy", detail)
            return

        try:
            generation, requested_path, requested_mode, result = payload
        except Exception:
            self.status.setText("Preview failed.")
            return

        # A user can select another wallpaper while Matugen is working.
        # Never let an older worker overwrite the newer selection.
        current_path = str(self.wallpaper) if self.wallpaper else ""
        if (
            generation != self._preview_generation
            or requested_path != current_path
            or requested_mode != self.mode
        ):
            if self.wallpaper and self.wallpaper.is_file():
                self.preview_palettes()
            return

        self.schemes, cached = result

        if not self.schemes:
            self.status.setText("No schemes generated.")
            return

        if not any(x.get("id") == self.selected_scheme for x in self.schemes):
            self.selected_scheme = self.schemes[0].get("id")
            key = self.wallpaper_key()
            if key and self.selected_scheme:
                self.scheme_choices[key] = self.selected_scheme
                self.save_state()

        self.rebuild_schemes()
        selected = next(
            (x for x in self.schemes if x.get("id") == self.selected_scheme),
            self.schemes[0],
        )
        self.apply_palette(selected, animate=self._has_palette)
        self._has_palette = True

        state = "cached" if cached else "generated and cached"
        self.status.setText(f"{len(self.schemes)} schemes · {self.mode} mode · {state} · {self.wallpaper.name}")
        self.apply_btn.setEnabled(bool(self.selected_scheme))

    def rebuild_schemes(self):
        while self.scheme_layout.count() > 1:
            item=self.scheme_layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()
        self.scheme_cards.clear()
        for item in self.schemes:
            card=SchemeCard(item,item.get("id")==self.selected_scheme)
            card.clicked.connect(self.select_scheme)
            self.scheme_cards[item.get("id")]=card
            self.scheme_layout.insertWidget(self.scheme_layout.count()-1,card)

    def select_scheme(self,sid):
        if self.busy or sid == self.selected_scheme:
            return
        item=next((x for x in self.schemes if x.get("id")==sid),None)
        if not item:
            return
        self.selected_scheme=sid
        key=self.wallpaper_key()
        if key:
            self.scheme_choices[key]=sid
            self.save_state()
        for card_id, card in self.scheme_cards.items():
            card.set_selected(card_id == sid)
        self.apply_palette(item, animate=True)
        self.apply_btn.setEnabled(True)
        self.status.setText(f"Previewing {item.get('name',sid)} · {self.mode}")

    def dialog_stylesheet(self):
        c = getattr(self, "colors", DEFAULTS)
        return f"""
        QMessageBox {{ background:{c['surface']}; color:{c['text']}; border:1px solid {c['outline']}; }}
        QMessageBox QLabel {{ color:{c['text']}; background:transparent; }}
        QMessageBox QPushButton {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:8px; padding:7px 16px; min-width:64px; }}
        QMessageBox QPushButton:hover {{ background:{c['hover']}; }}
        QMessageBox QPushButton:default {{ background:{c['primary']}; color:{c['on_primary']}; border-color:{c['primary']}; }}
        QDialogButtonBox QPushButton {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:8px; padding:7px 16px; min-width:64px; }}
        QDialogButtonBox QPushButton:hover {{ background:{c['hover']}; }}
        QInputDialog {{ background:{c['surface']}; color:{c['text']}; }}
        QInputDialog QLabel {{ color:{c['text']}; background:transparent; }}
        QInputDialog QLineEdit {{ background:{c['surface_high']}; color:{c['text']}; border:1px solid {c['outline']}; border-radius:8px; padding:7px 9px; }}
        """

    def show_message(self, kind, title, text):
        box = QMessageBox(self)
        box.setIcon(kind)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStyleSheet(self.dialog_stylesheet())
        box.exec()

    def ask_apply(self, name):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Apply theme")
        box.setText(f"Apply {name} in {self.mode} mode?")
        box.setInformativeText("Only enabled programs will be updated. Themy will keep a backup so you can restore the previous theme.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.setStyleSheet(self.dialog_stylesheet())
        return box.exec() == QMessageBox.StandardButton.Yes

    def apply_theme(self):
        if not self.wallpaper or not self.selected_scheme or self.busy:return
        item=next((x for x in self.schemes if x.get("id")==self.selected_scheme),{}); name=item.get("name",self.selected_scheme)
        if not self.ask_apply(name):
            return
        self.busy=True; self.apply_btn.setEnabled(False); self.status.setText(f"Applying {name}…"); p=str(self.wallpaper); mode=self.mode; sid=self.selected_scheme
        w=Worker(lambda:self.run_cli([f"--{mode}","--scheme",sid,"--non-interactive",p])); w.signals.finished.connect(lambda ok,r:self.apply_done(ok,r,name)); self.pool.start(w)

    def apply_done(self,ok,r,name):
        self.busy=False
        if not ok:
            self.status.setText("Apply failed; rollback was attempted.")
            self.show_message(QMessageBox.Icon.Critical, "Themy", str(r))
        elif r.returncode==0:
            self.save_state()
            self.status.setText(f"Applied {name} · {self.mode}")
            self.restore_btn.setEnabled(self.backup_available())
            self.show_message(QMessageBox.Icon.Information, "Themy", "Theme applied successfully.")
        else:
            self.status.setText("Apply failed; rollback was attempted.")
            self.show_message(QMessageBox.Icon.Critical, "Themy", (r.stderr or r.stdout or "Themy failed.")[-4000:])
        self.apply_btn.setEnabled(bool(self.selected_scheme))


def main():
    cli=sys.argv[1] if len(sys.argv)>1 and sys.argv[1]!="--self-test" else str(Path(__file__).resolve().parents[1]/"themy")
    app=QApplication(sys.argv); app.setApplicationName("Themy"); app.setStyle("Fusion")
    win=ThemyWindow(cli); win.show()
    if "--self-test" in sys.argv:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(250, app.quit)
    return app.exec()

if __name__=="__main__": raise SystemExit(main())
