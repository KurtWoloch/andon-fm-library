# -*- coding: utf-8 -*-
r"""
================================================================================
ANDON FM / BACKLINK BROADCAST - ANALYSE-GUI (Tkinter)
================================================================================
Zentrale Steueroberflaeche fuer die 6 Analyse-Skripte.

Aufruf:
    py andon_tools_gui.py

Das Tkinter-Fenster bleibt offen. Der Live-Output der gestarteten Skripte
erscheint zeilenweise sofort im Konsolenfenster darunter (bzw. im
Startfenster der Batchdatei).

Skripte:
    1. analyze_schedule_matrix.py   (10-Parameter-Programmanalyse)
    2. evaluate_show_playlist.py    (Einzeltitel-Bewertung)
    3. andon_context_analysis.py    (HOT/ARCHIVE/NEW Context-Fenster)
    4. simulate_fit_schedule.py     (Mehrtaegige Rotations-Simulation)
    5. suggest_show_wishes.py       (Wunschtitel-Generator)
    6. bb_fit_db.py                 (Fit-Datenbank sync/stats/playlist)
================================================================================
"""

import os
import re
import sys
import queue
import subprocess
import threading
from tkinter import Tk, StringVar, BooleanVar, TkVersion
import tkinter as tk
from tkinter import ttk, messagebox

# ----------------------------------------------------------------------------
# Pfade
# ----------------------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RF_DIR = r"C:\Users\kurt_\Betrieb\Radio Fernsehen"

# UTF-8 fuer eigenes stdout (Umlaute in GUI-Log), nur wenn moeglich
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ----------------------------------------------------------------------------
# Tooltip
# ----------------------------------------------------------------------------
class ToolTip:
    """Einfacher Hover-Tooltip fuer beliebige Widgets."""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text or ""
        self.delay = delay
        self._after_id = None
        self._tip = None
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")
        except Exception:
            pass

    def _schedule(self, _event=None):
        self._cancel()
        if self.text:
            self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 18
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry("+%d+%d" % (x, y))
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        frame = tk.Frame(tip, background="#ffffe0", borderwidth=1,
                         relief="solid")
        frame.pack()
        lbl = tk.Label(frame, text=self.text, justify="left", background="#ffffe0",
                       foreground="#222222", wraplength=460,
                       font=("Segoe UI", 9), padx=6, pady=4)
        lbl.pack()
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


# ----------------------------------------------------------------------------
# Parameter-Definitionen
# ----------------------------------------------------------------------------
# kind:
#   "int"    -> ganzzahliges Eingabefeld
#   "float"  -> Dezimalzahl
#   "text"   -> freier Text
#   "time"   -> HH:MM
#   "datetime" -> "YYYY-MM-DD HH:MM"
#   "station" -> Stationsname (Combobox mit Vorschlaegen)
#   "slot"   -> Uhrzeit-Slot "18:00" oder Sendungsname
#   "flag"   -> kein Eingabefeld
#
# flag: exakter CLI-Schalter (None = positionales Argument)
# optional_value: True -> "flag [value]" (Wert darf leer bleiben)

SCRIPTS = [
    {
        "file": "analyze_schedule_matrix.py",
        "title": "1. analyze_schedule_matrix.py",
        "short": "Sendeplan- & Programm-Analyse (10-Parameter-Matrix)",
        "desc": (
            "Wertet abgeschlossene Sendestunden rueckblickend anhand von Sendeplan, "
            "Musik-Log, Hoererzahlen und Archiv (bb_only.json) per Gemini aus.\n\n"
            "Aufruf: py analyze_schedule_matrix.py [--hours N] [--limit M] [--force] "
            "[--summary-only]\n"
            "Ergebnis bleibt inkrementell in der Programmanalyse-CSV erhalten "
            "(Merge nach Startzeit)."
        ),
        "params": [
            {
                "key": "hours", "label": "hours", "flag": "--hours", "kind": "int",
                "required": True, "default": "24",
                "help": "Prueft die abgeschlossenen Sendungen der letzten N Stunden "
                        "(Default ohne Flag: 24) und fuegt neue Stunden hinzu.",
            },
            {
                "key": "limit", "label": "limit", "flag": "--limit", "kind": "int",
                "required": True, "default": "3",
                "help": "Berechnet maximal M noch fehlende Sendungen aus dem "
                        "N-Stunden-Fenster.",
            },
            {
                "key": "force", "label": "force", "flag": "--force", "kind": "flag",
                "help": "Berechnet die Sendungen im angegebenen Zeitfenster neu und "
                        "ueberschreibt diese in der Tabelle.",
            },
            {
                "key": "summary_only", "label": "summary-only", "flag": "--summary-only",
                "kind": "flag",
                "help": "Berechnet nur die Top-3-Mutations- und Archivausbau-Rangliste "
                        "aus der bestehenden CSV ohne neue LLM-Calls.",
            },
        ],
        "files": [
            ("Programmanalyse (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_Programmanalyse.csv")),
            ("Programmanalyse (MD)", os.path.join(RF_DIR, "Backlink_Broadcast_Programmanalyse.md")),
        ],
    },
    {
        "file": "evaluate_show_playlist.py",
        "title": "2. evaluate_show_playlist.py",
        "short": "Einzeltitel-Bewertung gelaufener Sendungen (Playlist-Fit)",
        "desc": (
            "Bewertet jeden einzelnen gespielten Titel abgeschlossener Sendestunden "
            "(Note 1-10) gegen das Sendungskonzept und verknuepft das mit den "
            "Rotationsdaten (variabler, sendeplatzabhaengiger Cooldown).\n\n"
            "Aufruf: py evaluate_show_playlist.py [--hours N] [--at 'YYYY-MM-DD HH:MM'] "
            "[--force]"
        ),
        "params": [
            {
                "key": "hours", "label": "hours", "flag": "--hours", "kind": "int",
                "required": True, "default": "1",
                "help": "Bewertet alle abgeschlossenen Sendestunden der letzten N "
                        "Stunden (Default ohne Flag: 1).",
            },
            {
                "key": "at", "label": "at", "flag": "--at", "kind": "datetime",
                "required": True, "default": "", "placeholder": "2026-10-24 18:00",
                "help": "Bewertet gezielt eine bestimmte Sendestunde "
                        "(Format YYYY-MM-DD HH:MM).",
            },
            {
                "key": "force", "label": "force", "flag": "--force", "kind": "flag",
                "help": "Berechnet die angeforderten Stunden neu und aktualisiert sie "
                        "in CSV, MD und Datenbank.",
            },
        ],
        "files": [
            ("Titelbewertung (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_Titelbewertung.csv")),
            ("Titelbewertung (MD)", os.path.join(RF_DIR, "Backlink_Broadcast_Titelbewertung.md")),
        ],
    },
    {
        "file": "andon_context_analysis.py",
        "title": "3. andon_context_analysis.py",
        "short": "HOT / ARCHIVE / NEW - Context-Window-Analyse",
        "desc": (
            "Klassifiziert alle Plays eines Zeitfensters nach Frische:\n"
            "  HOT     = zuletzt vor <24h gespielt (noch in Rotation)\n"
            "  ARCHIVE = zuletzt vor >24h gespielt (Backkatalog)\n"
            "  NEW     = auf dieser Station noch nie gespielt\n\n"
            "Aufruf (rein positional): py andon_context_analysis.py [station_name] [hours]\n"
            "Ohne Station werden alle Stationen ausgewertet; ohne hours gilt 24."
        ),
        "params": [
            {
                "key": "station", "label": "station", "flag": None, "kind": "station",
                "required": True, "default": "Backlink Broadcast",
                "choices": ["Backlink Broadcast", "Thinking Frequencies",
                            "OpenAIR", "Grok-n-Roll"],
                "help": "Filtert die Context-Window-Analyse auf eine bestimmte Station. "
                        "Leer lassen, um alle Stationen auszuwerten.",
            },
            {
                "key": "hours", "label": "hours", "flag": None, "kind": "int",
                "required": True, "default": "24",
                "help": "Zeitfenster in Stunden fuer die HOT/ARCHIVE/NEW-Analyse "
                        "(Default: 24). Wird als zweites positionsales Argument "
                        "uebergeben.",
            },
        ],
        "files": [
            ("Andon FM Musik-Log", os.path.join(RF_DIR, "Andon FM Station logs.txt.music.txt")),
        ],
    },
    {
        "file": "simulate_fit_schedule.py",
        "title": "4. simulate_fit_schedule.py",
        "short": "Mehrtaegige Rotations- & Playlist-Simulation",
        "desc": (
            "Simuliert den Sendebetrieb ueber N Stunden auf Basis der Fit-DB und des "
            "24h-Sendeplans. Pro Stunde werden die 12 Titel mit dem hoechsten "
            "Quotienten (Stunden ungespielt / Cooldown) gewaehlt.\n\n"
            "Aufruf: py simulate_fit_schedule.py [--hours N] [--days D] "
            "[--start 'YYYY-MM-DD HH:MM'] [--min-fit F]\n"
            "Default: 72 Stunden (3 Tage)."
        ),
        "params": [
            {
                "key": "hours", "label": "hours", "flag": "--hours", "kind": "int",
                "required": True, "default": "72",
                "help": "Simuliert N aufeinanderfolgende Sendestunden "
                        "(Default: 72 Stunden = 3 Tage).",
            },
            {
                "key": "days", "label": "days", "flag": "--days", "kind": "int",
                "required": True, "default": "3",
                "help": "Simuliert D volle Tage (D * 24 Stunden). Ueberschreibt --hours, "
                        "wenn beide gesetzt sind.",
            },
            {
                "key": "start", "label": "start", "flag": "--start", "kind": "datetime",
                "required": True, "default": "", "placeholder": "2026-10-24 10:00",
                "help": "Startzeitpunkt der Simulation (Format YYYY-MM-DD HH:MM; "
                        "Default: naechste volle Stunde).",
            },
            {
                "key": "min_fit", "label": "min-fit", "flag": "--min-fit", "kind": "float",
                "required": True, "default": "1.0",
                "help": "Optionaler Mindest-Fit-Score (1-10) fuer zugelassene "
                        "Simulations-Kandidaten (Default: 1.0).",
            },
        ],
        "files": [
            ("Simulation (MD)", os.path.join(RF_DIR, "Backlink_Broadcast_Simulation.md")),
            ("Simulation (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_Simulation.csv")),
            ("Arbeitskopie (JSON)", os.path.join(RF_DIR, "sim_fit_working_state.json")),
        ],
    },
    {
        "file": "suggest_show_wishes.py",
        "title": "5. suggest_show_wishes.py",
        "short": "Intelligenter Wunschtitel-Generator",
        "desc": (
            "Generiert Wunschtitel fuer die aktuelle (oder eine per Sendeplatz-Uhrzeit / "
            "Namen angegebene) Sendung - wahlweise orientiert an den zuletzt gespielten Titeln.\n\n"
            "Aufruf: py suggest_show_wishes.py [--slot HH:MM] [--recent [N]] [--since HH:MM] "
            "[SHOW_NAME] [SHOW_DESC]"
        ),
        "params": [
            {
                "key": "slot", "label": "slot (Uhrzeit)", "flag": "--slot", "kind": "time",
                "required": True, "default": "16:00", "placeholder": "HH:MM (z.B. 16:00)",
                "help": "Sucht automatisch die Sendung und Beschreibung zur angegebenen "
                        "Sendeplatz-Uhrzeit (z.B. 16:00 oder 18:00) heraus.",
            },
            {
                "key": "recent", "label": "recent", "flag": "--recent", "kind": "int",
                "required": False, "optional_value": True, "default": "",
                "placeholder": "leer = Auto",
                "help": "Orientiert Wunschtitel an den letzten N gespielten Titeln "
                        "(leer = Auto-Erkennung seit letzter Pause).",
            },
            {
                "key": "since", "label": "since", "flag": "--since", "kind": "time",
                "required": True, "default": "12:00", "placeholder": "HH:MM",
                "help": "Orientiert Wunschtitel an allen Titeln, die seit HH:MM Uhr "
                        "gelaufen sind.",
            },
            {
                "key": "show_name", "label": "show_name", "flag": None, "kind": "text",
                "required": True, "default": "",
                "help": "Manueller Sendungsname (positionsales Argument 1). Wenn nicht "
                        "gesetzt, wird automatisch die aktuelle Live-Sendung aus dem "
                        "Log gelesen.",
            },
            {
                "key": "show_desc", "label": "show_desc", "flag": None, "kind": "text",
                "required": True, "default": "",
                "help": "Manuelle Sendungsbeschreibung (positionsales Argument 2) - "
                        "nur zusammen mit show_name sinnvoll.",
            },
        ],
        "files": [
            ("DB-Fit-Matrix (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_DB_Fit_Matrix.csv")),
            ("Repertoire-Zuordnung (MD)", os.path.join(RF_DIR, "Backlink_Broadcast_Repertoire_Zuordnung.md")),
        ],
    },
    {
        "file": "bb_fit_db.py",
        "title": "6. bb_fit_db.py",
        "short": "3-Tabellen-Fit-Datenbank (sync / stats / playlist)",
        "desc": (
            "Verwaltet die SQLite-Fit-Datenbank (Shows, Tracks, track_show_fit) und "
            "spiegelt sie in CSV. Generiert Datenbank-Playlists nach Kurts "
            "Quotienten-Formel (Zeit ungespielt / Cooldown).\n\n"
            "Aufruf: py bb_fit_db.py [--sync] [--stats] [--playlist Q] [--at 'J-M-T H:M'] "
            "[--top N]\n"
            "Ohne Argumente laeuft automatisch der Sync."
        ),
        "params": [
            {
                "key": "sync", "label": "sync", "flag": "--sync", "kind": "flag",
                "group": "mode", "default_group": True,
                "help": "Synchronisiert alle 910 Archivtitel mit dem Live-Log und "
                        "gleicht die Einzelwertungen aus Titelbewertung.csv ab.",
            },
            {
                "key": "stats", "label": "stats", "flag": "--stats", "kind": "flag",
                "group": "mode",
                "help": "Zeigt den aktuellen Fuellstand der Fit-Datenbank fuer alle "
                        "Sendungen.",
            },
            {
                "key": "playlist", "label": "playlist", "flag": "--playlist",
                "kind": "slot", "group": "mode", "required": True, "default": "18:00",
                "placeholder": "18:00 oder Sendungsname",
                "help": "Berechnet aus der Datenbank nach Kurts Quotienten-Formel "
                        "(Zeit ungespielt / Cooldown) die optimale Playlist fuer "
                        "diese Sendung.",
            },
            {
                "key": "at", "label": "at", "flag": "--at", "kind": "datetime",
                "required": True, "default": "", "placeholder": "2026-10-24 18:00",
                "help": "Historischer Referenzzeitpunkt fuer die Playlist-Berechnung "
                        "(ignoriert spaetere Plays im Log). Zusatz zu playlist.",
            },
            {
                "key": "top", "label": "top", "flag": "--top", "kind": "int",
                "required": True, "default": "12",
                "help": "Anzahl der auszugebenden Top-Titel (Default: 12). "
                        "Zusatz zu playlist.",
            },
        ],
        "files": [
            ("DB Sendungen (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_DB_Sendungen.csv")),
            ("DB Titel (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_DB_Titel.csv")),
            ("DB Fit-Matrix (CSV)", os.path.join(RF_DIR, "Backlink_Broadcast_DB_Fit_Matrix.csv")),
        ],
    },
]


# ----------------------------------------------------------------------------
# Validierung
# ----------------------------------------------------------------------------
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def validate_value(kind, value):
    """Gibt (ok, fehlertext) fuer einen Eingabewert zurueck."""
    v = (value or "").strip()
    if kind in ("int", "float", "datetime", "time"):
        if not v:
            return False, "Dieses Feld darf nicht leer sein."
    if kind == "int":
        if not re.fullmatch(r"[+-]?\d+", v):
            return False, "Bitte eine ganze Zahl eingeben (z.B. 24)."
        try:
            int(v)
        except Exception:
            return False, "Die Zahl ist zu gross."
    elif kind == "float":
        try:
            float(v.replace(",", "."))
        except Exception:
            return False, "Bitte eine Dezimalzahl eingeben (z.B. 1.0)."
    elif kind == "datetime":
        if not DT_RE.match(v):
            return False, "Format: YYYY-MM-DD HH:MM (z.B. 2026-10-24 18:00)."
        else:
            import datetime as _dt
            try:
                _dt.datetime.strptime(v, "%Y-%m-%d %H:%M")
            except Exception:
                return False, "Dieses Datum/Zeit existiert nicht " \
                              "(Format YYYY-MM-DD HH:MM)."
    elif kind == "time":
        if not TIME_RE.match(v):
            return False, "Format: HH:MM (z.B. 18:00)."
        hh, mm = v.split(":")
        try:
            h, m = int(hh), int(mm)
        except Exception:
            return False, "Format: HH:MM (z.B. 18:00)."
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return False, "Ungueltige Uhrzeit (0-23 : 0-59)."
    return True, ""


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
def _cmdline_quote(s):
    """Quoting fuer die WINDOWS-Kommandozeile (subprocess.list2cmdline).

    Notwendig, weil einige Skripte sys.argv[1] direkt als Stationsnamen nutzen
    und Namen wie 'Thinking Frequencies' sonst in zwei Argumente zerfallen.
    Einzelne Argumente ohne Leerzeichen bleiben unveraendert.
    """
    if s == "" or re.search(r'\s', s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


class AndonToolsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Andon FM / Backlink Broadcast - Analyse-GUI")
        self.root.geometry("1000x780")
        self.root.minsize(860, 660)

        self.rows = []            # Liste der Parameter-Widgets
        self.script_index = 0
        self.proc = None
        self.running = False
        # Thread-sichere Uebergabe vom Worker-Thread an den GUI-Thread
        self._done_q = queue.Queue()

        self.script_var = StringVar(value=SCRIPTS[0]["title"])
        self.radio_var = tk.IntVar(value=0)
        self.cmd_var = StringVar(value="")
        self.status_var = StringVar(value="Bereit.")
        self.status_color = "#138a13"

        self._build_ui()
        self._load_script(0)
        self._poll_finished()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ Aufbau
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        # ---- Kopf: Skript-Auswahl -------------------------------------------
        head = ttk.LabelFrame(outer, text="Skript auswaehlen", padding=8)
        head.pack(fill="x")

        ttk.Label(head, text="Analyse-Skript:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.combo = ttk.Combobox(
            head, textvariable=self.script_var, state="readonly", width=54,
            values=[s["title"] for s in SCRIPTS])
        self.combo.grid(row=0, column=1, sticky="w")
        self.combo.bind("<<ComboboxSelected>>", self._on_combo)

        self.radio_frame = ttk.Frame(head)
        self.radio_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for i, s in enumerate(SCRIPTS):
            rb_label = s.get("file", s["title"]).replace(".py", "").replace("_", " ")
            rb = ttk.Radiobutton(self.radio_frame, text=rb_label, value=i,
                                 variable=self.radio_var,
                                 command=lambda ix=i: self._select_index(ix))
            rb.pack(side="left", padx=(0, 12))
            ToolTip(rb, s["short"])

        self.short_lbl = ttk.Label(head, text="", font=("Segoe UI", 9, "italic"),
                                   foreground="#2a5b91")
        self.short_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.desc_lbl = tk.Message(head, text="", width=900, justify="left",
                                    font=("Segoe UI", 9), foreground="#333333")
        self.desc_lbl.grid(row=3, column=0, columnspan=2, sticky="we", pady=(4, 0))
        head.columnconfigure(1, weight=1)

        # ---- Parameter ------------------------------------------------------
        pbox = ttk.LabelFrame(outer, text="Parameter (aktivieren = an das Skript uebergeben)", padding=8)
        pbox.pack(fill="both", expand=True, pady=(10, 0))

        self.canvas = tk.Canvas(pbox, borderwidth=0, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(pbox, orient="vertical", command=self.canvas.yview)
        self.params_frame = ttk.Frame(self.canvas)
        self.params_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.params_frame,
                                                       anchor="nw")
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ---- Kommando-Vorschau + Start --------------------------------------
        runbox = ttk.LabelFrame(outer, text="Ausfuehren", padding=8)
        runbox.pack(fill="x", pady=(10, 0))

        ttk.Label(runbox, text="Kommandozeile:").grid(row=0, column=0, sticky="w")
        self.cmd_entry = tk.Entry(runbox, textvariable=self.cmd_var, state="readonly",
                                   font=("Consolas", 10), readonlybackground="#f4f4f4")
        self.cmd_entry.grid(row=0, column=1, sticky="we", padx=(8, 0))
        runbox.columnconfigure(1, weight=1)

        btns = ttk.Frame(runbox)
        btns.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))

        self.btn_run = ttk.Button(btns, text="\u25B6  Skript ausfuehren",
                                   command=self._run, width=26)
        self.btn_run.pack(side="left")

        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=130)
        self.progress.pack(side="left", padx=(12, 0))

        self.status_lbl = tk.Label(btns, textvariable=self.status_var,
                                    font=("Segoe UI", 9, "bold"),
                                    foreground=self.status_color)
        self.status_lbl.pack(side="left", padx=(12, 0))

        ttk.Button(btns, text="Felder zuruecksetzen", command=self._reset_fields,
                   width=20).pack(side="right")

        # ---- Ausgabedateien -------------------------------------------------
        self.files_box = ttk.LabelFrame(outer, text="Ausgabedateien (klicken zum Oeffnen)",
                                        padding=8)
        self.files_box.pack(fill="x", pady=(10, 0))
        self.files_inner = ttk.Frame(self.files_box)
        self.files_inner.pack(fill="x", anchor="w")

    # ------------------------------------------------------------ Skriptwechsel
    def _on_combo(self, _event=None):
        idx = self.combo.current()
        if idx >= 0:
            self._select_index(idx)

    def _select_index(self, idx):
        if self.running:
            self.script_var.set(SCRIPTS[self.script_index]["title"])
            self.radio_var.set(self.script_index)
            messagebox.showwarning(
                "Skript laeuft",
                "Bitte warten, bis das laufende Skript beendet ist.")
            return
        self._load_script(idx)

    def _on_canvas_resize(self, event):
        try:
            self.canvas.itemconfigure(self.canvas_window, width=event.width)
        except Exception:
            pass

    def _on_mousewheel(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            widget = None
        if widget is None:
            return
        # Nur scrollen, wenn der Zeiger ueber der Parameter-Flaeche steht
        w = widget
        while w is not None:
            if w is self.canvas:
                try:
                    self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except Exception:
                    pass
                return
            w = getattr(w, "master", None)

    def _load_script(self, idx):
        self.script_index = idx
        script = SCRIPTS[idx]
        self.script_var.set(script["title"])
        self.radio_var.set(idx)
        self.short_lbl.configure(text=script["short"])
        self.desc_lbl.configure(text=script["desc"])

        for child in self.params_frame.winfo_children():
            child.destroy()
        for child in self.files_inner.winfo_children():
            child.destroy()
        self.rows = []
        self.group_vars = {}

        # Parameter-Zeilen
        for r, p in enumerate(script["params"]):
            row = ttk.Frame(self.params_frame)
            row.pack(fill="x", anchor="w", pady=3)

            group_name = p.get("group")
            if group_name:
                if group_name not in self.group_vars:
                    # Default value is the key with default_group=True, or the first key in the group
                    default_val = p["key"]
                    for param_item in script["params"]:
                        if param_item.get("group") == group_name and param_item.get("default_group"):
                            default_val = param_item["key"]
                            break
                    self.group_vars[group_name] = StringVar(value=default_val)
                    self.group_vars[group_name].trace_add("write", lambda *_a, g=group_name: self._on_group_changed(g))

                cb_var = self.group_vars[group_name]
                cb = ttk.Radiobutton(row, text=p["label"], variable=cb_var,
                                     value=p["key"], width=20,
                                     command=lambda g=group_name: self._on_group_changed(g))
            else:
                cb_var = BooleanVar(value=False)
                cb = ttk.Checkbutton(row, text=p["label"], variable=cb_var,
                                      width=20)
            cb.grid(row=0, column=0, sticky="w")

            entry = None
            entry_var = None
            hint = None
            if p["kind"] != "flag":
                entry_var = StringVar(value=p.get("default", ""))
                if p["kind"] == "station":
                    entry = ttk.Combobox(row, textvariable=entry_var, width=34,
                                          values=p.get("choices", []))
                else:
                    entry = ttk.Entry(row, textvariable=entry_var, width=36)
                entry.grid(row=0, column=1, sticky="w", padx=(6, 6))

                # Vorbelegung setzen (falls Default vorhanden)
                first_hint = p.get("placeholder") or self._hint_for(p["kind"])
                hint = ttk.Label(row, text=first_hint, foreground="#888888",
                                  font=("Segoe UI", 8))
                hint.grid(row=0, column=2, sticky="w")
            else:
                hint = ttk.Label(row, text="(Schalter, kein Wert)", foreground="#888888",
                                  font=("Segoe UI", 8))
                hint.grid(row=0, column=1, sticky="w", padx=(6, 6))

            tip_text = p["help"]
            ToolTip(cb, tip_text)
            if entry is not None:
                ToolTip(entry, tip_text)
            if hint is not None:
                ToolTip(hint, tip_text)

            if p.get("optional_value"):
                ToolTip(cb, tip_text + "\n\nWert leer lassen = nur " + p["flag"] +
                        " (Auto-Erkennung).")

            rec = {"param": p, "cb": cb, "var": cb_var, "entry": entry,
                   "entry_var": entry_var, "hint": hint}
            cb.configure(command=lambda rec=rec: self._toggle_row(rec))
            if entry_var is not None:
                entry_var.trace_add("write", lambda *_a: self._update_cmd())
            self._toggle_row(rec)
            self.rows.append(rec)

        # Hinweis, wenn sich Parameter gegenseitig bedingen
        if idx == 2:  # andon_context_analysis
            ttk.Label(self.params_frame,
                      text="Hinweis: Der Stationsname muss das 1. Argument sein. Wenn nur "
                           "hours gewuenscht ist, bitte station aktivieren und leer lassen "
                           "-> es wird 'Alle Stationen' mit dieser Stundenzahl verwendet.",
                      wraplength=880, justify="left", foreground="#8a5a00",
                      font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 0))
        if idx == 5:  # bb_fit_db
            ttk.Label(self.params_frame,
                      text="Modus: sync, stats und playlist sind Radio-Buttons (genau ein Modus aktiv, Standard: sync). "
                           "at und top sind optionale Parameter fuer den Modus playlist.",
                      wraplength=880, justify="left", foreground="#8a5a00",
                      font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 0))
        if idx == 3:  # simulate
            ttk.Label(self.params_frame,
                      text="Hinweis: days ueberschreibt hours (der spaeter geparste "
                           "Schalter gewinnt).",
                      wraplength=880, justify="left", foreground="#8a5a00",
                      font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 0))

        # Datei-Buttons
        for label, path in script["files"]:
            b = ttk.Button(self.files_inner, text="\U0001F4C4  " + label,
                           command=lambda pth=path: self._open_file(pth))
            b.pack(side="left", padx=(0, 8), pady=2)
            exists = os.path.exists(path)
            Tip = "Oeffnen: " + path + ("" if exists else "\n\n(noch nicht vorhanden)")
            ToolTip(b, Tip)

        self.canvas.yview_moveto(0)
        for g in self.group_vars:
            self._on_group_changed(g)
        self._update_cmd()

    @staticmethod
    def _hint_for(kind):
        return {
            "int": "ganze Zahl",
            "float": "Dezimalzahl",
            "text": "Text",
            "time": "HH:MM",
            "datetime": "YYYY-MM-DD HH:MM",
            "station": "Station waehlen",
            "slot": "Uhrzeit oder Sendung",
        }.get(kind, "")

    def _is_active(self, rec):
        group_name = rec["param"].get("group")
        if group_name:
            return rec["var"].get() == rec["param"]["key"]
        return bool(rec["var"].get())

    def _on_group_changed(self, group_name):
        for rec in self.rows:
            if rec["param"].get("group") == group_name:
                self._toggle_row(rec, update_cmd=False)
        # Fuer bb_fit_db: at und top nur aktivieren, wenn playlist gewaehlt ist
        if self.script_index == 5:
            is_playlist = (self.group_vars.get("mode") and self.group_vars["mode"].get() == "playlist")
            for rec in self.rows:
                if rec["param"]["key"] in ("at", "top"):
                    if is_playlist:
                        rec["cb"].configure(state="normal")
                    else:
                        rec["var"].set(False)
                        rec["cb"].configure(state="disabled")
                    self._toggle_row(rec, update_cmd=False)
        self._update_cmd()

    def _toggle_row(self, rec, update_cmd=True):
        """Eingabefeld erst beim Aktivieren einblenden."""
        active = self._is_active(rec)
        p = rec["param"]
        if rec["entry"] is not None:
            if active:
                rec["entry"].configure(state="normal")
                try:
                    rec["entry"].focus_set()
                    rec["entry"].selection_range(0, "end")
                except Exception:
                    pass
            else:
                rec["entry"].configure(state="disabled")
        if update_cmd:
            self._update_cmd()

    def _reset_fields(self):
        script = SCRIPTS[self.script_index]
        for g_name, g_var in self.group_vars.items():
            for p in script["params"]:
                if p.get("group") == g_name and p.get("default_group"):
                    g_var.set(p["key"])
                    break
        for rec, p in zip(self.rows, script["params"]):
            if not p.get("group"):
                rec["var"].set(False)
            if rec["entry_var"] is not None:
                rec["entry_var"].set(p.get("default", ""))
            self._toggle_row(rec, update_cmd=False)
        self._update_cmd()
        self.status_var.set("Felder zurueckgesetzt.")
        self.status_color = "#138a13"
        self.status_lbl.configure(foreground=self.status_color)

    # ------------------------------------------------------------ Kommando bauen
    def _collect(self):
        """Baut die Argumentliste. Rueckgabe: (args, fehlerliste)."""
        script = SCRIPTS[self.script_index]
        args = []
        errors = []
        for rec in self.rows:
            p = rec["param"]
            if not self._is_active(rec):
                continue
            kind = p["kind"]
            flag = p["flag"]

            if kind == "flag":
                args.append(flag)
                continue

            val = (rec["entry_var"].get() or "").strip()

            # Sonderfall: optionaler Wert (--recent [N])
            if p.get("optional_value"):
                if val:
                    ok, msg = validate_value(kind, val)
                    if not ok:
                        errors.append(p["label"] + ": " + msg)
                        continue
                    args.extend([flag, val])
                else:
                    args.append(flag)
                continue

            ok, msg = validate_value(kind, val)
            if not ok:
                errors.append(p["label"] + ": " + msg)
                continue

            if flag:
                args.extend([flag, val])
            else:
                args.append(val)
        return args, errors

    def _update_cmd(self):
        args, _errors = self._collect()
        parts = ["py", SCRIPTS[self.script_index]["file"]] + args
        self.cmd_var.set(" ".join(_cmdline_quote(a) for a in parts))
        self.root.after_idle(lambda: self.cmd_entry.xview_moveto(1.0))

    @staticmethod
    def _quote(s):
        return _cmdline_quote(s)

    # ------------------------------------------------------------------ Ausfuehren
    def _run(self):
        if self.running:
            messagebox.showinfo("Laeuft bereits",
                                "Es laeuft gerade ein Skript. Bitte abwarten.")
            return

        script = SCRIPTS[self.script_index]
        args, errors = self._collect()

        # Zusatzpruefungen
        active = {rec["param"]["key"]: rec for rec in self.rows if self._is_active(rec)}

        if self.script_index == 2:  # andon_context_analysis
            # hours ist das 2. positionsale Argument -> station-Position ggf. leer
            if "hours" in active and "station" not in active:
                args = [""] + args
                print("Hinweis: 'hours' ohne Station -> alle Stationen werden "
                      "ausgewertet.")
        if self.script_index == 4:  # suggest_show_wishes
            if "show_desc" in active and "show_name" not in active:
                errors.append("'show_desc' braucht 'show_name' (2. positionsales "
                              "Argument ohne 1. ist nicht moeglich).")
            if "recent" in active and "since" in active:
                errors.append("'recent' und 'since' schliessen sich aus - bitte nur "
                              "eines waehlen.")
        if self.script_index == 5:  # bb_fit_db
            if "at" in active and "playlist" not in active:
                errors.append("'at' wirkt nur zusammen mit 'playlist'.")
            if "top" in active and "playlist" not in active:
                errors.append("'top' wirkt nur zusammen mit 'playlist'.")
            modes = [k for k in ("sync", "stats", "playlist") if k in active]
            if len(modes) > 1:
                errors.append("sync / stats / playlist sind eigenstaendige Modi - "
                              "bitte nur einen auswaehlen (sonst laeuft nur der erste).")
            if not modes:
                errors.append("bb_fit_db.py braucht einen Modus: sync, stats oder "
                              "playlist.")
        if self.script_index == 3:  # simulate
            if "hours" in active and "days" in active:
                if not messagebox.askyesno(
                        "hours und days gesetzt",
                        "Es sind sowohl hours als auch days aktiv. Der Schalter days "
                        "ueberschreibt hours (days * 24).\n\nTrotzdem starten?"):
                    return

        if errors:
            messagebox.showerror("Ungueltige Eingabe", "\n\n".join(errors))
            return

        script_path = os.path.join(SCRIPTS_DIR, script["file"])
        if not os.path.exists(script_path):
            messagebox.showerror("Skript fehlt",
                                 "Datei nicht gefunden:\n" + script_path)
            return

        cmd = ["py", "-u", script_path] + args
        cmdline = " ".join(_cmdline_quote(c) for c in cmd)

        # Kommando im Konsolenfenster sichtbar machen
        print("\n" + "=" * 78)
        print("START: " + cmdline)
        print("=" * 78)
        try:
            sys.stdout.flush()
        except Exception:
            pass

        try:
            self.proc = subprocess.Popen(cmdline, cwd=SCRIPTS_DIR)
        except Exception as exc:
            messagebox.showerror("Start fehlgeschlagen",
                                 "Das Skript konnte nicht gestartet werden:\n\n" + str(exc))
            return

        self.running = True
        self.btn_run.configure(state="disabled")
        self.combo.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Laeuft: " + script["file"] + " ...")
        self.status_color = "#b06a00"
        self.status_lbl.configure(foreground=self.status_color)

        t = threading.Thread(target=self._wait_for_process,
                             args=(self.proc, script["file"]), daemon=True)
        t.start()

    def _wait_for_process(self, proc, name):
        code = proc.wait()
        # Nur in die Queue legen: Tkinter ist NICHT thread-sicher.
        # (self.root.after() aus einem Thread wirft "main thread is not in main loop")
        self._done_q.put((code, name))

    def _poll_finished(self):
        """Wird im GUI-Thread aufgerufen und uebernimmt fertige Laeufe."""
        try:
            while True:
                code, name = self._done_q.get_nowait()
                self._on_finished(code, name)
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            try:
                self.root.after(200, self._poll_finished)
            except Exception:
                pass

    def _on_finished(self, code, name):
        self.running = False
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.combo.configure(state="readonly")
        if code == 0:
            self.status_var.set("Fertig: " + name)
            self.status_color = "#138a13"
        else:
            self.status_var.set("Beendet mit Fehlercode " + str(code) + ": " + name)
            self.status_color = "#b00020"
        self.status_lbl.configure(foreground=self.status_color)
        print("=" * 78)
        print("ENDE: " + name + " (Exit-Code " + str(code) + ")")
        print("=" * 78)
        try:
            sys.stdout.flush()
        except Exception:
            pass

    # --------------------------------------------------------------- Dateien
    def _open_file(self, path):
        if not os.path.exists(path):
            messagebox.showinfo(
                "Datei noch nicht vorhanden",
                "Diese Datei existiert noch nicht:\n\n" + path +
                "\n\nBitte zuerst das zugehoerige Skript ausfuehren.")
            return
        try:
            os.startfile(path)  # noqa: S606 - Windows-spezifisch, gewuenscht
        except Exception as exc:
            messagebox.showerror("Oeffnen fehlgeschlagen",
                                 str(path) + "\n\n" + str(exc))

    # --------------------------------------------------------------- Fenster
    def _on_close(self):
        if self.running:
            if not messagebox.askyesno(
                    "Skript laeuft",
                    "Es laeuft noch ein Skript. Fenster trotzdem schliessen?\n"
                    "(Das Skript laeuft im Hintergrund weiter.)"):
                return
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.root.destroy()


def main():
    root = Tk()
    app = AndonToolsGUI(root)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
