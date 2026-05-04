"""Tkinter UI skeleton for the control panel.

Layout (top to bottom):
  * Player selector + Refresh
  * Live readout of every skill's current value for the selected player
  * Skill selector + delta spinbox + Apply button
  * Activity log

Long-running operations (Sheets I/O, Discord HTTP) are dispatched to a
single worker thread and the result is marshalled back to the Tk main
loop via :class:`queue.Queue` polled with ``root.after``. This keeps
the window responsive without sprinkling ``threading`` calls through
the rest of the codebase.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

from .hat import HatCommandError
from .logic import AppService, HatRollResult, IncrementResult, SheetsError

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# ttk vs ttkbootstrap shim
# --------------------------------------------------------------------------
def _build_root() -> tuple[tk.Tk, Any]:
    """Return ``(root, widget_module)``.

    When ``ttkbootstrap`` is installed we use its ``Window`` so the
    Bootstrap theme is applied to every ttk widget under it. We still
    return the standard :mod:`tkinter.ttk` module for widget creation
    though — ttkbootstrap re-exports some classic ``tk`` widgets (e.g.
    ``LabelFrame``) which don't accept ``padding=`` and friends.
    Sticking with ``ttk`` keeps widget options uniform; the global
    bootstrap theme still themes them because the style is shared.
    """
    try:
        import ttkbootstrap as tb  # type: ignore[import-not-found]

        root = tb.Window(themename="darkly")
    except ImportError:
        log.info("ttkbootstrap not installed; falling back to plain ttk")
        root = tk.Tk()
    return root, ttk


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------
@dataclass
class _Job:
    work: Callable[[], Any]
    on_success: Callable[[Any], None]
    on_error: Callable[[Exception], None]


class _Worker:
    """Tiny single-threaded background worker with Tk-safe callbacks."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._results: queue.Queue[tuple[_Job, Any, Exception | None]] = queue.Queue()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._root.after(50, self._drain_results)

    def submit(
        self,
        work: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self._jobs.put(_Job(work, on_success, on_error))

    def stop(self) -> None:
        self._stopping.set()
        self._jobs.put(_Job(lambda: None, lambda _r: None, lambda _e: None))

    def _loop(self) -> None:
        while not self._stopping.is_set():
            job = self._jobs.get()
            if self._stopping.is_set():
                return
            try:
                result = job.work()
                self._results.put((job, result, None))
            except Exception as exc:  # noqa: BLE001
                self._results.put((job, None, exc))

    def _drain_results(self) -> None:
        try:
            while True:
                job, result, error = self._results.get_nowait()
                if error is not None:
                    job.on_error(error)
                else:
                    job.on_success(result)
        except queue.Empty:
            pass
        if not self._stopping.is_set():
            self._root.after(50, self._drain_results)


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------
class ControlPanel:
    PADDING = 10

    def __init__(self, service: AppService, *, demo_mode: bool = False) -> None:
        self.service = service
        self.demo_mode = demo_mode
        self.root, self._tk = _build_root()
        title = "Skill Tracker — DEMO" if demo_mode else "Skill Tracker — Discord + Sheets"
        self.root.title(title)
        self.root.geometry("640x700")
        self.root.minsize(540, 620)

        self._worker = _Worker(self.root)
        self._skill_value_vars: dict[str, tk.StringVar] = {}
        self._busy = False

        self._build_layout()
        self._populate_initial_state()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- layout ------------------------------------------------------
    def _build_layout(self) -> None:
        outer = self._tk.Frame(self.root, padding=self.PADDING)
        outer.pack(fill="both", expand=True)

        if self.demo_mode:
            self._build_demo_banner(outer)
        self._build_player_bar(outer)
        self._build_skills_panel(outer)
        self._build_action_bar(outer)
        self._build_hat_panel(outer)
        self._build_log_panel(outer)

    def _build_demo_banner(self, parent: Any) -> None:
        text = (
            "DEMO MODE — no Google Sheets reads/writes, no Discord posts. "
            "Re-run with --live (and a real config.json) to enable the real backends."
        )
        banner = self._tk.Label(
            parent,
            text=text,
            anchor="w",
            justify="left",
            padding=(8, 6),
        )
        try:
            banner.configure(bootstyle="warning-inverse")  # ttkbootstrap
        except tk.TclError:
            pass
        banner.pack(fill="x", pady=(0, self.PADDING))

    def _build_player_bar(self, parent: Any) -> None:
        bar = self._tk.Frame(parent)
        bar.pack(fill="x", pady=(0, self.PADDING))

        self._tk.Label(bar, text="Player:").pack(side="left")

        self.player_var = tk.StringVar()
        self.player_combo = self._tk.Combobox(
            bar,
            textvariable=self.player_var,
            values=self.service.player_names,
            state="readonly",
            width=24,
        )
        self.player_combo.pack(side="left", padx=(6, 12))
        self.player_combo.bind("<<ComboboxSelected>>", lambda _e: self._reload_skills())

        self.refresh_btn = self._tk.Button(
            bar, text="Refresh", command=lambda: self._reload_skills(force=True)
        )
        self.refresh_btn.pack(side="left")

        self.config_label = self._tk.Label(
            bar,
            text=f"config: {self.service.config.source_path.name}",
        )
        self.config_label.pack(side="right")

    def _build_skills_panel(self, parent: Any) -> None:
        frame = self._tk.LabelFrame(parent, text="Current skills", padding=self.PADDING)
        frame.pack(fill="both", expand=False, pady=(0, self.PADDING))

        for row, skill in enumerate(self.service.skill_names):
            self._tk.Label(frame, text=skill).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=2
            )
            var = tk.StringVar(value="—")
            self._skill_value_vars[skill] = var
            self._tk.Label(frame, textvariable=var, width=8, anchor="e").grid(
                row=row, column=1, sticky="e", pady=2
            )

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0)

    def _build_action_bar(self, parent: Any) -> None:
        bar = self._tk.LabelFrame(parent, text="Apply change", padding=self.PADDING)
        bar.pack(fill="x", pady=(0, self.PADDING))

        self._tk.Label(bar, text="Skill:").grid(row=0, column=0, sticky="w")

        self.skill_var = tk.StringVar()
        self.skill_combo = self._tk.Combobox(
            bar,
            textvariable=self.skill_var,
            values=self.service.skill_names,
            state="readonly",
            width=18,
        )
        self.skill_combo.grid(row=0, column=1, padx=(6, 12), sticky="w")

        self._tk.Label(bar, text="Δ:").grid(row=0, column=2, sticky="w")

        self.delta_var = tk.IntVar(value=1)
        self.delta_spin = tk.Spinbox(
            bar,
            from_=-99,
            to=99,
            textvariable=self.delta_var,
            width=6,
            justify="right",
        )
        self.delta_spin.grid(row=0, column=3, padx=(6, 12), sticky="w")

        self.apply_btn = self._tk.Button(bar, text="Apply", command=self._on_apply)
        self.apply_btn.grid(row=0, column=4, sticky="w")

        bar.columnconfigure(5, weight=1)

    def _build_hat_panel(self, parent: Any) -> None:
        die = self.service.config.hat.die
        title = f"Hat roll  (d{die}, or `hit` for d100)"
        bar = self._tk.LabelFrame(parent, text=title, padding=self.PADDING)
        bar.pack(fill="x", pady=(0, self.PADDING))

        self._tk.Label(bar, text="/hat").grid(row=0, column=0, sticky="w")

        self.hat_var = tk.StringVar()
        self.hat_entry = self._tk.Entry(bar, textvariable=self.hat_var, width=28)
        self.hat_entry.grid(row=0, column=1, padx=(6, 12), sticky="ew")
        self.hat_entry.bind("<Return>", lambda _e: self._on_hat_roll())

        self.hat_btn = self._tk.Button(bar, text="Roll", command=self._on_hat_roll)
        self.hat_btn.grid(row=0, column=2, sticky="w")

        hint = self._tk.Label(
            bar,
            text="e.g.  `52`   `3 33`   `hit`   `3 hit`   `3hit`",
        )
        hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        bar.columnconfigure(1, weight=1)

    def _build_log_panel(self, parent: Any) -> None:
        frame = self._tk.LabelFrame(parent, text="Activity", padding=self.PADDING)
        frame.pack(fill="both", expand=True)

        self.log_widget = scrolledtext.ScrolledText(
            frame, height=10, state="disabled", wrap="word"
        )
        self.log_widget.pack(fill="both", expand=True)

    # ---- behaviour ---------------------------------------------------
    def _populate_initial_state(self) -> None:
        names = self.service.player_names
        if names:
            self.player_var.set(names[0])
            self._reload_skills()
        if self.service.skill_names:
            self.skill_var.set(self.service.skill_names[0])

    def _selected_player(self) -> str | None:
        name = self.player_var.get().strip()
        return name or None

    def _reload_skills(self, *, force: bool = False) -> None:
        player = self._selected_player()
        if player is None:
            return
        self._set_busy(True)
        self._log(f"Loading skills for {player}…")
        for var in self._skill_value_vars.values():
            var.set("…")

        self._worker.submit(
            work=lambda: self.service.load_skills(player, force=force),
            on_success=lambda values: self._on_skills_loaded(player, values),
            on_error=lambda exc: self._on_load_error(player, exc),
        )

    def _on_skills_loaded(self, player: str, values: dict[str, int]) -> None:
        for skill, var in self._skill_value_vars.items():
            var.set(str(values.get(skill, 0)))
        self._log(f"Loaded {len(values)} skills for {player}.")
        self._set_busy(False)

    def _on_load_error(self, player: str, exc: Exception) -> None:
        for var in self._skill_value_vars.values():
            var.set("?")
        msg = f"Failed to load {player}: {exc}"
        self._log(msg, level="error")
        if isinstance(exc, SheetsError):
            messagebox.showerror("Google Sheets error", str(exc))
        else:
            messagebox.showerror("Error", msg)
        self._set_busy(False)

    def _on_apply(self) -> None:
        if self._busy:
            return
        player = self._selected_player()
        skill = self.skill_var.get().strip()
        try:
            delta = int(self.delta_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid input", "Δ must be an integer.")
            return

        if not player:
            messagebox.showerror("Missing input", "Select a player.")
            return
        if not skill:
            messagebox.showerror("Missing input", "Select a skill.")
            return
        if delta == 0:
            messagebox.showerror("Invalid input", "Δ must be non-zero.")
            return

        self._set_busy(True)
        self._log(f"Applying {delta:+d} {skill} for {player}…")
        self._worker.submit(
            work=lambda: self.service.apply_increment(player, skill, delta),
            on_success=self._on_apply_success,
            on_error=lambda exc: self._on_apply_error(player, skill, delta, exc),
        )

    def _on_apply_success(self, result: IncrementResult) -> None:
        var = self._skill_value_vars.get(result.skill)
        if var is not None:
            var.set(str(result.new_value))

        if self.demo_mode:
            self._log(
                f"[demo] would update {result.player} {result.cell} "
                f"({result.skill}): {result.old_value} -> {result.new_value} "
                f"({result.delta:+d})."
            )
            self._log(f'[demo] would post to Discord: "{result.message}"')
        else:
            self._log(
                f"Updated sheet: {result.player} {result.skill} "
                f"({result.cell}) {result.old_value} -> {result.new_value} "
                f"({result.delta:+d})."
            )
            if result.discord_sent:
                self._log(f'Posted to Discord: "{result.message}"')
            else:
                self._log(
                    f"Sheet updated, but Discord post failed: {result.discord_error}",
                    level="error",
                )
                messagebox.showwarning(
                    "Discord delivery failed",
                    "The sheet was updated, but the Discord notification failed:\n\n"
                    f"{result.discord_error}",
                )
        self._set_busy(False)

    def _on_apply_error(
        self, player: str, skill: str, delta: int, exc: Exception
    ) -> None:
        msg = f"Failed to apply {delta:+d} {skill} for {player}: {exc}"
        self._log(msg, level="error")
        messagebox.showerror("Update failed", str(exc))
        self._set_busy(False)

    def _on_hat_roll(self) -> None:
        # Rolling is purely local (RNG + string format) so we keep it on
        # the Tk main thread; no worker needed.
        player = self._selected_player()
        if not player:
            messagebox.showerror("Missing input", "Select a player.")
            return

        command = self.hat_var.get()
        if not command.strip():
            messagebox.showerror(
                "Missing input",
                "Enter a hat command, e.g. `52`, `3 33`, `hit`, or `3 hit`.",
            )
            return

        try:
            result: HatRollResult = self.service.execute_hat(player, command)
        except HatCommandError as exc:
            self._log(f"/hat parse error: {exc}", level="error")
            messagebox.showerror("Invalid /hat command", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors
            log.exception("Unexpected hat error")
            self._log(f"/hat failed: {exc}", level="error")
            messagebox.showerror("Roll failed", str(exc))
            return

        # Render the multi-line message verbatim into the activity log.
        for line in result.message.splitlines():
            self._log(line)
        self.hat_entry.selection_range(0, "end")
        self.hat_entry.focus_set()

    # ---- helpers -----------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.apply_btn, self.refresh_btn):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

    def _log(self, message: str, *, level: str = "info") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = "!" if level == "error" else " "
        line = f"[{ts}] {prefix} {message}\n"
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", line)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _on_close(self) -> None:
        self._worker.stop()
        self.root.destroy()

    # ---- public ------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()


def run_app(service: AppService, *, demo_mode: bool = False) -> None:
    ControlPanel(service, demo_mode=demo_mode).run()
