from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

import ttkbootstrap as tb  # modern themed ttk
from ttkbootstrap.constants import *  # type: ignore
from tkinterdnd2 import DND_FILES, TkinterDnD
from tkinter import filedialog, messagebox

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
_LOGGER = logging.getLogger(__name__)

###############################################################################
# Core conversion helpers
###############################################################################

def get_label(node: dict) -> str:
    pl = node.get("programLabel")
    if isinstance(pl, str) and pl.strip():
        return pl.strip()
    if isinstance(pl, list):
        parts: List[str] = []
        for d in pl:
            if "value" in d:
                parts.append(str(d["value"]))
            elif "translationKey" in d:
                key: str = d["translationKey"]
                if key.startswith("program-node-label."):
                    key = key[len("program-node-label.") :]
                parts.append(key.replace(".", " ").title())
        if parts:
            return " ".join(parts).strip()
    ctype = node.get("contributedNode", {}).get("type")
    if ctype:
        return ctype.replace("ur-", "").replace("-", " ").title()
    return "Unknown"

def _walk_pretty(node: dict, indent: int = 0, lines: list[str] | None = None) -> list[str]:
    lines = lines or []
    lines.append("  " * indent + get_label(node))
    for child in node.get("children", []):
        _walk_pretty(child, indent + 1, lines)
    return lines


def urpx_to_script(data: dict, stem: str, dst_dir: Path) -> Path:
    func_name = data.get("application", {}).get("applicationInfo", {}).get("name", stem)
    urscript = data.get("application", {}).get("urscript", {}).get("script", "")
    lines = [f"def {func_name}():", "  global _hidden_verificationVariable = 0"]
    lines.extend(f"  {ln}" for ln in urscript.splitlines())
    out = dst_dir / f"{stem}_converted.script"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def urpx_to_txt(data: dict, stem: str, dst_dir: Path) -> Path:
    root = {"name": "Program", "children": []}
    vars_node = {"name": "Variables Setup", "children": []}
    for var in data.get("program", {}).get("variableDeclarations", []):
        vars_node["children"].append({"programLabel": var.get("name", "<anon>")})
    root["children"].append(vars_node)

    prog_children = data.get("program", {}).get("programContent", {}).get("children", [])
    func_nodes = next(
        (n.get("children", []) for n in prog_children if n.get("contributedNode", {}).get("type") == "ur-functions"),
        [],
    )
    main_func_children = func_nodes[0].get("children", []) if func_nodes else []
    root["children"].append({"name": "Robot Program", "children": main_func_children})

    out = dst_dir / f"{stem}_converted.txt"
    out.write_text("\n".join(_walk_pretty(root)), encoding="utf-8")
    return out

###############################################################################
# GUI
###############################################################################

@dataclass
class Job:
    src: Path
    dst: Path
    mode: str  # "script" or "txt"

    def run(self) -> Path:
        data = json.loads(self.src.read_text(encoding="utf-8"))
        if self.mode == "script":
            return urpx_to_script(data, self.src.stem, self.dst)
        return urpx_to_txt(data, self.src.stem, self.dst)


class URPXApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("URPX Converter ✨")
        self.geometry("700x460")
        self.style = tb.Style("flatly")

        self.files: List[Path] = []
        self.output_dir: Path | None = None
        self.mode = tb.StringVar(value="script")

        self._build_widgets()

    # Build UI ----------------------------------------------------------- #
    def _build_widgets(self):
        pad = 10
        # Drop zone
        drop = tb.Frame(self, padding=pad, bootstyle=INFO, relief="ridge")
        drop.pack(fill=BOTH, expand=True, padx=pad, pady=(pad, 0))
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", self._on_drop)

        tb.Label(drop, text="➕  Drag *.urpx* files here or click Add", bootstyle="inverse-info").pack(fill=BOTH, expand=True)

        # Treeview list (no bootstyle arg!)
        self.list = tb.Treeview(drop, columns=("dummy",), show="tree", height=10)
        self.list.pack(fill=BOTH, expand=True, pady=(pad, 0))
        # manual striping
        self.list.tag_configure("odd", background=self.style.colors.light)

        # Bottom bar
        bar = tb.Frame(self, padding=pad)
        bar.pack(fill=X, side=BOTTOM)

        tb.Radiobutton(bar, text=".script", variable=self.mode, value="script").pack(side=LEFT)
        tb.Radiobutton(bar, text=".txt", variable=self.mode, value="txt").pack(side=LEFT, padx=(0, pad))

        tb.Button(bar, text="Output folder", command=self._choose_output).pack(side=LEFT)
        tb.Button(bar, text="Convert", bootstyle=SUCCESS, command=self._convert).pack(side=RIGHT)
        self.prog = tb.Progressbar(bar, mode="determinate", length=150)
        self.prog.pack(side=RIGHT, padx=(0, pad))

        tb.Button(self, text="Add", bootstyle=SECONDARY, command=self._add_dialog).pack(side=TOP, anchor="ne", padx=pad, pady=(pad, 0))

    # Event handlers ----------------------------------------------------- #
    def _on_drop(self, event):
        self._add_files(self._parse_paths(event.data))

    def _add_dialog(self):
        paths = filedialog.askopenfilenames(title="Select URPX files", filetypes=[("URPX", "*.urpx"), ("All", "*.*")])
        self._add_files(paths)

    def _choose_output(self):
        folder = filedialog.askdirectory(title="Output directory")
        if folder:
            self.output_dir = Path(folder)

    # Conversion --------------------------------------------------------- #
    def _convert(self):
        if not self.files:
            messagebox.showwarning("No input", "Add .urpx files first")
            return
        if self.output_dir is None:
            messagebox.showwarning("No output", "Choose output directory")
            return

        self.prog.configure(maximum=len(self.files), value=0)
        errors, done = [], []
        for i, fp in enumerate(self.files, 1):
            try:
                res = Job(fp, self.output_dir, self.mode.get()).run()
                done.append(res.name)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fp.name}: {exc}")
            self.prog.configure(value=i)
            self.update_idletasks()

        if errors:
            messagebox.showerror("Errors", "\n".join(errors))
        else:
            messagebox.showinfo("Done", "Converted:\n" + "\n".join(done))

    # Helpers ------------------------------------------------------------ #
    def _add_files(self, paths):
        for p in paths:
            path = Path(p)
            if path.suffix.lower() != ".urpx" or path in self.files:
                continue
            self.files.append(path)
            tag = "odd" if len(self.files) % 2 else "even"
            self.list.insert("", END, iid=str(path), text=path.name, tags=(tag,))

    @staticmethod
    def _parse_paths(data: str) -> List[str]:
        if sys.platform == "win32":
            data = data.strip("{}")
            return [p.strip("{}") for p in data.split("} {")]
        return data.split()


if __name__ == "__main__":
    app = URPXApp()
    app.mainloop()
