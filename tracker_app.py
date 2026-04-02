#!/usr/bin/env python3
"""
CAMeSM Attendance Tracker — GUI  v0.8.0
═══════════════════════════════════════
CustomTkinter + matplotlib front-end.
Run this file to launch the application.

Author: Alex (CAMeSM Board – Workshops Coordinator)
"""

import os
import webbrowser
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.ticker as mticker
import matplotlib.dates as mdates

from tracker_core import (
    APP_TITLE, APP_VERSION, DEFAULT_THRESHOLD,
    COL_ID, COL_TIMESTAMP, COL_SESSION, COL_NAME, COL_EMAIL, COL_IP, COL_UA, COL_REG_IP,
    COL_ENTRY_ID, COL_DATE_UPDATED, COL_SOURCE_URL, COL_CREATED_BY, COL_SUBMISSION_SPEED,
    COL_PHONE, COL_YEAR, COL_UNIVERSITY,
    AttendanceStore, Schedule, ScheduledSession,
    _norm_cols, parse_device_type,
)

# ══════════════════════════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════════════════════════

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CHART_BG = "#1a1a2e"
CHART_FG = "#e0e0e0"
CHART_ACCENT = "#3b82f6"
CHART_ACCENT2 = "#10b981"
CHART_ACCENT3 = "#f59e0b"
CHART_WARN = "#ef4444"
CHART_GRID = "#2a2a4a"

plt.rcParams.update({
    "figure.facecolor": CHART_BG,
    "axes.facecolor": CHART_BG,
    "axes.edgecolor": CHART_GRID,
    "axes.labelcolor": CHART_FG,
    "text.color": CHART_FG,
    "xtick.color": CHART_FG,
    "ytick.color": CHART_FG,
    "grid.color": CHART_GRID,
    "grid.alpha": 0.4,
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
})


# ══════════════════════════════════════════════════════════════════════════════
#  APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

class TrackerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry("1300x900")
        self.minsize(1080, 720)
        self.store = AttendanceStore()
        self.threshold = DEFAULT_THRESHOLD
        self._chart_figures: list[plt.Figure] = []   # track for cleanup
        self._chart_canvases: list[FigureCanvasTkAgg] = []
        self._last_search = pd.DataFrame()
        self._tag_ctr = 0
        self._build_ui()
        self._bind_shortcuts()
        self._refresh_all()

    # ── Chart lifecycle ───────────────────────────────────────────────────
    def _close_charts(self):
        """Close all tracked matplotlib figures to prevent memory leaks."""
        for fig in self._chart_figures:
            try:
                plt.close(fig)
            except Exception:
                pass
        self._chart_figures.clear()
        self._chart_canvases.clear()

    def _embed_chart(self, parent, fig):
        """Embed a matplotlib figure into a CTk frame and track it for cleanup."""
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
        self._chart_figures.append(fig)
        self._chart_canvases.append(canvas)
        return canvas

    # ── Shortcuts ─────────────────────────────────────────────────────────
    def _bind_shortcuts(self):
        pks = list(self.nav_buttons.keys())
        for i, k in enumerate(pks[:9]):
            self.bind(f"<Command-Key-{i+1}>", lambda e, k=k: self._show_page(k))
            self.bind(f"<Control-Key-{i+1}>", lambda e, k=k: self._show_page(k))
        self.bind("<Command-f>", lambda e: (self._show_page("search"), self.search_entry.focus_set()))
        self.bind("<Control-f>", lambda e: (self._show_page("search"), self.search_entry.focus_set()))
        self.bind("<Command-r>", lambda e: self._refresh_current())
        self.bind("<Control-r>", lambda e: self._refresh_current())

    def _refresh_current(self):
        for k, f in self.pages.items():
            if f.winfo_ismapped():
                self._show_page(k)
                break

    # ── Text helpers ──────────────────────────────────────────────────────
    def _make_id_clickable(self, tb, pid):
        tag = f"p{self._tag_ctr}"
        self._tag_ctr += 1
        inner = tb._textbox if hasattr(tb, "_textbox") else tb
        inner.insert("end", pid, tag)
        inner.tag_configure(tag, foreground="#3b82f6", underline=True)
        inner.tag_bind(tag, "<Button-1>", lambda e, p=pid: self._nav_participant(p))
        inner.tag_bind(tag, "<Enter>", lambda e: inner.configure(cursor="hand2"))
        inner.tag_bind(tag, "<Leave>", lambda e: inner.configure(cursor=""))

    def _nav_participant(self, pid):
        self.part_entry.delete(0, "end")
        self.part_entry.insert(0, pid)
        self._show_page("participant")
        self._do_plookup()

    def _tw(self, tb, text):
        (tb._textbox if hasattr(tb, "_textbox") else tb).insert("end", text)

    def _tc(self, tb):
        tb.configure(state="normal")
        (tb._textbox if hasattr(tb, "_textbox") else tb).delete("1.0", "end")

    def _tl(self, tb):
        tb.configure(state="disabled")

    def _clear_frame(self, f):
        for w in f.winfo_children():
            w.destroy()

    # ══════════════════════════════════════════════════════════════════════
    #  UI LAYOUT
    # ══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        ctk.CTkLabel(self.sidebar, text="🩺 CAMeSM", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(18, 2))
        ctk.CTkLabel(self.sidebar, text="Attendance Tracker", font=ctk.CTkFont(size=13), text_color="gray").pack(pady=(0, 14))

        self.nav_buttons = {}
        nav_items = [
            ("📊  Dashboard", "dashboard"), ("📅  Schedule", "schedule"),
            ("📈  Analytics", "analytics"), ("✅  Eligibility", "eligibility"),
            ("🔍  Search", "search"), ("👤  Participant", "participant"),
            ("⚠️  Duplicates", "duplicates"), ("🔗  Unmatched", "unmatched"),
            ("🛡️  Scan Audit", "scan_audit"), ("📂  Import", "import"),
            ("📥  Exports", "exports"),
        ]
        for i, (label, key) in enumerate(nav_items):
            sc = f"  ⌘{i+1}" if i < 9 else ""
            btn = ctk.CTkButton(
                self.sidebar, text=label + sc, height=30,
                font=ctk.CTkFont(size=12), anchor="w",
                fg_color="transparent", hover_color=("gray75", "gray25"),
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=10, pady=1)
            self.nav_buttons[key] = btn

        ctk.CTkLabel(self.sidebar, text="─" * 24, text_color="gray40").pack(pady=(10, 4))
        ctk.CTkLabel(self.sidebar, text="Threshold", font=ctk.CTkFont(size=12)).pack()
        tf = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        tf.pack(pady=4)
        self.threshold_var = ctk.StringVar(value=str(self.threshold))
        ctk.CTkEntry(tf, textvariable=self.threshold_var, width=50, justify="center",
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tf, text="Set", width=50, command=self._update_thr).pack(side="left")

        self.status_lbl = ctk.CTkLabel(self.sidebar, text="No data",
                                        font=ctk.CTkFont(size=11), text_color="gray50")
        self.status_lbl.pack(side="bottom", pady=(0, 6), padx=8)
        self.sched_status = ctk.CTkLabel(self.sidebar, text="No schedule",
                                          font=ctk.CTkFont(size=10), text_color="gray40")
        self.sched_status.pack(side="bottom", pady=(0, 2))
        ctk.CTkLabel(self.sidebar, text=f"v{APP_VERSION}", text_color="gray40",
                     font=ctk.CTkFont(size=10)).pack(side="bottom", pady=(0, 2))

        # Content area
        self.content = ctk.CTkFrame(self, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)
        self.pages = {}
        for k in ["dashboard", "schedule", "analytics", "eligibility", "search",
                   "participant", "duplicates", "unmatched", "scan_audit", "import", "exports"]:
            self.pages[k] = ctk.CTkFrame(self.content, corner_radius=0, fg_color="transparent")

        self._build_dashboard()
        self._build_schedule()
        self._build_analytics()
        self._build_eligibility()
        self._build_search()
        self._build_participant()
        self._build_duplicates()
        self._build_unmatched()
        self._build_scan_audit()
        self._build_import()
        self._build_exports()
        self._show_page("dashboard")

    # ── Navigation ────────────────────────────────────────────────────────
    def _show_page(self, key):
        for f in self.pages.values():
            f.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=20, pady=14)
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=("gray75", "gray25") if k == key else "transparent")
        self._update_status()
        refs = {
            "dashboard": self._ref_dash,
            "schedule": self._ref_sched,
            "analytics": self._ref_analytics,
            "eligibility": self._ref_elig,
            "duplicates": self._ref_dupes,
            "unmatched": self._ref_unmatched,
            "scan_audit": self._ref_audit,
        }
        if key in refs:
            refs[key]()

    def _refresh_all(self):
        self._ref_dash()

    def _update_status(self):
        s = self.store
        if s.total_scans:
            ne = len(s.eligible_participants(self.threshold))
            self.status_lbl.configure(
                text=f"{s.total_scans} scans • {s.unique_participants} pax • "
                     f"{len(s.sessions)} sess • {ne} eligible"
            )
        else:
            self.status_lbl.configure(text="No data")
        if self.store.schedule:
            self.sched_status.configure(text=f"📅 {len(self.store.schedule.sessions)} sessions scheduled")
        else:
            self.sched_status.configure(text="No schedule loaded")

    def _update_thr(self):
        try:
            v = int(self.threshold_var.get())
            if v < 1:
                raise ValueError
            self.threshold = v
            self._ref_elig()
        except ValueError:
            messagebox.showwarning("Invalid", "Positive integer.")
            self.threshold_var.set(str(self.threshold))

    # ══════════════════════════════════════════════════════════════════════
    #  DASHBOARD
    # ══════════════════════════════════════════════════════════════════════
    def _build_dashboard(self):
        p = self.pages["dashboard"]
        ctk.CTkLabel(p, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 12))
        self.sf = ctk.CTkFrame(p, fg_color="transparent")
        self.sf.pack(fill="x")
        self.sc = {}
        stats = [
            ("total_scans", "Scans"), ("unique_participants", "Participants"),
            ("total_sessions", "Sessions"), ("avg_sessions", "Avg"),
            ("median_sessions", "Median"), ("max_sessions", "Max"),
        ]
        for i, (k, t) in enumerate(stats):
            card = ctk.CTkFrame(self.sf)
            card.grid(row=0, column=i, padx=4, pady=4, sticky="nsew")
            self.sf.columnconfigure(i, weight=1)
            ctk.CTkLabel(card, text=t, font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(8, 2))
            lbl = ctk.CTkLabel(card, text="–", font=ctk.CTkFont(size=24, weight="bold"))
            lbl.pack(pady=(0, 8))
            self.sc[k] = lbl
        ctk.CTkLabel(p, text="Attendance per Session",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(12, 4))
        self.dash_tb = ctk.CTkTextbox(p, height=300, font=ctk.CTkFont(family="Courier", size=13))
        self.dash_tb.pack(fill="both", expand=True)

    def _ref_dash(self):
        for k, lbl in self.sc.items():
            v = self.store.global_stats().get(k, "–")
            lbl.configure(text=str(v) if v != 0 or self.store.total_scans > 0 else "–")
        self._tc(self.dash_tb)
        if self.store.total_scans > 0:
            att = self.store.attendance_per_session()
            self._tw(self.dash_tb, f"  {'Session':<42}{'Participants':>12}\n  " + "─" * 56 + "\n")
            for s, c in att.items():
                self._tw(self.dash_tb, f"  {s:<42}{c:>12}\n")
        else:
            self._tw(self.dash_tb, "\n   No data loaded yet.")
        self._tl(self.dash_tb)

    # ══════════════════════════════════════════════════════════════════════
    #  SCHEDULE
    # ══════════════════════════════════════════════════════════════════════
    def _build_schedule(self):
        p = self.pages["schedule"]
        ctk.CTkLabel(p, text="Schedule  (⌘2)", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 4))
        self.sched_info = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=14), text_color="gray")
        self.sched_info.pack(anchor="w", pady=(0, 8))
        self.sched_scroll = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.sched_scroll.pack(fill="both", expand=True)

    def _ref_sched(self):
        self._close_charts()
        c = self.sched_scroll
        self._clear_frame(c)
        sched = self.store.schedule

        if not sched:
            self.sched_info.configure(text="No schedule loaded. Import one via the Import page (⌘10).")
            ctk.CTkLabel(c, text="Load a schedule JSON to see the timetable here.\n"
                                  "A template is included: schedule_template.json",
                         font=ctk.CTkFont(size=14), text_color="gray").pack(pady=40)
            return

        self.sched_info.configure(text=sched.conference_name)
        att = self.store.attendance_per_session()

        for day in sched.days:
            day_label = datetime.strptime(day, "%Y-%m-%d").strftime("%A, %d %B %Y")
            day_frame = ctk.CTkFrame(c)
            day_frame.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(day_frame, text=f"📅  {day_label}",
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(10, 6))

            for sess in sched.sessions_on_day(day):
                sf = ctk.CTkFrame(day_frame, fg_color=("gray85", "gray20"))
                sf.pack(fill="x", padx=10, pady=3)

                time_str = f"{sess.start} – {sess.end}"
                n_attendees = att.get(sess.name, 0) if not att.empty else 0

                left = ctk.CTkFrame(sf, fg_color="transparent", width=140)
                left.pack(side="left", padx=(10, 0), pady=8)
                left.pack_propagate(False)
                ctk.CTkLabel(left, text=time_str, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
                ctk.CTkLabel(left, text=f"{sess.duration_min} min",
                             font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")

                mid = ctk.CTkFrame(sf, fg_color="transparent")
                mid.pack(side="left", fill="x", expand=True, padx=10, pady=8)
                ctk.CTkLabel(mid, text=sess.name, font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")

                right = ctk.CTkFrame(sf, fg_color="transparent", width=100)
                right.pack(side="right", padx=(0, 10), pady=8)
                right.pack_propagate(False)
                if n_attendees > 0:
                    ctk.CTkLabel(right, text=f"{n_attendees}",
                                 font=ctk.CTkFont(size=20, weight="bold"), text_color="#10b981").pack()
                    ctk.CTkLabel(right, text="attended", font=ctk.CTkFont(size=10), text_color="gray").pack()
                else:
                    ctk.CTkLabel(right, text="—", font=ctk.CTkFont(size=18), text_color="gray40").pack()
                    ctk.CTkLabel(right, text="no scans", font=ctk.CTkFont(size=10), text_color="gray40").pack()

        # Timing chart
        if self.store.total_scans > 0 and sched:
            chart_frame = ctk.CTkFrame(c)
            chart_frame.pack(fill="x", pady=(12, 0))
            ctk.CTkLabel(chart_frame, text="⏱️ Session Timing Overview",
                         font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))

            fig, ax = plt.subplots(figsize=(10, max(3, len(sched.sessions) * 0.5)))
            recs = self.store.records.copy()
            recs["ts"] = pd.to_datetime(recs[COL_TIMESTAMP], errors="coerce")

            for i, sess in enumerate(reversed(sched.sessions)):
                ax.barh(i, sess.duration_min, left=0, color="#2a2a4a", height=0.5, edgecolor=CHART_GRID)
                s_recs = recs[recs[COL_SESSION] == sess.name].dropna(subset=["ts"])
                if not s_recs.empty:
                    offsets = [sess.arrival_offset_min(t) for t in s_recs["ts"]]
                    for off in offsets:
                        colour = CHART_ACCENT2 if 0 <= off <= sess.duration_min else CHART_WARN
                        ax.plot(off, i, '|', color=colour, markersize=12, markeredgewidth=1.5, alpha=0.7)

            ax.set_yticks(range(len(sched.sessions)))
            ax.set_yticklabels([s.name[:25] for s in reversed(sched.sessions)], fontsize=9)
            ax.set_xlabel("Minutes from Session Start")
            ax.axvline(x=0, color=CHART_ACCENT, linestyle="--", linewidth=1, alpha=0.6, label="Session Start")
            ax.set_title("Scan Timing vs Scheduled Windows")
            ax.legend(fontsize=8, facecolor=CHART_BG, edgecolor=CHART_GRID)
            ax.grid(axis="x", alpha=0.3)
            fig.tight_layout()
            self._embed_chart(chart_frame, fig)

    # ══════════════════════════════════════════════════════════════════════
    #  ANALYTICS
    # ══════════════════════════════════════════════════════════════════════
    def _build_analytics(self):
        p = self.pages["analytics"]
        ctk.CTkLabel(p, text="Visual Analytics", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 8))
        self.an_s = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.an_s.pack(fill="both", expand=True)

    def _ref_analytics(self):
        self._close_charts()
        c = self.an_s
        self._clear_frame(c)

        if self.store.total_scans == 0:
            ctk.CTkLabel(c, text="No data loaded.", font=ctk.CTkFont(size=14), text_color="gray").pack(pady=40)
            return

        att = self.store.attendance_per_session()
        counts = self.store.session_count_per_participant()

        # 1. Attendance bar chart
        f = ctk.CTkFrame(c)
        f.pack(fill="x", pady=(0, 10))
        fig, ax = plt.subplots(figsize=(10, max(3, len(att) * 0.5)))
        bars = ax.barh(att.index[::-1], att.values[::-1], color=CHART_ACCENT, height=0.6)
        ax.set_xlabel("Participants")
        ax.set_title("Attendance per Session")
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        for b, v in zip(bars, att.values[::-1]):
            ax.text(b.get_width() + 0.3, b.get_y() + b.get_height() / 2, str(v),
                    va="center", fontsize=10, color=CHART_FG)
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        self._embed_chart(f, fig)

        # 2. Session distribution
        f = ctk.CTkFrame(c)
        f.pack(fill="x", pady=(0, 10))
        fig, ax = plt.subplots(figsize=(10, 4))
        mx = int(counts.max())
        hv = [int((counts == b).sum()) for b in range(1, mx + 1)]
        cols = [CHART_ACCENT if b >= self.threshold else CHART_WARN for b in range(1, mx + 1)]
        ax.bar(range(1, mx + 1), hv, color=cols, width=0.7)
        ax.axvline(x=self.threshold - 0.5, color=CHART_ACCENT2, linestyle="--", linewidth=1.5,
                   label=f"Threshold ({self.threshold})")
        ax.set_xlabel("Sessions")
        ax.set_ylabel("Participants")
        ax.set_title("Distribution")
        ax.set_xticks(range(1, mx + 1))
        ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.legend(facecolor=CHART_BG, edgecolor=CHART_GRID)
        for i, v in enumerate(hv):
            if v > 0:
                ax.text(i + 1, v + 0.15, str(v), ha="center", fontsize=10, color=CHART_FG)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        self._embed_chart(f, fig)

        # 3. Eligibility pie + curve
        ne = len(self.store.eligible_participants(self.threshold))
        ni = len(self.store.ineligible_participants(self.threshold))
        f = ctk.CTkFrame(c)
        f.pack(fill="x", pady=(0, 10))
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.5))
        if ne + ni > 0:
            a1.pie([ne, ni], labels=[f"Eligible ({ne})", f"Not Yet ({ni})"],
                   colors=[CHART_ACCENT2, CHART_WARN], autopct="%1.0f%%", startangle=90,
                   textprops={"color": CHART_FG, "fontsize": 11},
                   wedgeprops={"edgecolor": CHART_BG, "linewidth": 2})
            a1.set_title("Eligibility")
        sc2 = counts.sort_values(ascending=False).reset_index(drop=True)
        cp = [(sc2[:i+1] >= self.threshold).sum() / len(sc2) * 100 for i in range(len(sc2))]
        a2.fill_between(range(len(cp)), cp, alpha=0.3, color=CHART_ACCENT)
        a2.plot(range(len(cp)), cp, color=CHART_ACCENT, linewidth=2)
        a2.set_xlabel("Participants")
        a2.set_ylabel("% Eligible")
        a2.set_title("Eligibility Curve")
        a2.set_ylim(0, 105)
        a2.grid(alpha=0.3)
        fig.tight_layout()
        self._embed_chart(f, fig)

        # 4. Session correlation matrix
        corr = self.store.session_correlation_matrix()
        if not corr.empty and len(corr) > 1:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            fig, ax = plt.subplots(figsize=(10, max(4, len(corr) * 0.5)))
            im = ax.imshow(corr.values, cmap="RdYlGn", vmin=-0.3, vmax=1, aspect="auto")
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.index)))
            ax.set_xticklabels([s[:18] for s in corr.columns], rotation=45, ha="right", fontsize=8)
            ax.set_yticklabels([s[:18] for s in corr.index], fontsize=8)
            for i in range(len(corr)):
                for j in range(len(corr)):
                    ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center",
                            fontsize=8, color="black" if corr.values[i, j] > 0.5 else CHART_FG)
            ax.set_title("Session Correlation")
            fig.colorbar(im, ax=ax, shrink=0.6)
            fig.tight_layout()
            self._embed_chart(f, fig)

        # 5. Dropout + closing-only
        dropout = self.store.dropout_analysis()
        closing = self.store.closing_only_attendees()
        if not dropout.empty or not closing.empty:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(f, text="📉 Dropout & Patterns",
                         font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(8, 4))
            tb = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Courier", size=12), height=200)
            tb.pack(fill="x", padx=8, pady=(0, 8))
            tb.configure(state="normal")
            if not closing.empty:
                self._tw(tb, f"  🏁 LAST-SESSION-ONLY ({len(closing)}):\n  " + "─" * 50 + "\n")
                for _, r in closing.iterrows():
                    self._tw(tb, "    ")
                    self._make_id_clickable(tb, r[COL_ID])
                    self._tw(tb, f"  {r.get('name', '')[:26]}\n")
                self._tw(tb, "\n")
            if not dropout.empty:
                self._tw(tb, f"  📉 DROPOUTS ({len(dropout)}):\n  " + "─" * 60 + "\n")
                for _, r in dropout.head(30).iterrows():
                    self._tw(tb, "  ")
                    self._make_id_clickable(tb, r[COL_ID])
                    pad = max(0, 12 - len(str(r[COL_ID])))
                    self._tw(tb, f"{'':>{pad}}{r.get('name', '')[:24]:<26} last: "
                                  f"{r['last_seen'][:22]} missed: {r['sessions_missed']}\n")
            tb.configure(state="disabled")

        # 6. Year of Studies distribution
        year_dist = self.store.year_distribution()
        if not year_dist.empty:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            fig, ax = plt.subplots(figsize=(10, 3.5))
            colours = [CHART_ACCENT, CHART_ACCENT2, CHART_ACCENT3, CHART_WARN, "#8b5cf6", "#ec4899"]
            bar_colours = [colours[i % len(colours)] for i in range(len(year_dist))]
            bars = ax.bar(range(len(year_dist)), year_dist.values, color=bar_colours, width=0.6)
            ax.set_xticks(range(len(year_dist)))
            ax.set_xticklabels(year_dist.index, fontsize=11)
            ax.set_ylabel("Participants")
            ax.set_title("Year of Studies Distribution")
            ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            for b, v in zip(bars, year_dist.values):
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.15,
                        str(v), ha="center", fontsize=11, fontweight="bold", color=CHART_FG)
            ax.grid(axis="y", alpha=0.3)
            fig.tight_layout()
            self._embed_chart(f, fig)

        # 7. University distribution
        uni_dist = self.store.university_distribution()
        if not uni_dist.empty:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            fig, ax = plt.subplots(figsize=(10, max(3, len(uni_dist) * 0.5)))
            bar_colours = [colours[i % len(colours)] for i in range(len(uni_dist))]
            bars = ax.barh(range(len(uni_dist)), uni_dist.values, color=bar_colours, height=0.6)
            ax.set_yticks(range(len(uni_dist)))
            ax.set_yticklabels([u[:40] for u in uni_dist.index], fontsize=9)
            ax.set_xlabel("Participants")
            ax.set_title("University / Institution Distribution")
            ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            for b, v in zip(bars, uni_dist.values):
                ax.text(b.get_width() + 0.2, b.get_y() + b.get_height() / 2,
                        str(v), va="center", fontsize=10, color=CHART_FG)
            ax.grid(axis="x", alpha=0.3)
            fig.tight_layout()
            self._embed_chart(f, fig)

        # 8. Device distribution (from scan user agents)
        device_dist = self.store.device_distribution()
        if not device_dist.empty and len(device_dist) > 1:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            fig, ax = plt.subplots(figsize=(5, 3.5))
            dev_colours = {"Mobile": CHART_ACCENT2, "Desktop": CHART_ACCENT,
                           "Tablet": CHART_ACCENT3, "Unknown": "#666"}
            pie_colours = [dev_colours.get(d, "#666") for d in device_dist.index]
            ax.pie(device_dist.values,
                   labels=[f"{d} ({v})" for d, v in zip(device_dist.index, device_dist.values)],
                   colors=pie_colours, autopct="%1.0f%%", startangle=90,
                   textprops={"color": CHART_FG, "fontsize": 11},
                   wedgeprops={"edgecolor": CHART_BG, "linewidth": 2})
            ax.set_title("Scanner Device Types")
            fig.tight_layout()
            self._embed_chart(f, fig)

        # 9. Registration stats summary
        reg_stats = self.store.registration_stats()
        if reg_stats:
            f = ctk.CTkFrame(c)
            f.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(f, text="📋 Registration Overview",
                         font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(8, 4))
            tb = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Courier", size=12), height=120)
            tb.pack(fill="x", padx=8, pady=(0, 8))
            tb.configure(state="normal")
            for key, val in reg_stats.items():
                label = key.replace("_", " ").title()
                self._tw(tb, f"  {label:<30}{val}\n")
            tb.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════
    #  ELIGIBILITY
    # ══════════════════════════════════════════════════════════════════════
    def _build_eligibility(self):
        p = self.pages["eligibility"]
        ctk.CTkLabel(p, text="Eligibility", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 4))
        self.el_sum = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=14), text_color="gray")
        self.el_sum.pack(anchor="w", pady=(0, 8))
        self.el_tabs = ctk.CTkTabview(p)
        self.el_tabs.pack(fill="both", expand=True)
        self.el_tbs = {}
        for tn in ["✅ Eligible", "⏳ Not Yet", "📋 All"]:
            self.el_tabs.add(tn)
            tb = ctk.CTkTextbox(self.el_tabs.tab(tn), font=ctk.CTkFont(family="Courier", size=12))
            tb.pack(fill="both", expand=True, padx=4, pady=4)
            self.el_tbs[tn] = tb

    def _ref_elig(self):
        t = self.threshold
        e = self.store.eligible_participants(t)
        ie = self.store.ineligible_participants(t)

        if self.store.unique_participants:
            self.el_sum.configure(text=f"Threshold: {t} • {len(e)}/{self.store.unique_participants} eligible")
        else:
            self.el_sum.configure(text="No data.")

        # ✅ Eligible tab
        tb = self.el_tbs["✅ Eligible"]
        self._tc(tb)
        if not e.empty:
            self._tw(tb, f"  {'ID':<12}{'Name':<30}{'Email':<34}{'Sess':>6}\n  " + "─" * 84 + "\n")
            for _, r in e.iterrows():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, r[COL_ID])
                em = str(r.get(COL_EMAIL, ""))[:32] if COL_EMAIL in e.columns else ""
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(tb, f"{'':>{pad}}{str(r.get(COL_NAME, ''))[:28]:<30}{em:<34}"
                              f"{r['sessions_attended']:>6}\n")
        else:
            self._tw(tb, "\n   None yet.")
        self._tl(tb)

        # ⏳ Not Yet tab
        tb = self.el_tbs["⏳ Not Yet"]
        self._tc(tb)
        if not ie.empty:
            self._tw(tb, f"  {'ID':<12}{'Name':<30}{'Done':>6}{'Need':>6}\n  " + "─" * 56 + "\n")
            for _, r in ie.iterrows():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, r[COL_ID])
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(tb, f"{'':>{pad}}{str(r.get(COL_NAME, ''))[:28]:<30}"
                              f"{r['sessions_attended']:>6}{r['sessions_remaining']:>6}\n")
        else:
            self._tw(tb, "\n   Everyone eligible! 🎉")
        self._tl(tb)

        # 📋 All tab
        tb = self.el_tbs["📋 All"]
        self._tc(tb)
        cn = self.store.session_count_per_participant().sort_values(ascending=False)
        if not cn.empty:
            self._tw(tb, f"  {'ID':<12}{'Name':<30}{'Sess':>6}{'Status':>14}\n  " + "─" * 64 + "\n")
            for pid, cnt in cn.items():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, pid)
                pad = max(0, 12 - len(str(pid)))
                status = "✅" if cnt >= t else f"⏳ need {t - cnt}"
                self._tw(tb, f"{'':>{pad}}{self.store.get_name(pid)[:28]:<30}{cnt:>6}{status:>14}\n")
        else:
            self._tw(tb, "\n   No data.")
        self._tl(tb)

    # ══════════════════════════════════════════════════════════════════════
    #  SEARCH
    # ══════════════════════════════════════════════════════════════════════
    def _build_search(self):
        p = self.pages["search"]
        ctk.CTkLabel(p, text="Search (⌘F)", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 8))
        sf = ctk.CTkFrame(p, fg_color="transparent")
        sf.pack(fill="x", pady=(0, 8))
        self.search_entry = ctk.CTkEntry(sf, placeholder_text="Search…", width=360, height=38,
                                          font=ctk.CTkFont(size=14))
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self._do_search())
        ctk.CTkButton(sf, text="Search", width=80, height=38, command=self._do_search).pack(side="left", padx=(0, 8))
        ctk.CTkButton(sf, text="Open →", width=80, height=38,
                      fg_color=("gray70", "gray30"), command=self._open_from_search).pack(side="left")
        self.srch_lbl = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=13), text_color="gray")
        self.srch_lbl.pack(anchor="w", pady=(0, 4))
        self.srch_tb = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Courier", size=12))
        self.srch_tb.pack(fill="both", expand=True)

    def _do_search(self):
        q = self.search_entry.get().strip()
        if not q:
            return
        res = self.store.search(q)
        self._tc(self.srch_tb)
        if res.empty:
            self.srch_lbl.configure(text=f"No results for '{q}'")
            self._tw(self.srch_tb, "\n   No matches.")
        else:
            self.srch_lbl.configure(text=f"{len(res)} scan(s), {res[COL_ID].nunique()} pax")
            self._tw(self.srch_tb, f"  {'ID':<12}{'Name':<28}{'Session':<28}{'IP':<18}{'Time':>20}\n  "
                                    + "─" * 108 + "\n")
            for _, r in res.iterrows():
                self._tw(self.srch_tb, "  ")
                self._make_id_clickable(self.srch_tb, r[COL_ID])
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(self.srch_tb,
                         f"{'':>{pad}}{self.store.get_name(r[COL_ID])[:26]:<28}"
                         f"{str(r[COL_SESSION])[:26]:<28}{str(r.get(COL_IP, ''))[:16]:<18}"
                         f"{str(r[COL_TIMESTAMP])[:20]:>20}\n")
        self._tl(self.srch_tb)
        self._last_search = res

    def _open_from_search(self):
        if not self._last_search.empty:
            pid = self._last_search.iloc[0][COL_ID]
        else:
            pid = self.search_entry.get().strip()
        self._nav_participant(pid)

    # ══════════════════════════════════════════════════════════════════════
    #  PARTICIPANT DETAIL
    # ══════════════════════════════════════════════════════════════════════
    def _build_participant(self):
        p = self.pages["participant"]
        ctk.CTkLabel(p, text="Participant Detail", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 10))
        sf = ctk.CTkFrame(p, fg_color="transparent")
        sf.pack(fill="x", pady=(0, 10))
        self.part_entry = ctk.CTkEntry(sf, placeholder_text="Participant ID…", width=260, height=38,
                                        font=ctk.CTkFont(size=14))
        self.part_entry.pack(side="left", padx=(0, 8))
        self.part_entry.bind("<Return>", lambda e: self._do_plookup())
        ctk.CTkButton(sf, text="Look Up", width=80, height=38, command=self._do_plookup).pack(side="left", padx=(0, 8))
        ctk.CTkButton(sf, text="📄 Report", width=100, height=38,
                      fg_color=("gray70", "gray30"), command=self._exp_report).pack(side="left")
        self.pi = ctk.CTkFrame(p)
        self.pi.pack(fill="x", pady=(0, 6))
        self.p_id = ctk.CTkLabel(self.pi, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self.p_id.pack(anchor="w", padx=12, pady=(8, 2))
        self.p_name = ctk.CTkLabel(self.pi, text="", font=ctk.CTkFont(size=14), text_color="gray")
        self.p_name.pack(anchor="w", padx=12)
        self.p_st = ctk.CTkLabel(self.pi, text="", font=ctk.CTkFont(size=14))
        self.p_st.pack(anchor="w", padx=12)
        self.p_detail = ctk.CTkLabel(self.pi, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.p_detail.pack(anchor="w", padx=12)
        self.p_ip = ctk.CTkLabel(self.pi, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.p_ip.pack(anchor="w", padx=12, pady=(0, 8))
        self.pb = ctk.CTkFrame(p, fg_color="transparent")
        self.pb.pack(fill="both", expand=True)
        self.p_tb = ctk.CTkTextbox(self.pb, font=ctk.CTkFont(family="Courier", size=12), width=640)
        self.p_tb.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.p_ch = ctk.CTkFrame(self.pb, width=320)
        self.p_ch.pack(side="right", fill="both")
        self.p_ch.pack_propagate(False)

    def _do_plookup(self):
        pid = self.part_entry.get().strip()
        if not pid:
            return

        # Clean up previous participant chart
        self._close_charts()

        r = self.store.lookup(pid)
        self._tc(self.p_tb)
        self._clear_frame(self.p_ch)

        if r is None:
            self.p_id.configure(text=f"ID: {pid}")
            self.p_name.configure(text="")
            self.p_ip.configure(text="")
            self.p_st.configure(text="❌ Not found.", text_color="#ef4444")
            self._tw(self.p_tb, "\n   No records.")
            self._tl(self.p_tb)
            return

        ns = r[COL_SESSION].nunique()
        ts = len(r)
        el = ns >= self.threshold
        name = self.store.get_name(pid)
        rip = self.store.get_reg_ip(pid)
        year = self.store.get_year(pid)
        uni = self.store.get_university(pid)
        phone = self.store.get_phone(pid)

        self.p_id.configure(text=f"ID: {pid}")
        self.p_name.configure(text=name or "No name")
        if el:
            self.p_st.configure(text=f"✅ ELIGIBLE • {ns} sess • {ts} scans", text_color="#10b981")
        else:
            self.p_st.configure(text=f"⏳ {self.threshold - ns} more • {ns}/{self.threshold} • {ts} scans",
                                text_color="#f59e0b")
        detail_parts = []
        if year:
            detail_parts.append(f"Year: {year}")
        if uni:
            detail_parts.append(uni[:50])
        if phone:
            detail_parts.append(f"Tel: {phone}")
        self.p_detail.configure(text=" • ".join(detail_parts) if detail_parts else "")
        self.p_ip.configure(
            text=f"Reg IP: {rip or 'N/A'} • Scan IPs: {', '.join(str(ip) for ip in r[COL_IP].unique())}"
        )

        seen = set()
        sched = self.store.schedule
        self._tw(self.p_tb,
                 f"  {'#':<4}{'Session':<28}{'IP':<18}{'Timestamp':>20}{'Timing':>12}{'Flags':>6}\n  "
                 + "─" * 90 + "\n")
        for i, (_, row) in enumerate(r.iterrows(), 1):
            flags = ""
            if row[COL_SESSION] in seen:
                flags += "⚠️"
            seen.add(row[COL_SESSION])
            if rip and str(row[COL_IP]).strip() != str(rip).strip():
                flags += "🔀"
            timing = ""
            if sched:
                ss = sched.get_session_by_name(row[COL_SESSION])
                if ss:
                    ts_dt = pd.to_datetime(row[COL_TIMESTAMP])
                    off = ss.arrival_offset_min(ts_dt)
                    if not ss.is_within_window(ts_dt, 15):
                        timing = "🕐 OOW"
                    elif abs(off) <= 2:
                        timing = "✅"
                    else:
                        timing = f"{off:+.0f}m"
            self._tw(self.p_tb,
                     f"  {i:<4}{str(row[COL_SESSION])[:26]:<28}{str(row[COL_IP])[:16]:<18}"
                     f"{str(row[COL_TIMESTAMP])[:20]:>20}{timing:>12}{flags:>6}\n")
        self._tw(self.p_tb, f"\n  ⚠️=dup  🔀=IP diff  🕐 OOW=out of time window")
        self._tl(self.p_tb)

        # Session dot chart
        all_s = self.store.sessions
        at = set(r[COL_SESSION].unique())
        fig, ax = plt.subplots(figsize=(3.5, max(2.5, len(all_s) * 0.35)))
        for i, s in enumerate(all_s):
            ax.scatter(0.5, i, s=200, c=CHART_ACCENT2 if s in at else "#3a3a5a",
                       zorder=3, edgecolors="none")
            lbl = s[:24]
            if sched:
                ss = sched.get_session_by_name(s)
                if ss:
                    lbl = f"{s[:18]} ({ss.start})"
            ax.text(0.7, i, lbl, va="center", fontsize=8, color=CHART_FG)
        ax.set_xlim(0, 3.8)
        ax.set_ylim(-0.5, len(all_s) - 0.5)
        ax.invert_yaxis()
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f"{ns}/{len(all_s)} Sessions", fontsize=11)
        for sp in ax.spines.values():
            sp.set_visible(False)
        fig.tight_layout()
        self._embed_chart(self.p_ch, fig)

    def _exp_report(self):
        pid = self.part_entry.get().strip()
        if not pid:
            messagebox.showwarning("No ID", "Enter an ID first.")
            return
        if self.store.lookup(pid) is None:
            messagebox.showwarning("Not Found", f"No records for '{pid}'.")
            return
        html = self.store.generate_participant_report_html(pid, self.threshold)
        fp = filedialog.asksaveasfilename(
            defaultextension=".html", filetypes=[("HTML", "*.html")],
            initialfile=f"camesm_report_{pid}_{datetime.now():%Y%m%d}.html",
        )
        if fp:
            Path(fp).write_text(html, encoding="utf-8")
            messagebox.showinfo("Saved", f"Report: {fp}")
            webbrowser.open(f"file://{os.path.abspath(fp)}")

    # ══════════════════════════════════════════════════════════════════════
    #  DUPLICATES
    # ══════════════════════════════════════════════════════════════════════
    def _build_duplicates(self):
        p = self.pages["duplicates"]
        ctk.CTkLabel(p, text="Duplicates", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 10))
        self.dup_sum = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.dup_sum.pack(anchor="w", pady=(0, 6))
        self.dup_tb = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Courier", size=12))
        self.dup_tb.pack(fill="both", expand=True)

    def _ref_dupes(self):
        d = self.store.duplicate_scans()
        self._tc(self.dup_tb)
        if d.empty:
            self.dup_sum.configure(text="✅ None" if self.store.total_scans else "")
            self._tw(self.dup_tb, "\n   All clear." if self.store.total_scans else "\n   No data.")
        else:
            self.dup_sum.configure(text=f"⚠️ {len(d)} duplicate(s)")
            self._tw(self.dup_tb, f"  {'Session':<30}{'ID':<12}{'Name':<28}{'Scans':>6}\n  " + "─" * 78 + "\n")
            for _, r in d.iterrows():
                self._tw(self.dup_tb, f"  {str(r[COL_SESSION])[:28]:<30}")
                self._make_id_clickable(self.dup_tb, r[COL_ID])
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(self.dup_tb, f"{'':>{pad}}{self.store.get_name(r[COL_ID])[:26]:<28}{r['scan_count']:>6}\n")
        self._tl(self.dup_tb)

    # ══════════════════════════════════════════════════════════════════════
    #  UNMATCHED
    # ══════════════════════════════════════════════════════════════════════
    def _build_unmatched(self):
        p = self.pages["unmatched"]
        ctk.CTkLabel(p, text="Unmatched IDs", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 10))
        self.um_tb = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Courier", size=12))
        self.um_tb.pack(fill="both", expand=True)

    def _ref_unmatched(self):
        self._tc(self.um_tb)
        if self.store.registration is None:
            self._tw(self.um_tb, "\n   No registration loaded.")
            self._tl(self.um_tb)
            return
        um = self.store.unmatched_ids()
        so, ro = sorted(um["scan_only"]), sorted(um["registration_only"])
        self._tw(self.um_tb, f"  SCANNED NOT REGISTERED ({len(so)})\n  " + "─" * 60 + "\n")
        for pid in so:
            self._tw(self.um_tb, "    ⚠️ ")
            self._make_id_clickable(self.um_tb, pid)
            self._tw(self.um_tb, "\n")
        if not so:
            self._tw(self.um_tb, "    ✅ All match.\n")
        self._tw(self.um_tb, f"\n  REGISTERED NOT SCANNED ({len(ro)})\n  " + "─" * 60 + "\n")
        for pid in ro:
            n = self.store.get_name(pid)
            self._tw(self.um_tb, "    ○ ")
            self._make_id_clickable(self.um_tb, pid)
            self._tw(self.um_tb, f"  ({n})\n" if n else "\n")
        if not ro:
            self._tw(self.um_tb, "    ✅ All scanned.\n")
        self._tl(self.um_tb)

    # ══════════════════════════════════════════════════════════════════════
    #  SCAN AUDIT
    # ══════════════════════════════════════════════════════════════════════
    def _build_scan_audit(self):
        p = self.pages["scan_audit"]
        ctk.CTkLabel(p, text="Scan Audit", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 8))
        self.au_tabs = ctk.CTkTabview(p)
        self.au_tabs.pack(fill="both", expand=True)
        self.au_tbs = {}
        for tn in ["🚩 Isolated", "🏎️ Travel", "🕐 Out-of-Window", "⏱️ Timing Stats", "📋 Full Log", "🌐 IPs"]:
            self.au_tabs.add(tn)
            tb = ctk.CTkTextbox(self.au_tabs.tab(tn), font=ctk.CTkFont(family="Courier", size=12))
            tb.pack(fill="both", expand=True, padx=4, pady=4)
            self.au_tbs[tn] = tb

    def _ref_audit(self):
        for tb in self.au_tbs.values():
            self._tc(tb)
        if self.store.total_scans == 0:
            for tb in self.au_tbs.values():
                self._tw(tb, "\n   No data.")
                self._tl(tb)
            return

        a = self.store.anomalies(isolation_min=10, travel_min=5, grace_min=15)

        # 🚩 Isolated
        tb = self.au_tbs["🚩 Isolated"]
        self._tw(tb, "  Scans with no activity within ±10 min.\n\n")
        if a["isolated"].empty:
            self._tw(tb, "  ✅ None detected.\n")
        else:
            self._tw(tb, f"  🚩 {len(a['isolated'])} isolated:\n\n"
                         f"  {'ID':<12}{'Name':<28}{'Session':<24}{'IP':<18}{'Time':>20}{'Gap':>8}\n  "
                         + "─" * 112 + "\n")
            for _, r in a["isolated"].iterrows():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, r[COL_ID])
                gap = f"{r['nearest_min']:.0f}" if r["nearest_min"] is not None else "∞"
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(tb, f"{'':>{pad}}{str(r.get('name', ''))[:26]:<28}"
                              f"{str(r[COL_SESSION])[:22]:<24}{str(r[COL_IP])[:16]:<18}"
                              f"{str(r[COL_TIMESTAMP])[:20]:>20}{gap:>8}\n")
        self._tl(tb)

        # 🏎️ Travel
        tb = self.au_tbs["🏎️ Travel"]
        self._tw(tb, "  Same ID at different sessions within <5 min.\n\n")
        if a["impossible_travel"].empty:
            self._tw(tb, "  ✅ None detected.\n")
        else:
            self._tw(tb, f"  🏎️ {len(a['impossible_travel'])} suspicious:\n\n"
                         f"  {'ID':<12}{'Name':<24}{'From':<22}{'To':<22}{'Gap':>6}\n  "
                         + "─" * 88 + "\n")
            for _, r in a["impossible_travel"].iterrows():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, r[COL_ID])
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(tb, f"{'':>{pad}}{str(r.get('name', ''))[:22]:<24}"
                              f"{r['session_1'][:20]:<22}{r['session_2'][:20]:<22}{r['gap_min']:>5.1f}m\n")
        self._tl(tb)

        # 🕐 Out-of-Window
        tb = self.au_tbs["🕐 Out-of-Window"]
        if self.store.schedule is None:
            self._tw(tb, "\n   Load a schedule JSON to enable time-window validation.")
        elif a["out_of_window"].empty:
            self._tw(tb, "  ✅ All scans within scheduled windows (±15 min grace).\n")
        else:
            self._tw(tb, f"  🕐 {len(a['out_of_window'])} scan(s) outside session windows:\n\n"
                         f"  {'ID':<12}{'Name':<24}{'Session':<22}{'Scheduled':>14}{'Offset':>10}{'Status':>8}\n  "
                         + "─" * 92 + "\n")
            for _, r in a["out_of_window"].iterrows():
                self._tw(tb, "  ")
                self._make_id_clickable(tb, r[COL_ID])
                pad = max(0, 12 - len(str(r[COL_ID])))
                self._tw(tb, f"{'':>{pad}}{str(r.get('name', ''))[:22]:<24}"
                              f"{r[COL_SESSION][:20]:<22}"
                              f"{r['scheduled_start'] + '–' + r['scheduled_end']:>14}"
                              f"{r['offset_min']:>+10.0f}m{r['status']:>8}\n")
        self._tl(tb)

        # ⏱️ Timing Stats
        tb = self.au_tbs["⏱️ Timing Stats"]
        if self.store.schedule is None:
            self._tw(tb, "\n   Load a schedule to see per-session timing stats.")
        elif a["timing_stats"].empty:
            self._tw(tb, "\n   No timing data available.")
        else:
            self._tw(tb, "  Per-session timing analysis (schedule vs actual scans):\n\n"
                         f"  {'Session':<24}{'Scheduled':>14}{'Attend':>7}{'1st Scan':>10}"
                         f"{'Last Scan':>10}{'Avg Offset':>12}{'In Window':>10}\n  " + "─" * 89 + "\n")
            for _, r in a["timing_stats"].iterrows():
                self._tw(tb, f"  {r['session'][:22]:<24}{r['scheduled']:>14}{r['attendees']:>7}"
                              f"{r['first_scan']:>10}{r['last_scan']:>10}"
                              f"{r['avg_arrival_offset']:>12}{r['in_window_pct']:>10}\n")
        self._tl(tb)

        # 📋 Full Log
        tb = self.au_tbs["📋 Full Log"]
        full = a["full_log"]
        self._tw(tb, f"  {'ID':<12}{'Name':<28}{'Session':<24}{'IP':<18}{'Time':>20}\n  " + "─" * 104 + "\n")
        for _, r in full.iterrows():
            self._tw(tb, "  ")
            self._make_id_clickable(tb, r[COL_ID])
            pad = max(0, 12 - len(str(r[COL_ID])))
            self._tw(tb, f"{'':>{pad}}{str(r.get('name', ''))[:26]:<28}"
                          f"{str(r[COL_SESSION])[:22]:<24}{str(r[COL_IP])[:16]:<18}"
                          f"{str(r[COL_TIMESTAMP])[:20]:>20}\n")
        self._tw(tb, f"\n  Total: {len(full)} scan(s)\n")
        self._tl(tb)

        # 🌐 IPs
        tb = self.au_tbs["🌐 IPs"]
        sm = a["ip_summary"]
        self._tw(tb, f"  {'Session':<28}{'IP':<20}{'Scans':>6}{'IDs':>6}\n  " + "─" * 62 + "\n")
        cur = ""
        for _, r in sm.iterrows():
            s = str(r[COL_SESSION])[:26]
            if s != cur:
                if cur:
                    self._tw(tb, "\n")
                cur = s
            self._tw(tb, f"  {s:<28}{str(r[COL_IP])[:18]:<20}{r['scans']:>6}{r['unique_ids']:>6}\n")
        self._tl(tb)

    # ══════════════════════════════════════════════════════════════════════
    #  IMPORT
    # ══════════════════════════════════════════════════════════════════════
    def _build_import(self):
        p = self.pages["import"]
        ctk.CTkLabel(p, text="Import Data", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 12))

        # Schedule
        ctk.CTkLabel(p, text="📅 Conference Schedule",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(p, text="Load schedule JSON — enables time-window validation, auto-naming, and timing analytics",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(p, text="📅  Import Schedule JSON", height=38,
                      command=self._imp_sched).pack(anchor="w", pady=(0, 4))
        self.sched_lbl = ctk.CTkLabel(p, text="No schedule loaded",
                                       font=ctk.CTkFont(size=13), text_color="gray")
        self.sched_lbl.pack(anchor="w", pady=(0, 6))

        ctk.CTkFrame(p, height=2, fg_color="gray30").pack(fill="x", pady=6)

        # Scans
        ctk.CTkLabel(p, text="Session Scan Logs",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 4))
        bf = ctk.CTkFrame(p, fg_color="transparent")
        bf.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(bf, text="📄 Single CSV", height=36, command=self._imp_single).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bf, text="📁 Folder", height=36, command=self._imp_folder).pack(side="left")
        ctk.CTkLabel(p, text="Session names auto-matched from schedule when loaded, or you'll be prompted.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w", pady=(0, 4))

        # Rename
        ctk.CTkFrame(p, height=2, fg_color="gray30").pack(fill="x", pady=4)
        rf = ctk.CTkFrame(p, fg_color="transparent")
        rf.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(rf, text="Rename:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self.rn_old = ctk.CTkEntry(rf, placeholder_text="Current…", width=200, height=32)
        self.rn_old.pack(side="left", padx=(0, 4))
        self.rn_new = ctk.CTkEntry(rf, placeholder_text="New…", width=200, height=32)
        self.rn_new.pack(side="left", padx=(0, 4))
        ctk.CTkButton(rf, text="Go", width=50, height=32, command=self._rename).pack(side="left")

        # Registration
        ctk.CTkFrame(p, height=2, fg_color="gray30").pack(fill="x", pady=4)
        ctk.CTkLabel(p, text="Registration CSV",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(p, text="📋 Import Registration", height=36,
                      command=self._imp_reg).pack(anchor="w", pady=(0, 4))
        self.reg_lbl = ctk.CTkLabel(p, text="Not loaded", font=ctk.CTkFont(size=13), text_color="gray")
        self.reg_lbl.pack(anchor="w", pady=(0, 6))

        # Workshop Registration
        ctk.CTkFrame(p, height=2, fg_color="gray30").pack(fill="x", pady=4)
        ctk.CTkLabel(p, text="Workshop Registration CSV",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(p, text="Sign-up form data (no ID) — matched to main registration via email",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w", pady=(0, 4))
        ctk.CTkButton(p, text="🎓 Import Workshop Registration", height=36,
                      command=self._imp_workshop_reg).pack(anchor="w", pady=(0, 4))
        self.wreg_lbl = ctk.CTkLabel(p, text="Not loaded", font=ctk.CTkFont(size=13), text_color="gray")
        self.wreg_lbl.pack(anchor="w", pady=(0, 6))

        ctk.CTkLabel(p, text="Log", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(4, 2))
        self.imp_tb = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Courier", size=12), height=100)
        self.imp_tb.pack(fill="both", expand=True)
        self.imp_tb.configure(state="disabled")

    def _log_imp(self, msg):
        self.imp_tb.configure(state="normal")
        self.imp_tb.insert("end", f"  [{datetime.now():%H:%M:%S}]  {msg}\n")
        self.imp_tb.see("end")
        self.imp_tb.configure(state="disabled")

    def _imp_sched(self):
        fp = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if not fp:
            return
        try:
            n = self.store.load_schedule(fp)
            self.sched_lbl.configure(text=f"✅ {Path(fp).name} — {n} sessions loaded", text_color="#10b981")
            self._log_imp(f"✅ Schedule: {Path(fp).name} — {n} sessions")
        except Exception as e:
            self.sched_lbl.configure(text=f"❌ {e}", text_color="#ef4444")
            self._log_imp(f"❌ Schedule: {e}")

    def _peek_has_workshop(self, filepath: str) -> bool:
        """Check if a CSV has a workshop/session column without fully loading it."""
        header = pd.read_csv(filepath, nrows=0)
        header = _norm_cols(header)
        return "workshop" in header.columns or COL_SESSION in header.columns

    def _imp_single(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not fp:
            return
        has_workshop = self._peek_has_workshop(fp)
        label = None
        if not has_workshop:
            default = Path(fp).stem.replace("_", " ").replace("-", " ").title()
            label = simpledialog.askstring("Session Name", f"Name for:\n{Path(fp).name}",
                                           initialvalue=default, parent=self)
            if label is None:
                return
            label = label.strip() or default
        try:
            n = self.store.load_csv(fp, session_label=label)
            if n == -1:
                self._log_imp(f"⚠ {Path(fp).name} — already loaded")
            else:
                suffix = " (session from Workshop column)" if has_workshop else f" → '{label}'"
                self._log_imp(f"✅ {Path(fp).name} — {n} records{suffix}")
        except Exception as e:
            self._log_imp(f"❌ {Path(fp).name} — {e}")

    def _imp_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        for f in sorted(Path(folder).glob("*.csv")):
            has_workshop = self._peek_has_workshop(str(f))
            label = None
            if not has_workshop:
                default = f.stem.replace("_", " ").replace("-", " ").title()
                label = simpledialog.askstring("Session Name", f"Name for:\n{f.name}",
                                               initialvalue=default, parent=self)
                if label is None:
                    continue
                label = label.strip() or default
            try:
                n = self.store.load_csv(str(f), session_label=label)
                if n == -1:
                    self._log_imp(f"⚠ {f.name} — already loaded")
                else:
                    suffix = " (multi-session)" if has_workshop else f" → '{label}'"
                    self._log_imp(f"✅ {f.name} — {n} records{suffix}")
            except Exception as e:
                self._log_imp(f"❌ {f.name} — {e}")

    def _imp_reg(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not fp:
            return
        try:
            n = self.store.load_registration(fp)
            self.reg_lbl.configure(text=f"✅ {Path(fp).name} — {n} registrants", text_color="#10b981")
            self._log_imp(f"✅ Reg: {Path(fp).name} — {n}")
        except Exception as e:
            self.reg_lbl.configure(text=f"❌ {e}", text_color="#ef4444")
            self._log_imp(f"❌ {e}")

    def _imp_workshop_reg(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not fp:
            return
        if self.store.registration is None:
            messagebox.showwarning("Load Registration First",
                                   "Import the main registration CSV before workshop registration "
                                   "— email matching requires it.")
            return
        try:
            total, matched = self.store.load_workshop_registration(fp)
            self.wreg_lbl.configure(
                text=f"✅ {Path(fp).name} — {total} rows, {matched} matched",
                text_color="#10b981")
            self._log_imp(f"✅ Workshop Reg: {Path(fp).name} — {total} rows, {matched} matched")
        except Exception as e:
            self.wreg_lbl.configure(text=f"❌ {e}", text_color="#ef4444")
            self._log_imp(f"❌ Workshop Reg: {e}")

    def _rename(self):
        o = self.rn_old.get().strip()
        n = self.rn_new.get().strip()
        if not o or not n:
            return
        if o not in self.store.sessions:
            messagebox.showwarning("Not Found", f"'{o}' not in: {', '.join(self.store.sessions)}")
            return
        self.store.rename_session(o, n)
        self._log_imp(f"🔄 '{o}' → '{n}'")
        self.rn_old.delete(0, "end")
        self.rn_new.delete(0, "end")

    # ══════════════════════════════════════════════════════════════════════
    #  EXPORTS
    # ══════════════════════════════════════════════════════════════════════
    def _build_exports(self):
        p = self.pages["exports"]
        ctk.CTkLabel(p, text="Exports", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", pady=(0, 12))
        exports = [
            ("📥 Eligible Participants", "IDs, names, emails, counts.", self._exp_elig),
            ("📊 Attendance × Sessions", "Cross-tab matrix.", self._exp_att),
            ("📋 Audit Log", "All actions logged.", self._exp_audit),
        ]
        for title, desc, cmd in exports:
            f = ctk.CTkFrame(p)
            f.pack(fill="x", pady=4)
            ctk.CTkButton(f, text=title, height=38, anchor="w",
                          font=ctk.CTkFont(size=14), command=cmd).pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(f, text=desc, font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w", padx=16, pady=(0, 6))

    def _exp_elig(self):
        if not self.store.total_scans:
            messagebox.showwarning("No Data", "Import first.")
            return
        fp = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"eligible_{datetime.now():%Y%m%d_%H%M}.csv",
        )
        if fp:
            n = self.store.export_eligibility_csv(fp, self.threshold)
            messagebox.showinfo("Saved", f"{n} records.")

    def _exp_att(self):
        if not self.store.total_scans:
            messagebox.showwarning("No Data", "Import first.")
            return
        fp = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"attendance_{datetime.now():%Y%m%d_%H%M}.csv",
        )
        if fp:
            n = self.store.export_attendance_by_session(fp)
            messagebox.showinfo("Saved", f"{n} rows.")

    def _exp_audit(self):
        fp = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"audit_{datetime.now():%Y%m%d_%H%M}.csv",
        )
        if fp:
            n = self.store.export_audit_log(fp)
            messagebox.showinfo("Saved", f"{n} entries.")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    TrackerApp().mainloop()
