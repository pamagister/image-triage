"""Tkinter GUI: choose folders, run the selection, inspect ratings with preview."""

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ttkbootstrap
from config_cli_gui.gui import GenericSettingsDialog
from config_cli_gui.logging import connect_gui_logging, initialize_logging
from config_cli_gui.persistence import get_store_dir, read_last_used_config
from PIL import Image, ImageOps, ImageTk

from image_triage import pipeline
from image_triage.config import ImageTriageConfig
from image_triage.models import download_model
from image_triage.scan import Photo

PREVIEW_SIZE = (520, 400)


def load_config() -> tuple[ImageTriageConfig, Path]:
    """Load the last used config file, or defaults stored in the user's app folder."""
    app_name = ImageTriageConfig.get_app_name()
    last = read_last_used_config(app_name)
    if last and Path(last).exists():
        return ImageTriageConfig(last), Path(last)
    return ImageTriageConfig(), get_store_dir(app_name) / "config.yaml"


class MainWindow:
    def __init__(self, root: ttkbootstrap.Window, config: ImageTriageConfig, config_file: Path):
        self.root = root
        self.config = config
        self.config_file = config_file
        self.photos: dict[str, Photo] = {}
        self.preview_image = None

        root.title("Image Triage")
        root.geometry("1200x800")
        self._build_menu()
        self._build_widgets()

        self.logger = initialize_logging(
            log_level=config.app.log_level.value,
            enable_file_logging=False,
            enable_console_logging=False,
        ).get_logger("gui")
        connect_gui_logging(lambda msg: root.after(0, self._append_log, msg))
        self.logger.info(f"Configuration: {config_file}")

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Load config...", command=self._load_config_file)
        file_menu.add_command(label="Save config as...", command=self._save_config_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_command(label="Settings", command=self._open_settings)
        self.root.config(menu=menubar)

    def _build_widgets(self):
        general = self.config.general
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)
        self.input_var = tk.StringVar(value=str(general.input.value))
        self.output_var = tk.StringVar(value=str(general.output.value))
        self.dry_run_var = tk.BooleanVar(value=general.dry_run.value)
        self.top_n_var = tk.IntVar(value=self.config.selection.top_n.value)
        for row, (label, var) in enumerate(
            [("Input folder", self.input_var), ("Output folder", self.output_var)]
        ):
            ttk.Label(top, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            ttk.Entry(top, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
            ttk.Button(top, text="Browse", command=lambda v=var: self._browse(v)).grid(
                row=row, column=2, padx=(8, 0), pady=2
            )
        top.columnconfigure(1, weight=1)

        actions = ttk.Frame(top)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(actions, text="Top N (0 = by rating)").pack(side=tk.LEFT)
        ttk.Spinbox(actions, from_=0, to=100000, width=7, textvariable=self.top_n_var).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Checkbutton(actions, text="Dry run", variable=self.dry_run_var).pack(side=tk.LEFT)
        self.run_button = ttk.Button(actions, text="Run selection", command=self._run)
        self.run_button.pack(side=tk.LEFT, padx=10)
        self.download_button = ttk.Button(
            actions, text="Download model", command=self._download_model
        )
        self.download_button.pack(side=tk.RIGHT, padx=(8, 0))
        self.model_status = ttk.Label(actions)
        self.model_status.pack(side=tk.RIGHT, padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._update_model_status()

        panes = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        results = ttk.PanedWindow(panes, orient=tk.HORIZONTAL)
        columns = ("selected", "rating", "group", "sharpness", "exposure", "score", "objects")
        tree_frame = ttk.Frame(results)
        self.tree = ttk.Treeview(tree_frame, columns=columns, selectmode="browse")
        self.tree.heading("#0", text="File")
        self.tree.column("#0", width=260)
        for col in columns:
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=80, anchor="e")
        self.tree.column("selected", width=60, anchor="center")
        self.tree.column("objects", width=160, anchor="w")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._show_preview)
        self.tree.bind("<Double-1>", self._open_selected)
        results.add(tree_frame, weight=1)

        self.preview = ttk.Label(results, anchor="center")
        results.add(self.preview, weight=1)
        panes.add(results, weight=3)

        log_frame = ttk.Frame(panes)
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.NONE)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        panes.add(log_frame, weight=1)

    def _browse(self, var: tk.StringVar):
        folder = filedialog.askdirectory(initialdir=var.get() or ".")
        if folder:
            var.set(folder)

    def _append_log(self, msg: str):
        self.log_text.insert(tk.END, msg)
        self.log_text.see(tk.END)

    def _sync_main_fields_to_config(self):
        general = self.config.general
        general.input.value = Path(self.input_var.get())
        general.output.value = Path(self.output_var.get())
        general.dry_run.value = self.dry_run_var.get()
        self.config.selection.top_n.value = self.top_n_var.get()

    def _sync_config_to_main_fields(self):
        general = self.config.general
        self.input_var.set(str(general.input.value))
        self.output_var.set(str(general.output.value))
        self.dry_run_var.set(general.dry_run.value)
        self.top_n_var.set(self.config.selection.top_n.value)
        self._update_model_status()

    def _run(self):
        self._sync_main_fields_to_config()
        self.config.save_to_file(str(self.config_file))
        self.run_button.config(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.photos.clear()
        self.progress["value"] = 0
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self):
        try:
            self.logger.setLevel(self.config.app.log_level.value)
            photos = pipeline.run(self.config, self.logger, progress=self._report_progress)
            self.root.after(0, self._show_results, photos)
        except Exception as e:
            self.logger.error(f"Selection failed: {e}")
            self.root.after(0, lambda msg=str(e): messagebox.showerror("Error", msg))
        finally:
            self.root.after(0, lambda: self.run_button.config(state="normal"))

    def _report_progress(self, done: int, total: int):
        if total:
            self.root.after(0, lambda: self.progress.configure(value=100 * done / total))

    def _show_results(self, photos: list[Photo]):
        input_root = Path(self.config.general.input.value)
        for photo in photos:
            iid = self.tree.insert(
                "",
                tk.END,
                text=str(photo.path.relative_to(input_root)),
                values=(
                    "✓" if photo.selected else "",
                    "★" * photo.rating,
                    photo.group,
                    f"{photo.sharpness:.1f}",
                    f"{photo.exposure:.2f}",
                    f"{photo.score:.2f}",
                    ", ".join(sorted({d.label for d in photo.objects})),
                ),
            )
            self.photos[iid] = photo

    def _selected_photo(self) -> Photo | None:
        selection = self.tree.selection()
        return self.photos.get(selection[0]) if selection else None

    def _show_preview(self, _event=None):
        photo = self._selected_photo()
        if not photo:
            return
        with Image.open(photo.path) as image:
            image.draft("RGB", PREVIEW_SIZE)
            preview = ImageOps.exif_transpose(image).convert("RGB")
        preview.thumbnail(PREVIEW_SIZE)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.preview.configure(image=self.preview_image)

    def _open_selected(self, _event=None):
        photo = self._selected_photo()
        if not photo:
            return
        if sys.platform == "win32":
            os.startfile(photo.path)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(photo.path)])

    def _model_path(self) -> Path:
        return Path(self.config.models.object_detector.value)

    def _update_model_status(self):
        installed = self._model_path().is_file()
        self.model_status.config(text="Model: installed" if installed else "Model: missing")
        self.download_button.config(state="disabled" if installed else "normal")

    def _download_model(self):
        path = self._model_path()
        self.download_button.config(state="disabled")
        self.progress["value"] = 0
        self.logger.info(f"Downloading object model to {path}")
        threading.Thread(target=self._download_worker, args=(path,), daemon=True).start()

    def _download_worker(self, path: Path):
        try:
            download_model(path, progress=self._report_progress)
            self.logger.info("Model downloaded")
        except Exception as e:
            self.logger.error(f"Model download failed: {e}")
            self.root.after(0, lambda msg=str(e): messagebox.showerror("Error", msg))
        finally:
            self.root.after(0, self._update_model_status)

    def _open_settings(self):
        self._sync_main_fields_to_config()
        dialog = GenericSettingsDialog(self.root, self.config, config_file=str(self.config_file))
        self.root.wait_window(dialog.dialog)
        self._sync_config_to_main_fields()

    def _load_config_file(self):
        path = filedialog.askopenfilename(filetypes=[("YAML", "*.yaml *.yml"), ("JSON", "*.json")])
        if not path:
            return
        try:
            self.config = ImageTriageConfig(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not load configuration: {e}")
            return
        self.config_file = Path(path)
        self._sync_config_to_main_fields()
        self.logger.info(f"Configuration: {path}")

    def _save_config_file(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".yaml", filetypes=[("YAML", "*.yaml"), ("JSON", "*.json")]
        )
        if not path:
            return
        self._sync_main_fields_to_config()
        self.config.save_to_file(path)
        self.config_file = Path(path)
        self.logger.info(f"Configuration saved: {path}")


def main():
    config, config_file = load_config()
    root = ttkbootstrap.Window(themename=config.app.theme.value)
    MainWindow(root, config, config_file)
    root.mainloop()


if __name__ == "__main__":
    main()
