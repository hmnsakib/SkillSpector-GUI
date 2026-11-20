"""SkillSpector Scanner - a simple window for NVIDIA's SkillSpector.

Detects SkillSpector (installs it if missing), lets you pick a skill to scan,
runs the scan in the background and shows the results.
"""
import json
import os
import queue
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ss_core as core

ACCENT = "#0F7B6C"
ACCENT_DARK = "#0B5F54"
INK = "#16181A"
MUTED = "#5A5F5B"
LINE = "#D9DBD5"
RAIL_BG = "#F4F5F2"
WHITE = "#FFFFFF"
SEV_COLORS = {"High": ("#FBEAE8", "#8E1B14"), "Medium": ("#FFF1D0", "#6B4400"), "Low": ("#E6EDF8", "#1B3F7A")}
IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"
FONT = "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
MONO = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")


class _MacButton(tk.Label):
    """tk.Button ignores bg/fg on macOS, so use a Label that acts like a button there."""

    def __init__(self, parent, command=None, activebackground=None, activeforeground=None,
                 relief="flat", bd=0, padx=8, pady=4, highlightthickness=0, **kw):
        kw.pop("state", None)
        super().__init__(parent, padx=padx, pady=pady, highlightthickness=highlightthickness, **kw)
        self._cmd, self._state = command, "normal"
        self._ab, self._af = activebackground, activeforeground
        self._saved = {}
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def configure(self, cnf=None, **kw):
        kw = dict(kw)
        if "command" in kw:
            self._cmd = kw.pop("command")
        if "activebackground" in kw:
            self._ab = kw.pop("activebackground")
        if "activeforeground" in kw:
            self._af = kw.pop("activeforeground")
        kw.pop("disabledforeground", None)
        if "state" in kw:
            self._state = kw.pop("state")
        return super().configure(cnf, **kw) if cnf else super().configure(**kw)

    config = configure

    def _press(self, _):
        if self._state == "normal" and self._ab:
            self._saved = {"bg": tk.Label.cget(self, "bg"), "fg": tk.Label.cget(self, "fg")}
            super().configure(bg=self._ab, fg=self._af or self._saved["fg"])

    def _release(self, e):
        if self._saved:
            super().configure(**self._saved)
            self._saved = {}
        if (self._state == "normal" and self._cmd
                and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()):
            self._cmd()


def Button(parent, **kw):
    return (_MacButton if IS_MAC else tk.Button)(parent, **kw)

KINDS = [
    ("folder", "Folder", "Skill folder", "The folder that contains SKILL.md.", "Browse folder…",
     os.path.join("~", "Downloads", "my-skill")),
    ("file", "SKILL.md file", "Skill file", "A single SKILL.md file.", "Browse file…",
     os.path.join("~", "Downloads", "SKILL.md")),
    ("zip", "Zip file", "Zip file", "A zipped skill package.", "Browse zip…",
     os.path.join("~", "Downloads", "my-skill.zip")),
    ("git", "Git link", "Link to the skill on GitHub", "Paste the address of the repository.", "",
     "https://github.com/user/my-skill"),
]


def flat_button(parent, text, command, primary=True, **kw):
    if primary:
        b = Button(parent, text=text, command=command, bg=ACCENT, fg=WHITE, activebackground=ACCENT_DARK,
                      activeforeground=WHITE, relief="flat", bd=0, cursor="hand2",
                      font=(FONT, 11, "bold"), padx=22, pady=9, **kw)
    else:
        b = Button(parent, text=text, command=command, bg=WHITE, fg=INK, activebackground="#EEF0EB",
                      activeforeground=INK, relief="flat", bd=0, cursor="hand2", font=(FONT, 10, "bold"),
                      padx=16, pady=8, highlightthickness=1, highlightbackground="#8D918B", **kw)
    return b


def heading(parent, text):
    return tk.Label(parent, text=text, font=(FONT, 18, "bold"), bg=WHITE, fg=INK, anchor="w")


def body(parent, text, wrap=560, fg="#3A3F3C", size=10):
    return tk.Label(parent, text=text, font=(FONT, size), bg=WHITE, fg=fg, anchor="w", justify="left",
                    wraplength=wrap)


def log_box(parent, height=8):
    frame = tk.Frame(parent, bg="#16181A")
    t = tk.Text(frame, height=height, bg="#16181A", fg="#D8DCD6", font=(MONO, 9), relief="flat", bd=0,
                padx=12, pady=10, wrap="word", state="disabled", insertbackground="#D8DCD6")
    sb = ttk.Scrollbar(frame, command=t.yview)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    return frame, t


def append_text(widget, line):
    widget.configure(state="normal")
    widget.insert("end", line + "\n")
    widget.see("end")
    widget.configure(state="disabled")


class ScrollFrame(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=WHITE, **kw)
        self.canvas = tk.Canvas(self, bg=WHITE, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=WHITE)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._wheel)

    def _unbind_wheel(self, _):
        self.canvas.unbind_all("<MouseWheel>")

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SkillSpector Scanner")
        self.geometry("960x680")
        self.minsize(900, 640)
        self.configure(bg=WHITE)
        self.q = queue.Queue()
        self.holder = {}
        self.status = {}
        self.kind = "folder"
        self.target = tk.StringVar()
        self.quick = tk.BooleanVar(value=True)
        self.api_key = tk.StringVar()
        self.provider = tk.StringVar(value="OpenAI")
        self.scan_result = None
        self.findings = None
        self.filter = "All"
        self.last_target = ""
        self.recommendation = None
        self._build()
        self.target.trace_add("write", lambda *a: self._update_scan_button())
        self.after(80, self._poll)
        self.show("checking")
        threading.Thread(target=self._check_job, daemon=True).start()

    # ------------------------------------------------------------ layout
    def _build(self):
        self.status_var = tk.StringVar(value="Checking your computer…")
        bar = tk.Frame(self, bg=RAIL_BG, height=30, highlightthickness=1, highlightbackground=LINE)
        bar.pack(side="bottom", fill="x")
        tk.Label(bar, textvariable=self.status_var, bg=RAIL_BG, fg="#4A4F4B", font=(FONT, 9)).pack(side="left", padx=14, pady=5)
        tk.Label(bar, text="A clean result is not proof a skill is safe.", bg=RAIL_BG, fg="#4A4F4B",
                 font=(FONT, 9)).pack(side="right", padx=14)

        rail = tk.Frame(self, bg=RAIL_BG, width=210, highlightthickness=1, highlightbackground=LINE)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Label(rail, text="SkillSpector", bg=RAIL_BG, fg=INK, font=(FONT, 13, "bold"), anchor="w").pack(
            fill="x", padx=20, pady=(24, 0))
        tk.Label(rail, text="Skill Security Scanner", bg=RAIL_BG, fg=MUTED, font=(FONT, 9), anchor="w").pack(
            fill="x", padx=20, pady=(0, 24))
        self.rail_items = []
        for n, (label, sub) in enumerate([("Set up", "Install SkillSpector"), ("Choose", "What to scan"),
                                          ("Results", "Safe to install?")], 1):
            row = tk.Frame(rail, bg=RAIL_BG)
            row.pack(fill="x", padx=20, pady=10)
            c = tk.Canvas(row, width=28, height=28, bg=RAIL_BG, highlightthickness=0)
            c.pack(side="left")
            txt = tk.Frame(row, bg=RAIL_BG)
            txt.pack(side="left", padx=12)
            l1 = tk.Label(txt, text=label, bg=RAIL_BG, fg=INK, font=(FONT, 10), anchor="w")
            l1.pack(anchor="w")
            tk.Label(txt, text=sub, bg=RAIL_BG, fg=MUTED, font=(FONT, 8), anchor="w").pack(anchor="w")
            self.rail_items.append((c, l1, n))
        tk.Label(rail, text="Scans only read the files.\nNothing from the skill is run\non your computer.",
                 bg=RAIL_BG, fg=MUTED, font=(FONT, 8), justify="left", anchor="w").pack(
            side="bottom", fill="x", padx=20, pady=20)

        self.main = tk.Frame(self, bg=WHITE)
        self.main.pack(side="left", fill="both", expand=True, padx=40, pady=30)
        self.screens = {}
        for name in ("checking", "missing", "installing", "ready", "scanning", "results"):
            f = tk.Frame(self.main, bg=WHITE)
            self.screens[name] = f
        self._build_checking(self.screens["checking"])
        self._build_missing(self.screens["missing"])
        self._build_installing(self.screens["installing"])
        self._build_ready(self.screens["ready"])
        self._build_scanning(self.screens["scanning"])
        self._build_results(self.screens["results"])

    def set_step(self, step):
        for c, lab, n in self.rail_items:
            c.delete("all")
            done, active = n < step, n == step
            fill = "#124E45" if done else (ACCENT if active else "#E4E6E1")
            fg = WHITE if (done or active) else "#3A3F3C"
            c.create_oval(1, 1, 27, 27, fill=fill, outline=fill)
            c.create_text(14, 14, text="✓" if done else str(n), fill=fg, font=(FONT, 10, "bold"))
            lab.configure(font=(FONT, 10, "bold" if active else "normal"))

    def show(self, name):
        for f in self.screens.values():
            f.pack_forget()
        self.screens[name].pack(fill="both", expand=True)
        self.set_step({"checking": 1, "missing": 1, "installing": 1, "ready": 2, "scanning": 2, "results": 3}[name])
        self.status_var.set({"checking": "Checking your computer…", "missing": "SkillSpector is not installed",
                             "installing": "Installing…", "ready": "SkillSpector is ready",
                             "scanning": "Scanning…", "results": "Scan complete"}[name])
        self.current = name

    # ------------------------------------------------------------ checking
    def _build_checking(self, f):
        box = tk.Frame(f, bg=WHITE)
        box.place(relx=0.5, rely=0.45, anchor="center")
        heading(box, "Checking your computer").pack()
        body(box, "Looking for SkillSpector and the tools it needs.", wrap=380).pack(pady=(6, 16))
        pb = ttk.Progressbar(box, mode="indeterminate", length=260)
        pb.pack()
        pb.start(12)

    def _check_job(self):
        self.q.put(("checked", core.check_status()))

    # ------------------------------------------------------------ missing
    def _build_missing(self, f):
        heading(f, "Set up SkillSpector").pack(anchor="w")
        body(f, "SkillSpector checks AI agent skills for risky or malicious content before you install them. "
                "It isn't on this computer yet. One click will install everything it needs.").pack(anchor="w", pady=(8, 18))
        table = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        table.pack(fill="x")
        self.dep_rows = {}
        for key, name, note in [("git", "Git", "Needed to download skills from GitHub"),
                                ("uv", "uv", "Python tool manager (installed automatically)"),
                                ("skillspector", "SkillSpector", "The scanner itself")]:
            row = tk.Frame(table, bg=WHITE)
            row.pack(fill="x", padx=14, pady=10)
            badge = tk.Label(row, text="–", width=3, bg="#FFF1D0", fg="#6B4400", font=(FONT, 11, "bold"))
            badge.pack(side="left")
            col = tk.Frame(row, bg=WHITE)
            col.pack(side="left", padx=12)
            tk.Label(col, text=name, bg=WHITE, fg=INK, font=(FONT, 11, "bold"), anchor="w").pack(anchor="w")
            tk.Label(col, text=note, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w").pack(anchor="w")
            st = tk.Label(row, text="Will install", bg=WHITE, fg="#6B4400", font=(FONT, 9, "bold"))
            st.pack(side="right")
            self.dep_rows[key] = (badge, st)
        info = tk.Label(f, text="Needs an internet connection and may take a few minutes. "
                                "You don't need to open a command window.", bg="#E3F1EE", fg="#124E45",
                        font=(FONT, 9), justify="left", anchor="w", wraplength=620, padx=14, pady=12)
        info.pack(fill="x", pady=18)
        row = tk.Frame(f, bg=WHITE)
        row.pack(side="bottom", fill="x")
        flat_button(row, "Install SkillSpector", self.start_install).pack(side="left")
        tk.Label(row, text="Installs for your account only. No admin rights needed\n(Git may ask for permission).",
                 bg=WHITE, fg=MUTED, font=(FONT, 9), justify="left").pack(side="left", padx=14)

    def _refresh_deps(self):
        for key, (badge, st) in self.dep_rows.items():
            ok = bool(self.status.get(key))
            badge.configure(text="✓" if ok else "–", bg="#E3F1EE" if ok else "#FFF1D0",
                            fg="#124E45" if ok else "#6B4400")
            st.configure(text="Found" if ok else "Will install", fg="#124E45" if ok else "#6B4400")

    # ------------------------------------------------------------ installing
    def _build_installing(self, f):
        self.inst_title = heading(f, "Installing…")
        self.inst_title.pack(anchor="w")
        self.inst_sub = body(f, "Please keep this window open.")
        self.inst_sub.pack(anchor="w", pady=(6, 14))
        self.inst_bar = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.inst_bar.pack(fill="x")
        self.inst_steps_frame = tk.Frame(f, bg=WHITE)
        self.inst_steps_frame.pack(fill="x", pady=14)
        tk.Label(f, text="DETAILS", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        box, self.inst_log = log_box(f, 8)
        box.pack(fill="both", expand=True, pady=(4, 10))
        self.inst_buttons = tk.Frame(f, bg=WHITE)
        self.inst_buttons.pack(fill="x")
        self.inst_step_labels = []

    def start_install(self):
        steps = core.install_plan(self.status)
        self.install_steps = steps
        for w in self.inst_steps_frame.winfo_children():
            w.destroy()
        for w in self.inst_buttons.winfo_children():
            w.destroy()
        self.inst_step_labels = []
        for s in steps:
            lab = tk.Label(self.inst_steps_frame, text="○  " + s, bg=WHITE, fg=MUTED, font=(FONT, 10), anchor="w")
            lab.pack(anchor="w", pady=2)
            self.inst_step_labels.append(lab)
        self.inst_log.configure(state="normal")
        self.inst_log.delete("1.0", "end")
        self.inst_log.configure(state="disabled")
        self.inst_title.configure(text="Installing…")
        self.inst_sub.configure(text="Please keep this window open.", fg="#3A3F3C")
        self.inst_bar.configure(value=0)
        self.holder = {}
        self.show("installing")

        def job():
            ok, msg = core.install_all(
                self.status, lambda i: self.q.put(("istep", i)), lambda l: self.q.put(("ilog", l)), self.holder)
            self.q.put(("idone", (ok, msg)))
        threading.Thread(target=job, daemon=True).start()

    def _on_istep(self, i):
        n = len(self.inst_step_labels)
        for k, lab in enumerate(self.inst_step_labels):
            if k < i:
                lab.configure(text="✓  " + self.install_steps[k], fg="#124E45")
            elif k == i:
                lab.configure(text="●  " + self.install_steps[k], fg=INK, font=(FONT, 10, "bold"))
        self.inst_bar.configure(value=int(100 * i / max(n, 1)) + 5)

    def _on_idone(self, res):
        ok, msg = res
        if ok:
            self.inst_bar.configure(value=100)
            self.status = core.check_status()
            self.show("ready")
            self._update_scan_button()
            return
        self.inst_title.configure(text="Something went wrong")
        self.inst_sub.configure(text=msg, fg="#8E1B14")
        for w in self.inst_buttons.winfo_children():
            w.destroy()
        flat_button(self.inst_buttons, "Try again", self.start_install).pack(side="left")
        flat_button(self.inst_buttons, "Copy details", lambda: self._copy(self.inst_log.get("1.0", "end")),
                    primary=False).pack(side="left", padx=10)
        if "git-scm.com" in msg:
            flat_button(self.inst_buttons, "Open Git download page",
                        lambda: webbrowser.open(core.GIT_DOWNLOAD_URL), primary=False).pack(side="left")

    # ------------------------------------------------------------ choose
    def _build_ready(self, f):
        top = tk.Frame(f, bg=WHITE)
        top.pack(fill="x")
        heading(top, "What do you want to scan?").pack(anchor="w", side="left")
        tk.Label(top, text="  ✓ SkillSpector ready  ", bg="#E3F1EE", fg="#124E45", font=(FONT, 9, "bold")).pack(side="right")
        body(f, "Pick a skill you downloaded, or paste a link to one on GitHub.").pack(anchor="w", pady=(6, 14))

        pills = tk.Frame(f, bg=WHITE)
        pills.pack(fill="x")
        self.pill_buttons = {}
        for k in KINDS:
            b = Button(pills, text=k[1], relief="flat", bd=0, cursor="hand2", font=(FONT, 10, "bold"),
                          padx=16, pady=7, command=lambda key=k[0]: self.set_kind(key), highlightthickness=1)
            b.pack(side="left", padx=(0, 8))
            self.pill_buttons[k[0]] = b

        self.in_label = tk.Label(f, bg=WHITE, fg=INK, font=(FONT, 10, "bold"), anchor="w")
        self.in_label.pack(fill="x", pady=(18, 4))
        row = tk.Frame(f, bg=WHITE)
        row.pack(fill="x")
        self.entry = tk.Entry(row, textvariable=self.target, font=(FONT, 11), relief="flat",
                              highlightthickness=1, highlightbackground="#8D918B", highlightcolor=ACCENT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.browse_btn = flat_button(row, "Browse…", self.browse, primary=False)
        self.browse_btn.pack(side="left", padx=(10, 0))
        self.in_hint = tk.Label(f, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w")
        self.in_hint.pack(fill="x", pady=(4, 0))

        opt = tk.Frame(f, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        opt.pack(fill="x", pady=16)
        cb = tk.Checkbutton(opt, text="Quick scan (no account needed)", variable=self.quick, bg=WHITE,
                            activebackground=WHITE, font=(FONT, 10, "bold"), anchor="w", command=self._toggle_ai)
        cb.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(opt, text="Fast built-in checks. Turn off to add AI review, which can catch risky instructions "
                           "written in plain language but needs an API key.", bg=WHITE, fg=MUTED,
                 font=(FONT, 9), wraplength=600, justify="left", anchor="w").pack(fill="x", padx=36, pady=(0, 10))
        self.ai_frame = tk.Frame(opt, bg=WHITE)
        tk.Label(self.ai_frame, text="AI provider", bg=WHITE, font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Combobox(self.ai_frame, textvariable=self.provider, values=["OpenAI"], state="readonly", width=14).grid(
            row=1, column=0, padx=(0, 12), pady=(2, 12))
        tk.Label(self.ai_frame, text="API key (used for this scan only, never saved)", bg=WHITE,
                 font=(FONT, 9, "bold")).grid(row=0, column=1, sticky="w")
        tk.Entry(self.ai_frame, textvariable=self.api_key, show="•", width=44, font=(FONT, 10)).grid(
            row=1, column=1, sticky="w", pady=(2, 12), ipady=3)

        self.err_var = tk.StringVar()
        tk.Label(f, textvariable=self.err_var, bg=WHITE, fg="#8E1B14", font=(FONT, 9), anchor="w").pack(fill="x")
        bottom = tk.Frame(f, bg=WHITE)
        bottom.pack(side="bottom", fill="x")
        self.scan_btn = flat_button(bottom, "Scan", self.start_scan)
        self.scan_btn.pack(side="left")
        self.scan_hint = tk.Label(bottom, text="Choose or paste something to scan first.", bg=WHITE, fg=MUTED,
                                  font=(FONT, 9))
        self.scan_hint.pack(side="left", padx=12)
        self.set_kind("folder")

    def _toggle_ai(self):
        if self.quick.get():
            self.ai_frame.pack_forget()
        else:
            self.ai_frame.pack(fill="x", padx=36, pady=(0, 4))

    def set_kind(self, key):
        self.kind = key
        info = next(k for k in KINDS if k[0] == key)
        for k, b in self.pill_buttons.items():
            on = k == key
            b.configure(bg=ACCENT if on else WHITE, fg=WHITE if on else INK, activebackground=ACCENT_DARK if on else "#EEF0EB",
                        activeforeground=WHITE if on else INK, highlightbackground=ACCENT if on else "#8D918B")
        self.in_label.configure(text=info[2])
        self.in_hint.configure(text=info[3] + "   Example: " + info[5])
        if key == "git":
            self.browse_btn.pack_forget()
        else:
            self.browse_btn.configure(text=info[4])
            self.browse_btn.pack(side="left", padx=(10, 0))
        self.target.set("")
        self.err_var.set("")

    def browse(self):
        if self.kind == "folder":
            p = filedialog.askdirectory(title="Choose the skill folder")
        elif self.kind == "zip":
            p = filedialog.askopenfilename(title="Choose a zip file", filetypes=[("Zip files", "*.zip")])
        else:
            p = filedialog.askopenfilename(title="Choose SKILL.md", filetypes=[("Markdown", "*.md"), ("All files", "*.*")])
        if p:
            self.target.set(os.path.normpath(p))

    def _update_scan_button(self):
        has = bool(self.target.get().strip())
        if has:
            self.scan_btn.configure(state="normal", bg=ACCENT, cursor="hand2")
            self.scan_hint.configure(text="")
        else:
            self.scan_btn.configure(state="disabled", bg="#D9DBD5", cursor="arrow", disabledforeground="#4A4F4B")
            self.scan_hint.configure(text="Choose or paste something to scan first.")

    # ------------------------------------------------------------ scanning
    def _build_scanning(self, f):
        heading(f, "Scanning…").pack(anchor="w")
        self.scan_target_lbl = body(f, "", wrap=640)
        self.scan_target_lbl.pack(anchor="w", pady=(6, 14))
        ttk.Progressbar(f, mode="indeterminate", length=300).pack(fill="x")
        f.winfo_children()[-1].start(12)
        tk.Label(f, text="LIVE OUTPUT", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w", pady=(16, 0))
        box, self.scan_log = log_box(f, 10)
        box.pack(fill="both", expand=True, pady=(4, 10))
        flat_button(f, "Cancel", self.cancel_scan, primary=False).pack(anchor="w")

    def start_scan(self):
        t = self.target.get().strip()
        err = core.validate_target(self.kind, t)
        if err:
            self.err_var.set(err)
            return
        if self.kind == "git" and not self.status.get("git"):
            messagebox.showwarning("Git needed", "Scanning a GitHub link needs Git. Install Git from\n" + core.GIT_DOWNLOAD_URL)
            return
        if not self.quick.get() and not self.api_key.get().strip():
            self.err_var.set("Enter an API key, or turn Quick scan back on.")
            return
        self.err_var.set("")
        self.last_target = t
        self.scan_target_lbl.configure(text=t)
        self.scan_log.configure(state="normal")
        self.scan_log.delete("1.0", "end")
        self.scan_log.configure(state="disabled")
        self.holder = {}
        self.show("scanning")
        ss = self.status.get("skillspector") or core.find_skillspector()
        quick, prov, key = self.quick.get(), self.provider.get(), self.api_key.get().strip()

        def job():
            res = core.run_scan(ss, t, quick, prov, key, lambda l: self.q.put(("slog", l)), self.holder)
            self.q.put(("sdone", res))
        threading.Thread(target=job, daemon=True).start()

    def cancel_scan(self):
        self.holder["cancelled"] = True
        core.kill_tree(self.holder.get("proc"))

    # ------------------------------------------------------------ results
    def _build_results(self, f):
        self.banner = tk.Frame(f, bg="#FBEAE8")
        self.banner.pack(fill="x")
        self.banner_title = tk.Label(self.banner, font=(FONT, 16, "bold"), anchor="w", bg="#FBEAE8")
        self.banner_title.pack(fill="x", padx=18, pady=(12, 0))
        self.banner_sub = tk.Label(self.banner, font=(FONT, 10), anchor="w", bg="#FBEAE8")
        self.banner_sub.pack(fill="x", padx=18, pady=(0, 12))
        mid = tk.Frame(f, bg=WHITE)
        mid.pack(fill="x", pady=10)
        self.counts_lbl = tk.Label(mid, bg=WHITE, fg=INK, font=(FONT, 10, "bold"))
        self.counts_lbl.pack(side="left")
        self.filter_frame = tk.Frame(mid, bg=WHITE)
        self.filter_frame.pack(side="right")
        self.filter_btns = {}
        for name in ("All", "High", "Medium", "Low"):
            b = Button(self.filter_frame, text=name, relief="flat", bd=0, cursor="hand2", font=(FONT, 9, "bold"),
                          padx=12, pady=4, highlightthickness=1, command=lambda n=name: self.set_filter(n))
            b.pack(side="left", padx=3)
            self.filter_btns[name] = b
        self.res_target = tk.Label(f, bg=WHITE, fg=MUTED, font=(FONT, 8), anchor="w", wraplength=640, justify="left")
        self.res_target.pack(fill="x")
        bottom = tk.Frame(f, bg=WHITE)
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        flat_button(bottom, "Scan another", self.scan_another).pack(side="left")
        flat_button(bottom, "Save report (.md)", self.save_md, primary=False).pack(side="left", padx=8)
        flat_button(bottom, "Save as JSON", self.save_json, primary=False).pack(side="left")
        self.list_area = ScrollFrame(f)
        self.list_area.pack(fill="both", expand=True, pady=(6, 0))

    def show_results(self, res):
        self.scan_result = res
        self.res_target.configure(text="Scanned: " + self.last_target)
        self.findings = core.parse_findings(res["report"]) if res["report"] is not None else None
        if self.findings is not None:
            counts = core.count_by_severity(self.findings)
            self.recommendation, _score = core.risk_summary(res["report"])
            lab, expl, level = core.verdict(counts, self.recommendation)
            note = core.incomplete_note(res["report"])
            if note:
                expl += "  " + note
            bg, fg = {"bad": ("#FBEAE8", "#8E1B14"), "warn": ("#FFF1D0", "#6B4400"), "ok": ("#E3F1EE", "#124E45")}[level]
            self.counts_lbl.configure(text="High %d   ·   Medium %d   ·   Low %d" % (counts["High"], counts["Medium"], counts["Low"]))
        else:
            self.recommendation = None
            lab, expl, bg, fg = ("Scan finished", "The report format wasn't recognised, so the raw report is shown below.",
                                 "#FFF1D0", "#6B4400")
            self.counts_lbl.configure(text="")
        self.banner.configure(bg=bg)
        for w, t in ((self.banner_title, lab), (self.banner_sub, expl)):
            w.configure(bg=bg, fg=fg, text=t)
        self.filter = "All"
        self.render_findings()
        self.show("results")

    def set_filter(self, name):
        self.filter = name
        self.render_findings()

    def render_findings(self):
        for n, b in self.filter_btns.items():
            on = n == self.filter
            b.configure(bg=INK if on else WHITE, fg=WHITE if on else INK, activebackground=INK if on else "#EEF0EB",
                        activeforeground=WHITE if on else INK, highlightbackground=INK if on else "#8D918B")
        inner = self.list_area.inner
        for w in inner.winfo_children():
            w.destroy()
        if self.findings is None:
            t = tk.Text(inner, height=18, font=(MONO, 9), wrap="word", relief="flat", bg="#F4F5F2")
            t.insert("1.0", (self.scan_result or {}).get("raw_text", ""))
            t.configure(state="disabled")
            t.pack(fill="both", expand=True, padx=2, pady=4)
            return
        shown = [f for f in self.findings if self.filter in ("All", f["severity"])]
        if not shown:
            tk.Label(inner, text="Nothing to show here.", bg=WHITE, fg=MUTED, font=(FONT, 10)).pack(pady=20)
        for f in shown:
            card = tk.Frame(inner, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
            card.pack(fill="x", pady=5, padx=2)
            head = tk.Frame(card, bg=WHITE)
            head.pack(fill="x", padx=14, pady=(10, 2))
            bg, fg = SEV_COLORS[f["severity"]]
            tk.Label(head, text=" %s " % f["severity"].upper(), bg=bg, fg=fg, font=(FONT, 8, "bold")).pack(side="left")
            tk.Label(head, text=f["title"], bg=WHITE, fg=INK, font=(FONT, 10, "bold"), wraplength=520,
                     justify="left", anchor="w").pack(side="left", padx=10)
            if f["description"]:
                tk.Label(card, text=f["description"], bg=WHITE, fg="#3A3F3C", font=(FONT, 9), wraplength=600,
                         justify="left", anchor="w").pack(fill="x", padx=14, pady=2)
            if f["where"]:
                tk.Label(card, text=f["where"], bg=WHITE, fg=MUTED, font=(MONO, 8), anchor="w").pack(
                    fill="x", padx=14, pady=(0, 10))
            else:
                tk.Frame(card, bg=WHITE, height=8).pack()

    def scan_another(self):
        self.target.set("")
        self.show("ready")
        self._update_scan_button()

    def save_md(self):
        if self.findings is None:
            self.save_json()
            return
        p = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md")],
                                         initialfile="skillspector-report.md")
        if p:
            counts = core.count_by_severity(self.findings)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(core.to_markdown(self.last_target, self.findings, counts, self.recommendation))

    def save_json(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                         initialfile="skillspector-report.json")
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write((self.scan_result or {}).get("raw_text", ""))

    # ------------------------------------------------------------ plumbing
    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_scan_done(self, res):
        if res["ok"]:
            self.show_results(res)
            return
        self.show("ready")
        self._update_scan_button()
        if res.get("error") == "Cancelled.":
            self.err_var.set("Scan cancelled.")
        else:
            self.err_var.set(res.get("error") or "The scan failed.")
            messagebox.showerror("Scan failed", (res.get("error") or "") + "\n\n" + (res.get("log") or "")[-1500:])

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "checked":
                    self.status = val
                    if val.get("skillspector"):
                        self.show("ready")
                        self._update_scan_button()
                    else:
                        self._refresh_deps()
                        self.show("missing")
                elif kind == "istep":
                    self._on_istep(val)
                elif kind == "ilog":
                    append_text(self.inst_log, val)
                elif kind == "idone":
                    self._on_idone(val)
                elif kind == "slog":
                    append_text(self.scan_log, val)
                elif kind == "sdone":
                    self._on_scan_done(val)
        except queue.Empty:
            pass
        self.after(80, self._poll)


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
