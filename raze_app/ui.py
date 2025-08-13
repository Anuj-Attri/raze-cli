# raze_app/ui.py
# Native PySide6 UI: chat-driven flow, two-column layout, Apply plan with quarantine
# Requires: pip install PySide6
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLineEdit, QListWidget, QLabel, QFileDialog, QSplitter, QTreeWidget,
    QTreeWidgetItem, QListWidgetItem, QDialog, QFormLayout, QDialogButtonBox,
    QCheckBox, QMessageBox
)
from pathlib import Path
import json, threading, re, os, traceback

# Backend pipeline + executor
try:
    from raze_cli.pipeline import run_pipeline
except Exception:
    run_pipeline = None
try:
    from raze_cli.plan_apply import apply_plan
except Exception:
    apply_plan = None


def human_bytes(n: int) -> str:
    if n is None: return "0 B"
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} PB"

def cluster_key(bucket: str, sub: str) -> str:
    return f"{bucket}:{sub}"

# ---------------- Settings dialog ----------------

class SettingsDialog(QDialog):
    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        self.endpoint = QLineEdit()
        self.model = QLineEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("Storage $/GB/month (e.g., 0.023)")
        self.dry_run = QCheckBox("Apply in Dry-Run (quarantine/move preview only)")

        if initial:
            self.endpoint.setText(initial.get("endpoint",""))
            self.model.setText(initial.get("model",""))
            self.api_key.setText(initial.get("api_key",""))
            if initial.get("rate") is not None:
                self.rate.setText(str(initial.get("rate")))
            self.dry_run.setChecked(bool(initial.get("dry_run", False)))

        form = QFormLayout()
        form.addRow("LLM Endpoint:", self.endpoint)
        form.addRow("LLM Model:", self.model)
        form.addRow("API Key:", self.api_key)
        form.addRow("Storage $/GB:", self.rate)
        form.addRow("", self.dry_run)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def data(self):
        try:
            rate = float(self.rate.text().strip()) if self.rate.text().strip() else 0.0
        except Exception:
            rate = 0.0
        return dict(
            endpoint=self.endpoint.text().strip(),
            model=self.model.text().strip(),
            api_key=self.api_key.text().strip(),
            rate=rate,
            dry_run=self.dry_run.isChecked()
        )

# ---------------- Main window ----------------

class RazeApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAZE — Offline Copilot")
        self.resize(1320, 860)

        self.settings = {
            "endpoint": "http://localhost:11434/v1",
            "model": "llama3",   # swap to GPT-OSS model name when available in Ollama
            "api_key": "ollama",
            "rate": 0.0,
            "dry_run": False
        }
        self.last_path = ""
        self.last_output = None   # {"graph":..., "summaries":..., "plan":...}

        root = QVBoxLayout(self)

        # Top bar: pick directory + settings + organize
        top = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_btn = QPushButton("Browse…")
        self.settings_btn = QPushButton("Settings")
        self.organize_btn = QPushButton("Organize")
        top.addWidget(QLabel("Directory:"))
        top.addWidget(self.dir_edit, 1)
        top.addWidget(self.dir_btn)
        top.addStretch(1)
        top.addWidget(self.settings_btn)
        top.addWidget(self.organize_btn)
        root.addLayout(top)

        # Splitter: left (structure) | right (clusters)
        spl = QSplitter()
        spl.setOrientation(QtCore.Qt.Horizontal)
        root.addWidget(spl, 1)

        # Left: Proposed Structure + Apply
        leftWrap = QWidget()
        leftLay = QVBoxLayout(leftWrap)
        leftLay.addWidget(QLabel("Proposed File Structure"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Path / Operation", "Info"])
        self.apply_btn = QPushButton("Apply Plan")
        self.apply_btn.setEnabled(False)
        leftLay.addWidget(self.tree, 1)
        leftLay.addWidget(self.apply_btn)
        spl.addWidget(leftWrap)

        # Right: AI Clusters (cards)
        rightWrap = QWidget()
        rightLay = QVBoxLayout(rightWrap)
        headRow = QHBoxLayout()
        headRow.addWidget(QLabel("AI Clusters"))
        headRow.addStretch(1)
        self.cost_label = QLabel("")
        headRow.addWidget(self.cost_label)
        rightLay.addLayout(headRow)
        self.clusters = QListWidget()
        self.clusters.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        rightLay.addWidget(self.clusters, 1)
        spl.addWidget(rightWrap)
        spl.setSizes([700, 620])

        # Bottom: Chat bar (prompt-driven)
        chatRow = QHBoxLayout()
        self.chat = QLineEdit()
        self.chat.setPlaceholderText('Chat with RAZE… e.g., "organize X", "/rate 0.023", "/apply", "/help"')
        self.send_btn = QPushButton("Send")
        chatRow.addWidget(self.chat, 1)
        chatRow.addWidget(self.send_btn)
        root.addLayout(chatRow)

        # Connections
        self.dir_btn.clicked.connect(self.browse)
        self.settings_btn.clicked.connect(self.open_settings)
        self.organize_btn.clicked.connect(self.organize_clicked)
        self.apply_btn.clicked.connect(self.apply_clicked)
        self.send_btn.clicked.connect(self.on_chat)

    # ---------- UI helpers ----------

    def log_error(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose directory")
        if d:
            self.dir_edit.setText(d)

    # ---------- Chat handling ----------

    def on_chat(self):
        text = self.chat.text().strip()
        if not text:
            return
        # Commands
        if text.startswith("/"):
            self.run_command(text)
            self.chat.clear()
            return

        # Natural language intents (basic)
        # "organize X" "organize directory X"
        m = re.match(r'(?i)organize\s+(?:directory\s+)?(.+)$', text)
        if m:
            path = m.group(1).strip().strip('"')
            self.dir_edit.setText(path)
            self.chat.clear()
            self.organize_clicked()
            return

        # Fallback: if directory already set, treat as "organize"
        if self.dir_edit.text().strip():
            self.chat.clear()
            self.organize_clicked()
            return
        else:
            self.log_error("Need a directory", "Tell me which folder to organize (e.g., “organize C:\\Data”).")

    def run_command(self, cmd: str):
        # /rate 0.023
        m = re.match(r'(?i)^/rate\s+([0-9]*\.?[0-9]+)$', cmd)
        if m:
            self.settings["rate"] = float(m.group(1))
            QMessageBox.information(self, "Rate updated", f"Storage rate set to ${self.settings['rate']}/GB.")
            return
        # /endpoint URL
        m = re.match(r'(?i)^/endpoint\s+(\S+)$', cmd)
        if m:
            self.settings["endpoint"] = m.group(1)
            QMessageBox.information(self, "Endpoint updated", self.settings["endpoint"])
            return
        # /model NAME
        m = re.match(r'(?i)^/model\s+(.+)$', cmd)
        if m:
            self.settings["model"] = m.group(1).strip()
            QMessageBox.information(self, "Model updated", self.settings["model"])
            return
        # /apply
        if re.match(r'(?i)^/apply$', cmd):
            self.apply_clicked()
            return
        # /dryrun on|off
        m = re.match(r'(?i)^/dryrun\s+(on|off)$', cmd)
        if m:
            self.settings["dry_run"] = (m.group(1).lower() == "on")
            QMessageBox.information(self, "Dry-Run", f"Dry-run = {self.settings['dry_run']}")
            return
        # /help
        if re.match(r'(?i)^/help$', cmd):
            QMessageBox.information(self, "Help", "/rate 0.023\n/endpoint http://localhost:11434/v1\n/model llama3\n/dryrun on|off\n/apply\norganize <path>")
            return

        QMessageBox.information(self, "Unknown command", "Try /help")

    # ---------- Settings & organize ----------

    def open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.Accepted:
            self.settings.update(dlg.data())

    def organize_clicked(self):
        if run_pipeline is None:
            self.log_error("Pipeline missing", "raze_cli.pipeline.run_pipeline not found.")
            return
        path = self.dir_edit.text().strip()
        if not path or not Path(path).exists():
            self.log_error("Invalid directory", "Pick a valid folder first.")
            return

        self.last_path = path
        self.organize_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.tree.clear()
        self.clusters.clear()
        self.cost_label.setText("")

        t = threading.Thread(target=self._bg_run, daemon=True)
        t.start()

    def _bg_run(self):
        try:
            out = run_pipeline(
                path=self.last_path,
                llm_endpoint=self.settings.get("endpoint") or None,
                llm_model=self.settings.get("model") or None,
                api_key=self.settings.get("api_key") or None,
                storage_rate_per_gb=float(self.settings.get("rate") or 0.0),
            )
        except Exception as e:
            tb = traceback.format_exc()
            QtCore.QMetaObject.invokeMethod(
                self, "show_error",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, f"Pipeline failed: {e}\n\n{tb}")
            )
            QtCore.QMetaObject.invokeMethod(self.organize_btn, "setEnabled", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(bool, True))
            return

        self.last_output = out
        QtCore.QMetaObject.invokeMethod(self, "render_results", QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def render_results(self):
        self.organize_btn.setEnabled(True)
        if not self.last_output:
            return
        plan = self.last_output.get("plan", {})
        graph = self.last_output.get("graph", {})
        self.populate_structure(plan)
        self.populate_clusters(graph, plan)
        self.apply_btn.setEnabled(True)

    def populate_structure(self, plan: dict):
        self.tree.clear()
        moves = plan.get("moves", [])
        deletes = plan.get("deletes", [])
        # Root items
        mv_root = QTreeWidgetItem(["Moves (proposed)", f"{len(moves)}"])
        del_root = QTreeWidgetItem(["Deletes (to quarantine)", f"{len(deletes)}"])
        self.tree.addTopLevelItem(mv_root)
        self.tree.addTopLevelItem(del_root)

        # Moves grouped by destination
        by_dst = {}
        for mv in moves:
            by_dst.setdefault(mv.get("to",""), []).append(mv)
        for dst, mvs in sorted(by_dst.items()):
            p = QTreeWidgetItem([dst, f"{len(mvs)} files"])
            mv_root.addChild(p)
            for mv in mvs[:500]:  # cap for UI
                name = Path(mv.get("from") or "").name
                p.addChild(QTreeWidgetItem([f"{name}  →  {dst}", mv.get("reason","")]))
        mv_root.setExpanded(True)

        # Deletes grouped by reason
        by_reason = {}
        for de in deletes:
            by_reason.setdefault(de.get("reason","unknown"), []).append(de)
        for reason, items in sorted(by_reason.items()):
            p = QTreeWidgetItem([reason, f"{len(items)} files"])
            del_root.addChild(p)
            for de in items[:500]:
                name = Path(de.get("path") or "").name
                p.addChild(QTreeWidgetItem([name, f"{de.get('confidence',0):.2f}"]))
        del_root.setExpanded(True)

        # Totals
        total_gb = 0.0
        costs = self.last_output["plan"].get("cluster_costs", {})
        for meta in costs.values():
            total_gb += float(meta.get("gb", 0.0))
        rate = float(self.settings.get("rate") or 0.0)
        total_cost = total_gb * rate
        self.cost_label.setText(f"Total size: {total_gb:.3f} GB | est ${total_cost:.2f}/mo at ${rate}/GB")

    def populate_clusters(self, graph: dict, plan: dict):
        self.clusters.clear()
        # Build a quick index: cluster -> file_ids
        cluster_files = {}   # key "Bucket:Sub" => set(ids)
        for n in graph.get("nodes", []):
            if n.get("kind") == "subcategory":
                label = n.get("label","")
                # label format: "Bucket → Sub"
                if "→" in label:
                    bucket, sub = [s.strip() for s in label.split("→", 1)]
                else:
                    bucket = n.get("meta",{}).get("bucket","Category")
                    sub = label
                k = cluster_key(bucket, sub)
                cluster_files[k] = set(n.get("meta",{}).get("file_ids", []))

        # Build delete set to estimate junkiness
        delete_ids = set(d.get("id") for d in plan.get("deletes", []))
        moves = plan.get("moves", [])
        costs = plan.get("cluster_costs", {})

        for key, ids in sorted(cluster_files.items()):
            total = len(ids)
            del_count = len(ids & delete_ids)
            ratio = (del_count / total) if total else 0.0

            # Heuristic Junk coloring until adjudicator is added:
            # >= 0.5 -> JUNK, 0.2..0.5 -> REVIEW, else NOT JUNK
            if ratio >= 0.5:
                status = "JUNK"
                color = QtGui.QColor("#ef4444")  # red
            elif ratio >= 0.2:
                status = "REVIEW"
                color = QtGui.QColor("#f59e0b")  # amber
            else:
                status = "NOT JUNK"
                color = QtGui.QColor("#22c55e")  # green

            meta = costs.get(key, {})
            gb = meta.get("gb", 0.0)
            cost = meta.get("monthly_cost", 0.0)
            text = f"{key} — {status}\nFiles: {total} | Deletes flagged: {del_count} | Size: {gb:.3f} GB | Est: ${cost:.2f}/mo"
            item = QListWidgetItem(text)

            # Color bar
            brush = QtGui.QBrush(color)
            item.setBackground(brush)
            item.setToolTip(text)
            self.clusters.addItem(item)

    # ---------- Apply plan ----------

    def apply_clicked(self):
        if apply_plan is None:
            self.log_error("Apply missing", "raze_cli.plan_apply.apply_plan not found.")
            return
        if not self.last_output:
            self.log_error("No plan", "Run 'Organize' first to build a plan.")
            return
        plan = self.last_output.get("plan")
        if not plan:
            self.log_error("No plan", "Plan data missing.")
            return

        # Save plan to disk (so executor can read it)
        plan_path = Path(self.last_path) / ".raze-last-plan.json"
        try:
            plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        except Exception as e:
            self.log_error("Write failed", f"Could not write plan file:\n{e}")
            return

        dry_run = bool(self.settings.get("dry_run", False))
        try:
            audit = apply_plan(str(plan_path), root=self.last_path, dry_run=dry_run, quarantine_days=30)
        except Exception as e:
            tb = traceback.format_exc()
            self.log_error("Apply failed", f"{e}\n\n{tb}")
            return

        if dry_run:
            QMessageBox.information(self, "Dry-Run complete", f"Moves/Deletes simulated. Audit log:\n{audit}")
        else:
            QMessageBox.information(self, "Applied", f"Plan applied. Audit log:\n{audit}")

    # ---------- Qt slot for background errors ----------

    @QtCore.Slot(str)
    def show_error(self, msg: str):
        self.log_error("Error", msg)


def main():
    app = QApplication([])
    w = RazeApp()
    w.show()
    app.exec()

if __name__ == "__main__":
    main()
