"""
progress.py  Barre de progression console (sans dépendance, caractères compatibles
avec la console Windows) : pourcentage, temps écoulé, temps restant estimé,
débit et informations libres.
"""

from __future__ import annotations

import sys
import time


def setup_console():
    """Évite qu'un caractère non affichable par la console Windows (cp1252) ne fasse
    planter un long calcul au moment d'un print."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def fmt_duration(seconds) -> str:
    if seconds is None or seconds != seconds or seconds < 0:
        return "--:--"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


class ConsoleProgress:
    def __init__(self, total: float, label: str = "", width: int = 28, unit: str = "",
                 stream=None, min_interval: float = 0.25):
        self.total = max(float(total), 1e-9)
        self.label = label
        self.width = width
        self.unit = unit
        self.stream = stream or sys.stdout
        self.min_interval = min_interval
        self.t0 = time.time()
        self._last = 0.0
        self._last_len = 0
        self._last_pct_line = -1
        self._tty = hasattr(self.stream, "isatty") and self.stream.isatty()
        self.done = 0.0
        self._start_done = None   # avancement au premier appel (reprise d'un calcul)

    def update(self, done: float, info: str = "", label: str | None = None,
               eta: float | None = None, force: bool = False):
        self.done = done
        if label is not None:
            self.label = label
        now = time.time()
        if not force and now - self._last < self.min_interval and done < self.total:
            return
        self._last = now
        if self._start_done is None:
            self._start_done = done
            self.t0 = now
        frac = min(1.0, max(0.0, done / self.total))
        elapsed = now - self.t0
        run = done - self._start_done
        if eta is None and run > 0:
            eta = elapsed / run * (self.total - done)
        filled = int(round(frac * self.width))
        bar = "#" * filled + "-" * (self.width - filled)
        line = (f"{self.label} [{bar}] {frac * 100:5.1f}%  {fmt_duration(elapsed)} écoulé"
                f"  reste ~{fmt_duration(eta)}")
        if info:
            line += f"  | {info}"
        if self._tty:
            pad = max(0, self._last_len - len(line))
            self.stream.write("\r" + line + " " * pad)
            self._last_len = len(line)
        else:
            # Sortie redirigée (fichier, journal) : une ligne tous les 5 %
            step = int(frac * 20)
            if step == self._last_pct_line and not force:
                return
            self._last_pct_line = step
            self.stream.write(line + "\n")
        self.stream.flush()

    def close(self, message: str | None = None, complete: bool = True):
        if complete:
            self.update(self.total, force=True)
        if self._tty:
            self.stream.write("\n")
        if message:
            self.stream.write(message + "\n")
        self.stream.flush()
