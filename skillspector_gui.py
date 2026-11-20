"""SkillSpector Scanner - a simple window for NVIDIA's SkillSpector.

Detects SkillSpector (installs it if missing), lets you pick a skill to scan,
runs the scan in the background and shows the results.

Rounded buttons / inputs / cards are drawn on Canvas, so they look the same on
Windows, macOS and Linux (tk.Button ignores colours on macOS).
"""
import os
import queue
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import ss_core as core
import ss_groups

# ---- design tokens (from the design prototype)
ACCENT = "#0F7B6C"
ACCENT_DARK = "#0B5F54"
INK = "#16181A"
BODY = "#3A3F3C"
MUTED = "#5A5F5B"
LINE = "#D9DBD5"
BORDER = "#8D918B"
RAIL_BG = "#F4F5F2"
TRACK = "#E4E6E1"
HOVER = "#EEF0EB"
WHITE = "#FFFFFF"
OK_BG, OK_FG = "#E3F1EE", "#124E45"
WARN_BG, WARN_FG = "#FFF1D0", "#6B4400"
BAD_BG, BAD_FG = "#FBEAE8", "#8E1B14"
SEV_COLORS = {"Critical": ("#8E1B14", "#FFFFFF"), "High": (BAD_BG, BAD_FG), "Medium": (WARN_BG, WARN_FG),
              "Low": ("#E6EDF8", "#1B3F7A")}
LEVELS = {  # verdict level -> (background, title colour, subtitle colour)
    "bad": (BAD_BG, BAD_FG, "#5B1712"),
    "warn": (WARN_BG, WARN_FG, "#4A2F00"),
    "ok": (OK_BG, OK_FG, "#0B3A33"),
}
BUSY = ("checking", "installing", "scanning")

IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"
FONT = "TkDefaultFont"
MONO = "TkFixedFont"


def pick_fonts(root):
    """Use the best available font (Inter if installed, else the system UI font)."""
    global FONT, MONO
    fams = set(tkfont.families(root))
    FONT = next((f for f in ("Inter", "Segoe UI", "Helvetica Neue", "DejaVu Sans") if f in fams), "TkDefaultFont")
    MONO = next((f for f in ("JetBrains Mono", "Consolas", "Menlo", "DejaVu Sans Mono") if f in fams), "TkFixedFont")


def example_path(name):
    base = "C:\\Users\\you\\Downloads\\" if IS_WIN else ("/Users/you/Downloads/" if IS_MAC else "/home/you/Downloads/")
    return base + name


KINDS = [
    ("folder", "Folder", "Skill folder", "The folder that contains SKILL.md.", "Browse folder…", example_path("my-skill")),
    ("file", "SKILL.md file", "Skill file", "A single SKILL.md file.", "Browse file…", example_path("SKILL.md")),
    ("zip", "Zip file", "Zip file", "A zipped skill package.", "Browse zip…", example_path("my-skill.zip")),
    ("git", "Git link", "Link to the skill on GitHub", "Paste the address of the repository.", "",
     "https://github.com/user/my-skill"),
]


# ---------------------------------------------------------------- drawing helpers

def rrect(c, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle on a canvas."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def rrect_border(c, x1, y1, x2, y2, r, fill, outline, **kw):
    """Rounded rect with a crisp 1px border (two stacked fills; polygon outlines render jagged)."""
    if outline and outline != fill:
        rrect(c, x1, y1, x2, y2, r, fill=outline, outline=outline, **kw)
        rrect(c, x1 + 1, y1 + 1, x2 - 1, y2 - 1, max(r - 1, 0), fill=fill, outline=fill, **kw)
    else:
        rrect(c, x1, y1, x2, y2, r, fill=fill, outline=fill, **kw)


def shield(c, x, y, size, color, glyph=None, width=2):
    """Shield icon (24-unit design grid scaled to `size`). glyph: 'check' | 'alert' | None."""
    k = size / 24.0
    pts = [(12, 3), (20, 6), (20, 12), (17.5, 17.5), (12, 21), (6.5, 17.5), (4, 12), (4, 6)]
    flat = [v for px, py in pts for v in (x + px * k, y + py * k)]
    c.create_polygon(flat, outline=color, fill="", width=width, joinstyle="round")
    if glyph == "check":
        c.create_line(x + 8.5 * k, y + 12 * k, x + 11 * k, y + 14.5 * k, x + 15.5 * k, y + 10 * k,
                      fill=color, width=width, capstyle="round", joinstyle="round")
    elif glyph == "alert":
        c.create_line(x + 12 * k, y + 8 * k, x + 12 * k, y + 13 * k, fill=color, width=width, capstyle="round")
        c.create_line(x + 12 * k, y + 16.3 * k, x + 12 * k, y + 16.6 * k, fill=color, width=width, capstyle="round")


class RButton(tk.Canvas):
    """Rounded, flat button drawn on a canvas (same look on every OS)."""

    def __init__(self, parent, text, command=None, height=44, radius=8, padx=22, size=10, bold=True,
                 bg=ACCENT, fg=WHITE, border=None, hover=None, pbg=WHITE):
        self._rb_font = tkfont.Font(family=FONT, size=size, weight="bold" if bold else "normal")
        self._rb_text, self._rb_cmd = text, command
        self._rb_r, self._rb_px, self._rb_minh = radius, padx, height
        self._rb_c = {"bg": bg, "fg": fg, "border": border, "hover": hover}
        self._rb_on, self._rb_over = True, False
        super().__init__(parent, bg=pbg, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._rb_resize()
        self.bind("<Enter>", lambda e: self._rb_hover(True))
        self.bind("<Leave>", lambda e: self._rb_hover(False))
        self.bind("<ButtonRelease-1>", self._rb_release)
        self.bind("<Return>", lambda e: self._rb_fire())
        self.bind("<space>", lambda e: self._rb_fire())

    def _rb_resize(self):
        w = self._rb_font.measure(self._rb_text) + 2 * self._rb_px
        h = max(self._rb_minh, self._rb_font.metrics("linespace") + 16)
        self._rb_wh = (w, h)
        self.configure(width=w, height=h)
        self._rb_draw()

    def _rb_draw(self):
        self.delete("all")
        w, h = self._rb_wh
        c = self._rb_c
        if self._rb_on:
            fill = c["hover"] if (self._rb_over and c["hover"]) else c["bg"]
            fg, outline = c["fg"], c["border"] or fill
        else:
            fill, fg, outline = LINE, "#4A4F4B", LINE
        rrect_border(self, 0, 0, w - 1, h - 1, self._rb_r, fill, outline if outline != fill else None)
        self.create_text(w / 2, h / 2, text=self._rb_text, fill=fg, font=self._rb_font)

    def _rb_hover(self, over):
        self._rb_over = over
        self._rb_draw()

    def _rb_release(self, e):
        w, h = self._rb_wh
        if 0 <= e.x <= w and 0 <= e.y <= h:
            self._rb_fire()

    def _rb_fire(self):
        if self._rb_on and self._rb_cmd:
            self._rb_cmd()

    # public API
    def restyle(self, **kw):
        self._rb_c.update({k: v for k, v in kw.items() if k in self._rb_c})
        self._rb_draw()

    def set_enabled(self, on):
        self._rb_on = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._rb_draw()

    def set_text(self, text):
        self._rb_text = text
        self._rb_resize()

    def set_command(self, cmd):
        self._rb_cmd = cmd


def primary_button(parent, text, command, height=46, padx=26, **kw):
    return RButton(parent, text, command, height=height, size=11, padx=padx, bg=ACCENT, fg=WHITE,
                   hover=ACCENT_DARK, **kw)


def secondary_button(parent, text, command, height=44, padx=18, **kw):
    return RButton(parent, text, command, height=height, size=10, padx=padx, bg=WHITE, fg=INK, border=BORDER,
                   hover=HOVER, **kw)


def pill_button(parent, text, command, height=40, size=10, padx=18):
    return RButton(parent, text, command, height=height, radius=height // 2, size=size, padx=padx,
                   bg=WHITE, fg=INK, border=BORDER, hover=HOVER)


def style_pill(btn, on, dark=False):
    col = INK if dark else ACCENT
    if on:
        btn.restyle(bg=col, fg=WHITE, border=col, hover=col)
    else:
        btn.restyle(bg=WHITE, fg=INK, border=BORDER, hover=HOVER)


class RBox(tk.Canvas):
    """A rounded, bordered container. Put children in `.inner`."""

    def __init__(self, parent, fill=WHITE, outline=LINE, radius=8, pad=0, pbg=WHITE, width=None, height=None):
        super().__init__(parent, bg=pbg, highlightthickness=0, bd=0, width=width or 4, height=height or 4)
        self._rx_fill, self._rx_out, self._rx_r, self._rx_pad = fill, outline, radius, pad
        self._rx_fixh = height
        self._rx_size = (4, 4)
        # outer frame fills the canvas (1px inset keeps the border visible); inner carries the padding
        self._rx_outer = tk.Frame(self, bg=fill)
        self.inner = tk.Frame(self._rx_outer, bg=fill)
        self.inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._rx_win = self.create_window(1, 1, window=self._rx_outer, anchor="nw")
        self._rx_outer.bind("<Configure>", self._rx_inner)
        self.bind("<Configure>", self._rx_self)

    def _rx_inner(self, _):
        if not self._rx_fixh:
            h = self._rx_outer.winfo_reqheight() + 2
            if int(float(self.cget("height"))) != h:
                self.configure(height=h)

    def _rx_self(self, e):
        self._rx_size = (e.width, e.height)
        kw = {"width": max(e.width - 2, 1)}
        if self._rx_fixh:
            kw["height"] = max(e.height - 2, 1)
        self.itemconfigure(self._rx_win, **kw)
        self._rx_redraw()

    def _rx_redraw(self):
        w, h = self._rx_size
        self.delete("bg")
        rrect_border(self, 0, 0, w - 1, h - 1, self._rx_r, self._rx_fill, self._rx_out, tags="bg")
        self.tag_lower("bg")

    def set_colors(self, fill=None, outline=None):
        if fill:
            self._rx_fill = fill
            self._rx_outer.configure(bg=fill)
            self.inner.configure(bg=fill)
        if outline:
            self._rx_out = outline
        self._rx_redraw()


def entry_box(parent, var, height=46, show=None, placeholder="", size=11):
    """Rounded text input with placeholder. Returns (box, entry)."""
    box = RBox(parent, fill=WHITE, outline=BORDER, radius=8, height=height)
    e = tk.Entry(box.inner, textvariable=var, relief="flat", bd=0, highlightthickness=0, bg=WHITE, fg=INK,
                 insertbackground=INK, font=(FONT, size), show=show or "")
    e.pack(fill="x", expand=True, padx=14)
    ph = tk.Label(box.inner, text=placeholder, bg=WHITE, fg=BORDER, font=(FONT, size), anchor="w")
    ph.bind("<Button-1>", lambda _e: e.focus_set())

    def sync(*_):
        if var.get():
            ph.place_forget()
        else:
            ph.place(in_=e, x=0, y=0, relheight=1, relwidth=1)
            ph.lift()
    var.trace_add("write", sync)
    e.bind("<FocusIn>", lambda _e: box.set_colors(outline=ACCENT))
    e.bind("<FocusOut>", lambda _e: box.set_colors(outline=BORDER))
    box.set_placeholder = lambda t: (ph.configure(text=t), sync())
    sync()
    return box, e


class Bar(tk.Canvas):
    """8px rounded progress bar."""

    def __init__(self, parent, pbg=WHITE):
        super().__init__(parent, height=8, bg=pbg, highlightthickness=0, bd=0)
        self.val = 0
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, v):
        self.val = max(0, min(100, v))
        self._draw()

    def _draw(self):
        w = self.winfo_width()
        self.delete("all")
        rrect(self, 0, 0, w, 8, 4, fill=TRACK, outline=TRACK)
        if self.val > 0:
            rrect(self, 0, 0, max(8, w * self.val / 100.0), 8, 4, fill=ACCENT, outline=ACCENT)


class Spinner(tk.Canvas):
    def __init__(self, parent, size=44):
        super().__init__(parent, width=size, height=size, bg=WHITE, highlightthickness=0, bd=0)
        self.size, self.angle = size, 90
        self._tick()

    def _tick(self):
        if not self.winfo_exists():
            return
        if self.winfo_ismapped():
            s = self.size
            self.delete("all")
            self.create_oval(4, 4, s - 4, s - 4, outline=LINE, width=4)
            self.create_arc(4, 4, s - 4, s - 4, start=self.angle, extent=90, style="arc", outline=ACCENT, width=4)
            self.angle = (self.angle - 18) % 360
        self.after(40, self._tick)


def step_row(parent, text):
    """One step line with a round status icon. Returns (setter)."""
    row = tk.Frame(parent, bg=WHITE)
    row.pack(anchor="w", pady=6, fill="x")
    ic = tk.Canvas(row, width=24, height=24, bg=WHITE, highlightthickness=0, bd=0)
    ic.pack(side="left")
    lab = tk.Label(row, text=text, bg=WHITE, fg=MUTED, font=(FONT, 10), anchor="w")
    lab.pack(side="left", padx=12)

    def setter(state):  # 'done' | 'run' | 'todo'
        ic.delete("all")
        fill, fg, glyph = {"done": (OK_BG, OK_FG, "✓"), "run": (ACCENT, WHITE, "…"), "todo": (TRACK, "#4A4F4B", "")}[state]
        ic.create_oval(1, 1, 23, 23, fill=fill, outline=fill)
        ic.create_text(12, 11, text=glyph, fill=fg, font=(FONT, 9, "bold"))
        lab.configure(fg=INK if state != "todo" else MUTED, font=(FONT, 10, "bold" if state == "run" else "normal"))
    setter("todo")
    return setter


def heading(parent, text):
    return tk.Label(parent, text=text, font=(FONT, 18, "bold"), bg=WHITE, fg=INK, anchor="w")


def body(parent, text, wrap=560, fg=BODY, size=10):
    return tk.Label(parent, text=text, font=(FONT, size), bg=WHITE, fg=fg, anchor="w", justify="left",
                    wraplength=wrap)


def log_box(parent, height=8):
    outer = RBox(parent, fill=INK, outline=INK, radius=8, pad=1)
    frame = outer.inner
    t = tk.Text(frame, height=height, bg=INK, fg="#D8DCD6", font=(MONO, 9), relief="flat", bd=0,
                padx=12, pady=10, wrap="word", state="disabled", insertbackground="#D8DCD6")
    sb = ttk.Scrollbar(frame, command=t.yview)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    return outer, t


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
        # One window-wide binding: the list scrolls wherever the pointer is over it
        # (cards and labels included), not only over the scrollbar.
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", lambda e: self._scroll(-2, e), add="+")
        self.bind_all("<Button-5>", lambda e: self._scroll(2, e), add="+")

    def _over_me(self, e):
        if not self.winfo_ismapped():
            return False
        x, y = self.winfo_rootx(), self.winfo_rooty()
        return x <= e.x_root < x + self.winfo_width() and y <= e.y_root < y + self.winfo_height()

    def _scroll(self, step, e):
        if not self._over_me(e):
            return
        bbox = self.canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > self.canvas.winfo_height():  # only when there is more to see
            self.canvas.yview_scroll(step, "units")

    def _wheel(self, e):
        if e.delta:
            self._scroll(-e.delta if IS_MAC else (-1 if e.delta > 0 else 1) * 3 * max(1, abs(e.delta) // 120), e)


# ---------------------------------------------------------------- the app

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        pick_fonts(self)
        self.title("SkillSpector Scanner")
        self.geometry("960x680")
        self.minsize(900, 640)
        self.configure(bg=WHITE)
        self.q = queue.Queue()
        self.holder = {}
        self.status = {}
        self.kind = "folder"
        self.current = "checking"
        self.target = tk.StringVar()
        self.quick = tk.BooleanVar(value=True)
        self.api_key = tk.StringVar()
        self.provider = tk.StringVar(value="OpenAI")
        self.scan_result = None
        self.findings = None
        self.groups = []
        self.filter = "All"
        self.last_target = ""
        self.scan_started = time.monotonic()
        self.scan_root = None
        self.group_open = {}
        self._build()
        self.target.trace_add("write", lambda *a: self._update_scan_button())
        self.after(80, self._poll)
        self.show("checking")
        threading.Thread(target=self._check_job, daemon=True).start()

    # ------------------------------------------------------------ layout
    def _build(self):
        self.status_var = tk.StringVar(value="Checking your computer…")
        bar = tk.Frame(self, bg=RAIL_BG, height=32, highlightthickness=1, highlightbackground=LINE)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self.status_var, bg=RAIL_BG, fg="#4A4F4B", font=(FONT, 9)).pack(
            side="left", padx=16)
        tk.Label(bar, text="A clean result is not proof a skill is safe.", bg=RAIL_BG, fg="#4A4F4B",
                 font=(FONT, 9)).pack(side="right", padx=16)

        rail = tk.Frame(self, bg=RAIL_BG, width=210, highlightthickness=1, highlightbackground=LINE)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        head = tk.Frame(rail, bg=RAIL_BG)
        head.pack(fill="x", padx=20, pady=(26, 28))
        logo = tk.Canvas(head, width=20, height=20, bg=RAIL_BG, highlightthickness=0)
        logo.grid(row=0, column=0, padx=(0, 8))
        shield(logo, 0, 0, 20, ACCENT, "check", width=2)
        tk.Label(head, text="SkillSpector", bg=RAIL_BG, fg=INK, font=(FONT, 12, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w")
        tk.Label(head, text="AI Skill Security Scanner", bg=RAIL_BG, fg=MUTED, font=(FONT, 9), anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.rail_items = []
        for n, (label, sub) in enumerate([("Set up", "Install SkillSpector"), ("Choose", "What to scan"),
                                          ("Results", "Safe to install?")], 1):
            row = tk.Frame(rail, bg=RAIL_BG)
            row.pack(fill="x", padx=12, pady=2)
            inner = tk.Frame(row, bg=RAIL_BG)
            inner.pack(fill="x", padx=8, pady=8)
            c = tk.Canvas(inner, width=28, height=28, bg=RAIL_BG, highlightthickness=0)
            c.pack(side="left")
            txt = tk.Frame(inner, bg=RAIL_BG)
            txt.pack(side="left", padx=12)
            l1 = tk.Label(txt, text=label, bg=RAIL_BG, fg=INK, font=(FONT, 10), anchor="w")
            l1.pack(anchor="w")
            l2 = tk.Label(txt, text=sub, bg=RAIL_BG, fg=MUTED, font=(FONT, 9), anchor="w")
            l2.pack(anchor="w")
            item = {"n": n, "row": row, "inner": inner, "c": c, "txt": txt, "l1": l1, "l2": l2}
            self.rail_items.append(item)
            for w in (row, inner, c, txt, l1, l2):
                w.bind("<Button-1>", lambda e, n=n: self.go_step(n))
                w.bind("<Enter>", lambda e, it=item: self._rail_hover(it, True))
                w.bind("<Leave>", lambda e, it=item: self._rail_hover(it, False))
        tk.Label(rail, text="Scans only read the files. Nothing from the skill is run on your computer.",
                 bg=RAIL_BG, fg=MUTED, font=(FONT, 9), justify="left", anchor="w", wraplength=170).pack(
            side="bottom", fill="x", padx=20, pady=20)

        self.main = tk.Frame(self, bg=WHITE)
        self.main.pack(side="left", fill="both", expand=True, padx=44, pady=34)
        self.screens = {}
        for name in ("checking", "setup", "installing", "ready", "scanning", "results"):
            self.screens[name] = tk.Frame(self.main, bg=WHITE)
        self._build_checking(self.screens["checking"])
        self._build_setup(self.screens["setup"])
        self._build_installing(self.screens["installing"])
        self._build_ready(self.screens["ready"])
        self._build_scanning(self.screens["scanning"])
        self._build_results(self.screens["results"])

    # ---- rail
    def _rail_enabled(self, n):
        if self.current in BUSY:
            return False
        if n == 2:
            return bool(self.status.get("skillspector"))
        if n == 3:
            return bool(self.scan_result and self.scan_result.get("ok"))
        return True

    def _rail_hover(self, item, over):
        bg = HOVER if (over and self._rail_enabled(item["n"])) else RAIL_BG
        for k in ("row", "inner", "c", "txt", "l1", "l2"):
            item[k].configure(bg=bg)

    def _refresh_rail(self):
        step = {"checking": 1, "setup": 1, "installing": 1, "ready": 2, "scanning": 2, "results": 3}[self.current]
        for it in self.rail_items:
            n = it["n"]
            done, active = n < step, n == step
            on = self._rail_enabled(n)
            fill = OK_FG if done else (ACCENT if active else TRACK)
            fg = WHITE if (done or active) else BODY
            c = it["c"]
            c.delete("all")
            c.create_oval(1, 1, 27, 27, fill=fill, outline=fill)
            c.create_text(14, 14, text="✓" if done else str(n), fill=fg, font=(FONT, 10, "bold"))
            it["l1"].configure(font=(FONT, 10, "bold" if active else "normal"), fg=INK if (on or active) else "#8A8F89")
            it["l2"].configure(fg=MUTED if (on or active) else "#9A9F99")
            cur = "hand2" if on else "arrow"
            for k in ("row", "inner", "c", "txt", "l1", "l2"):
                it[k].configure(cursor=cur, bg=RAIL_BG)

    def go_step(self, n):
        if not self._rail_enabled(n):
            return
        if n == 1:
            self.open_setup()
        elif n == 2:
            self.show("ready")
            self._update_scan_button()
        else:
            self.show("results")

    def show(self, name):
        for f in self.screens.values():
            f.pack_forget()
        self.screens[name].pack(fill="both", expand=True)
        self.current = name
        if name == "setup":
            self._refresh_deps()
        if name == "ready":
            self.entry.focus_set()
        self._refresh_rail()
        texts = {"checking": "Checking your computer…", "installing": "Installing…", "ready": "SkillSpector is ready",
                 "scanning": "Scanning…", "results": "Scan complete"}
        if name == "setup":
            texts["setup"] = "SkillSpector is ready" if self._all_ok() else "SkillSpector is not installed"
        self.status_var.set(texts[name])

    # ------------------------------------------------------------ checking
    def _build_checking(self, f):
        box = tk.Frame(f, bg=WHITE)
        box.place(relx=0.5, rely=0.45, anchor="center")
        Spinner(box).pack(pady=(0, 18))
        tk.Label(box, text="Checking your computer", font=(FONT, 16, "bold"), bg=WHITE, fg=INK).pack()
        body(box, "Looking for SkillSpector and the tools it needs. This takes a few seconds.", wrap=360).pack(
            pady=(8, 0))

    def _check_job(self):
        self.q.put(("checked", core.check_status()))

    # ------------------------------------------------------------ set up (missing / all installed)
    def _build_setup(self, f):
        self.setup_title = heading(f, "Set up SkillSpector")
        self.setup_title.pack(anchor="w")
        self.setup_sub = body(f, "", wrap=520)
        self.setup_sub.pack(anchor="w", pady=(8, 20))

        table = RBox(f, fill=WHITE, outline=LINE, radius=8)
        table.pack(fill="x")
        self.dep_rows = {}
        items = [("git", "Git", "Needed to download skills from GitHub"),
                 ("uv", "uv", "Python tool manager (installed automatically)"),
                 ("skillspector", "SkillSpector", "The scanner itself")]
        for i, (key, name, note) in enumerate(items):
            if i:
                tk.Frame(table.inner, bg="#E8EAE5", height=1).pack(fill="x")
            row = tk.Frame(table.inner, bg=WHITE)
            row.pack(fill="x", padx=16, pady=12)
            badge = tk.Canvas(row, width=28, height=28, bg=WHITE, highlightthickness=0)
            badge.pack(side="left")
            col = tk.Frame(row, bg=WHITE)
            col.pack(side="left", padx=12)
            tk.Label(col, text=name, bg=WHITE, fg=INK, font=(FONT, 10, "bold"), anchor="w").pack(anchor="w")
            tk.Label(col, text=note, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w").pack(anchor="w")
            st = tk.Label(row, text="", bg=WHITE, font=(FONT, 9, "bold"))
            st.pack(side="right")
            self.dep_rows[key] = (badge, st)

        self.setup_note_box = RBox(f, fill=OK_BG, outline=OK_BG, radius=8, pad=16)
        self.setup_note_box.pack(fill="x", pady=20)
        self.setup_note = tk.Label(self.setup_note_box.inner, text="", bg=OK_BG, fg=OK_FG, font=(FONT, 10),
                                   justify="left", anchor="w", wraplength=560)
        self.setup_note.pack(fill="x", pady=0)

        row = tk.Frame(f, bg=WHITE)
        row.pack(side="bottom", fill="x")
        self.setup_btn = primary_button(row, "Install SkillSpector", self.start_install)
        self.setup_btn.pack(side="left")
        self.recheck_btn = secondary_button(row, "Check again", self.open_setup, height=46)
        self.setup_hint = tk.Label(row, text="", bg=WHITE, fg=MUTED, font=(FONT, 9), justify="left")
        self.setup_hint.pack(side="left", padx=14)

    def _all_ok(self):
        return all(self.status.get(k) for k in ("git", "uv", "skillspector"))

    def _refresh_deps(self):
        for key, (badge, st) in self.dep_rows.items():
            ok = bool(self.status.get(key))
            fill, fg = (OK_BG, OK_FG) if ok else (WARN_BG, WARN_FG)
            badge.delete("all")
            badge.create_oval(1, 1, 27, 27, fill=fill, outline=fill)
            badge.create_text(14, 14, text="✓" if ok else "–", fill=fg, font=(FONT, 11, "bold"))
            st.configure(text="Found" if ok else "Will install", fg=fg)
        if self._all_ok():
            self.setup_title.configure(text="SkillSpector is set up")
            self.setup_sub.configure(text="Everything SkillSpector needs is installed on this computer.")
            self.setup_note_box.set_colors(fill=OK_BG, outline=OK_BG)
            self.setup_note.configure(bg=OK_BG, fg=OK_FG, text="All set. You can scan a skill now. "
                                      "If you just installed or removed something yourself, press Check again.")
            self.setup_btn.set_text("Choose what to scan")
            self.setup_btn.set_command(lambda: (self.show("ready"), self._update_scan_button()))
            self.setup_hint.pack_forget()
            self.recheck_btn.pack(side="left", padx=(10, 0))
        else:
            self.setup_title.configure(text="Set up SkillSpector")
            self.setup_sub.configure(text="SkillSpector checks AI agent skills for risky or malicious content "
                                          "before you install them. One click will install everything it needs.")
            self.setup_note_box.set_colors(fill=OK_BG, outline=OK_BG)
            self.setup_note.configure(bg=OK_BG, fg=OK_FG, text="Needs an internet connection and may take a few "
                                      "minutes. The missing items above will be installed automatically. You don't "
                                      "need to open a command window.")
            self.setup_btn.set_text("Install SkillSpector")
            self.setup_btn.set_command(self.start_install)
            self.recheck_btn.pack_forget()
            self.setup_hint.configure(text="Installs for your account only. No admin rights needed\n"
                                           "(Git may ask for permission).")
            self.setup_hint.pack(side="left", padx=14)

    def open_setup(self):
        """Show the set-up page and re-check what is installed in the background."""
        self.show("setup")
        threading.Thread(target=lambda: self.q.put(("rechecked", core.check_status())), daemon=True).start()

    # ------------------------------------------------------------ installing
    def _build_installing(self, f):
        self.inst_title = heading(f, "Installing…")
        self.inst_title.pack(anchor="w")
        self.inst_sub = body(f, "Please keep this window open.")
        self.inst_sub.pack(anchor="w", pady=(8, 18))
        self.inst_bar = Bar(f)
        self.inst_bar.pack(fill="x")
        self.inst_steps_frame = tk.Frame(f, bg=WHITE)
        self.inst_steps_frame.pack(fill="x", pady=16)
        tk.Label(f, text="DETAILS", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        box, self.inst_log = log_box(f, 8)
        box.pack(fill="both", expand=True, pady=(6, 12))
        self.inst_buttons = tk.Frame(f, bg=WHITE)
        self.inst_buttons.pack(fill="x")
        self.inst_setters = []

    def start_install(self):
        steps = core.install_plan(self.status)
        self.install_steps = steps
        for w in self.inst_steps_frame.winfo_children():
            w.destroy()
        for w in self.inst_buttons.winfo_children():
            w.destroy()
        self.inst_setters = [step_row(self.inst_steps_frame, s) for s in steps]
        self.inst_log.configure(state="normal")
        self.inst_log.delete("1.0", "end")
        self.inst_log.configure(state="disabled")
        self.inst_title.configure(text="Installing…")
        self.inst_sub.configure(text="Please keep this window open.", fg=BODY)
        self.inst_bar.set(0)
        self.holder = {}
        self.show("installing")

        def job():
            ok, msg = core.install_all(
                self.status, lambda i: self.q.put(("istep", i)), lambda l: self.q.put(("ilog", l)), self.holder)
            self.q.put(("idone", (ok, msg)))
        threading.Thread(target=job, daemon=True).start()

    def _on_istep(self, i):
        n = len(self.inst_setters)
        for k, setter in enumerate(self.inst_setters):
            setter("done" if k < i else ("run" if k == i else "todo"))
        self.inst_bar.set(int(100 * i / max(n, 1)) + 8)

    def _on_idone(self, res):
        ok, msg = res
        if ok:
            self.inst_bar.set(100)
            self.status = core.check_status()
            self.show("ready")
            self._update_scan_button()
            return
        self.inst_title.configure(text="Something went wrong")
        self.inst_sub.configure(text=msg, fg=BAD_FG)
        for w in self.inst_buttons.winfo_children():
            w.destroy()
        primary_button(self.inst_buttons, "Try again", self.start_install, height=44).pack(side="left")
        secondary_button(self.inst_buttons, "Copy details", lambda: self._copy(self.inst_log.get("1.0", "end"))
                         ).pack(side="left", padx=10)
        if "git-scm.com" in msg:
            secondary_button(self.inst_buttons, "Open Git download page",
                             lambda: webbrowser.open(core.GIT_DOWNLOAD_URL)).pack(side="left")
        self.status = core.check_status()
        self._refresh_rail()

    # ------------------------------------------------------------ choose
    def _build_ready(self, f):
        top = tk.Frame(f, bg=WHITE)
        top.pack(fill="x")
        tk.Label(top, text="  ✓ SkillSpector ready  ", bg=OK_BG, fg=OK_FG, font=(FONT, 9, "bold"), pady=3).pack(
            side="right", anchor="n")
        heading(top, "What do you want to scan?").pack(anchor="w")
        body(top, "Pick a skill you downloaded, or paste a link to one on GitHub.", wrap=500).pack(
            anchor="w", pady=(8, 0))

        pills = tk.Frame(f, bg=WHITE)
        pills.pack(fill="x", pady=(20, 0))
        self.pill_buttons = {}
        for k in KINDS:
            b = pill_button(pills, k[1], lambda key=k[0]: self.set_kind(key))
            b.pack(side="left", padx=(0, 8))
            self.pill_buttons[k[0]] = b

        self.in_label = tk.Label(f, bg=WHITE, fg=INK, font=(FONT, 10, "bold"), anchor="w")
        self.in_label.pack(fill="x", pady=(20, 8))
        row = tk.Frame(f, bg=WHITE)
        row.pack(fill="x")
        self.entry_box, self.entry = entry_box(row, self.target, height=46, placeholder="")
        self.entry_box.pack(side="left", fill="x", expand=True)
        self.browse_btn = secondary_button(row, "Browse…", self.browse, height=46, padx=20)
        self.browse_btn.pack(side="left", padx=(10, 0))
        self.in_hint = tk.Label(f, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w")
        self.in_hint.pack(fill="x", pady=(8, 0))
        # shown only when the chosen folder has a skills/ subfolder
        self.skills_row = tk.Frame(f, bg=WHITE)
        pill_button(self.skills_row, "Scan only the skills folder", self._use_skills_folder, height=34, size=9,
                    padx=14).pack(side="left")
        tk.Label(self.skills_row, text="Faster, and skips tests, docs and benchmarks.", bg=WHITE, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=10)

        opt = RBox(f, fill=WHITE, outline=LINE, radius=8, pad=16)
        opt.pack(fill="x", pady=20)
        oi = opt.inner
        cb = tk.Checkbutton(oi, text="Quick scan (no account needed)", variable=self.quick, bg=WHITE,
                            activebackground=WHITE, font=(FONT, 10, "bold"), anchor="w", command=self._toggle_ai,
                            bd=0, highlightthickness=0, cursor="hand2")
        cb.pack(fill="x")
        tk.Label(oi, text="Fast built-in checks. Turn off to add AI review, which can catch risky instructions "
                          "written in plain language but needs an API key.", bg=WHITE, fg=MUTED,
                 font=(FONT, 9), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=(26, 0))
        self.ai_frame = tk.Frame(oi, bg=WHITE)
        pv = tk.Frame(self.ai_frame, bg=WHITE)
        pv.pack(side="left", padx=(0, 12), anchor="n")
        tk.Label(pv, text="AI provider", bg=WHITE, font=(FONT, 9, "bold"), anchor="w").pack(anchor="w", pady=(0, 6))
        ttk.Combobox(pv, textvariable=self.provider, values=["OpenAI"], state="readonly", width=14).pack(
            anchor="w", ipady=4)
        kv = tk.Frame(self.ai_frame, bg=WHITE)
        kv.pack(side="left", fill="x", expand=True, anchor="n")
        tk.Label(kv, text="API key (used for this scan only, never saved)", bg=WHITE, font=(FONT, 9, "bold"),
                 anchor="w").pack(anchor="w", pady=(0, 6))
        kb, _ = entry_box(kv, self.api_key, height=40, show="•", placeholder="Paste your key", size=10)
        kb.pack(fill="x")

        self.err_var = tk.StringVar()
        tk.Label(f, textvariable=self.err_var, bg=WHITE, fg=BAD_FG, font=(FONT, 9), anchor="w").pack(fill="x")
        bottom = tk.Frame(f, bg=WHITE)
        bottom.pack(side="bottom", fill="x")
        self.scan_btn = primary_button(bottom, "Scan", self.start_scan, padx=30)
        self.scan_btn.pack(side="left")
        self.scan_hint = tk.Label(bottom, text="Choose or paste something to scan first.", bg=WHITE, fg=MUTED,
                                  font=(FONT, 9))
        self.scan_hint.pack(side="left", padx=14)
        self.set_kind("folder")

    def _toggle_ai(self):
        if self.quick.get():
            self.ai_frame.pack_forget()
        else:
            self.ai_frame.pack(fill="x", pady=(14, 0))

    def set_kind(self, key):
        self.kind = key
        info = next(k for k in KINDS if k[0] == key)
        for k, b in self.pill_buttons.items():
            style_pill(b, k == key)
        self.in_label.configure(text=info[2])
        self.in_hint.configure(text=info[3])
        self.entry_box.set_placeholder(info[5])
        if key == "git":
            self.browse_btn.pack_forget()
        else:
            self.browse_btn.set_text(info[4])
            self.browse_btn.pack(side="left", padx=(10, 0))
        self.target.set("")
        self.err_var.set("")
        self._update_scan_button()

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
        self.scan_btn.set_enabled(has)
        self.scan_hint.configure(text="" if has else "Choose or paste something to scan first.")
        sub = core.skills_subfolder(self.target.get()) if self.kind == "folder" else None
        if sub and not self.skills_row.winfo_ismapped():
            self.skills_row.pack(fill="x", pady=(10, 0), after=self.in_hint)
        elif not sub and self.skills_row.winfo_ismapped():
            self.skills_row.pack_forget()

    def _use_skills_folder(self):
        sub = core.skills_subfolder(self.target.get())
        if sub:
            self.target.set(os.path.normpath(sub))

    # ------------------------------------------------------------ scanning
    # SkillSpector prints no stage information, so these advance with elapsed time. The last one stays
    # active until the scan really finishes (we never show "done" early).
    SCAN_STEPS = ["Reading skill files", "Running security checks", "Checking known vulnerabilities",
                  "Building report"]
    SCAN_STEP_AT = (0, 3, 8, 20)  # seconds at which each step becomes active

    def _build_scanning(self, f):
        heading(f, "Scanning…").pack(anchor="w")
        self.scan_target_lbl = body(f, "", wrap=640)
        self.scan_target_lbl.pack(anchor="w", pady=(8, 18))
        box = tk.Frame(f, bg=WHITE)
        box.pack(fill="x", pady=(10, 0))
        Spinner(box, size=56).pack(side="left", padx=(0, 18))
        txt = tk.Frame(box, bg=WHITE)
        txt.pack(side="left", fill="x", expand=True)
        self.scan_status = tk.Label(txt, text="", bg=WHITE, fg=INK, font=(FONT, 12, "bold"), anchor="w")
        self.scan_status.pack(fill="x")
        self.scan_last = tk.Label(txt, text="", bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w", justify="left",
                                  wraplength=520)
        self.scan_last.pack(fill="x", pady=(4, 0))
        steps = tk.Frame(f, bg=WHITE)
        steps.pack(fill="x", pady=(22, 0))
        self.scan_setters = [step_row(steps, s) for s in self.SCAN_STEPS]
        self.scan_note = tk.Label(f, text="", bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w", justify="left",
                                  wraplength=600)
        self.scan_note.pack(anchor="w", pady=(12, 0))
        # full live output is kept for error reports (shown if the scan fails), not displayed
        self.scan_log = tk.Text(f)
        secondary_button(f, "Cancel", self.cancel_scan, height=42).pack(side="bottom", anchor="w")

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
        self.scan_note.configure(
            text="Large folders can take a few minutes." if self.quick.get()
            else "AI review can take a few minutes. Large folders take longer.")
        self.scan_log.delete("1.0", "end")
        self.holder = {}
        self.scan_started = time.monotonic()
        self.scan_last.configure(text="")
        self.scan_root = core.local_scan_root(self.kind, t)
        self._paint_scan()
        self.show("scanning")
        ss = self.status.get("skillspector") or core.find_skillspector()
        quick, prov, key = self.quick.get(), self.provider.get(), self.api_key.get().strip()

        def job():
            res = core.run_scan(ss, t, quick, prov, key, lambda l: self.q.put(("slog", l)), self.holder)
            self.q.put(("sdone", res))
        threading.Thread(target=job, daemon=True).start()
        self.after(250, self._scan_tick)

    def _paint_scan(self, finished=False):
        secs = int(time.monotonic() - self.scan_started)
        self.scan_status.configure(text="Scanning… %d:%02d" % (secs // 60, secs % 60))
        active = max(i for i, at in enumerate(self.SCAN_STEP_AT) if secs >= at)
        for i, setter in enumerate(self.scan_setters):
            setter("done" if finished or i < active else ("run" if i == active else "todo"))

    def _scan_tick(self):
        if self.current != "scanning":
            return
        self._paint_scan()
        self.after(500, self._scan_tick)

    def cancel_scan(self):
        self.holder["cancelled"] = True
        core.kill_tree(self.holder.get("proc"))

    # ------------------------------------------------------------ results
    def _build_results(self, f):
        top = tk.Frame(f, bg=WHITE)
        top.pack(fill="x")
        self.banner = RBox(top, fill=BAD_BG, outline=BAD_BG, radius=10, pad=0)
        self.banner.pack(side="left", fill="x", expand=True)
        bi = self.banner.inner
        self.banner_icon = tk.Canvas(bi, width=34, height=34, bg=BAD_BG, highlightthickness=0)
        self.banner_icon.pack(side="left", padx=(20, 14), pady=18)
        txt = tk.Frame(bi, bg=BAD_BG)
        txt.pack(side="left", fill="x", expand=True, pady=14)
        self.banner_txt = txt
        self.banner_title = tk.Label(txt, font=(FONT, 14, "bold"), anchor="w", bg=BAD_BG)
        self.banner_title.pack(fill="x")
        self.banner_sub = tk.Label(txt, font=(FONT, 10), anchor="w", justify="left", bg=BAD_BG, wraplength=250)
        self.banner_sub.pack(fill="x")

        tiles = tk.Frame(top, bg=WHITE)
        tiles.pack(side="left", padx=(12, 0), fill="y")
        self.count_lbls = {}
        for name in core.SEVERITIES:
            t = RBox(tiles, fill=WHITE, outline=LINE, radius=10, width=70)
            t.pack(side="left", padx=(0, 6), fill="y")
            n = tk.Label(t.inner, text="0", bg=WHITE, fg=INK, font=(FONT, 16, "bold"))
            n.pack(pady=(10, 0))
            tk.Label(t.inner, text=name, bg=WHITE, fg=BODY, font=(FONT, 8, "bold")).pack(pady=(0, 10))
            self.count_lbls[name] = n

        notes = tk.Frame(f, bg=WHITE)
        notes.pack(fill="x", pady=(10, 0))
        self.warn_lbl = tk.Label(notes, bg=WARN_BG, fg=WARN_FG, font=(FONT, 9, "bold"), anchor="w", justify="left",
                                 padx=10, pady=5, wraplength=640)
        self.info_lbl = tk.Label(notes, bg=WHITE, fg=BODY, font=(FONT, 9), anchor="w", justify="left",
                                 wraplength=640)

        mid = tk.Frame(f, bg=WHITE)
        mid.pack(fill="x", pady=(12, 8))
        self.filter_frame = tk.Frame(mid, bg=WHITE)
        self.filter_frame.pack(side="right", anchor="n")
        self.filter_btns = {}
        for name in ("All",) + core.SEVERITIES:
            b = pill_button(self.filter_frame, name, lambda n=name: self.set_filter(n), height=32, size=9, padx=12)
            b.pack(side="left", padx=(5, 0))
            self.filter_btns[name] = b
        self.res_target = tk.Label(mid, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w", wraplength=260,
                                   justify="left")
        self.res_target.pack(side="left", fill="x", expand=True)

        bottom = tk.Frame(f, bg=WHITE)
        bottom.pack(side="bottom", fill="x", pady=(14, 0))
        primary_button(bottom, "Scan another", self.scan_another, height=44, padx=22).pack(side="left")
        secondary_button(bottom, "Save report (.md)", self.save_md).pack(side="left", padx=10)
        secondary_button(bottom, "Save as JSON", self.save_json).pack(side="left")
        self.list_area = ScrollFrame(f)
        self.list_area.pack(fill="both", expand=True)

    def _set_note(self, label, text, pady=(0, 0)):
        if text:
            label.configure(text=text)
            label.pack(fill="x", pady=pady, anchor="w")
        else:
            label.pack_forget()

    def show_results(self, res):
        self.scan_result = res
        report = res["report"]
        t = self.last_target
        if len(t) > 56:
            t = t[:22] + "…" + t[-32:]
        self.res_target.configure(text="Scanned: " + t)
        self.findings = core.parse_findings(report) if report is not None else None
        self.groups = []
        warn = details = group_note = ""
        if self.findings is not None:
            counts = core.count_by_severity(self.findings)
            lab, expl, level = core.verdict(counts, report)
            warn, details = core.completeness_lines(core.completeness(report))
            self.groups = core.group_findings(self.findings)
            group_note = core.group_note(self.groups)
            for k, w in self.count_lbls.items():
                w.configure(text=str(counts[k]))
        else:
            lab, expl, level = "Scan finished", "The report format wasn't recognised, so the raw report is shown below.", "warn"
            for w in self.count_lbls.values():
                w.configure(text="–")
        bg, fg, sub = LEVELS[level]
        self.banner.set_colors(fill=bg, outline=bg)
        for w in (self.banner_icon, self.banner_txt):
            w.configure(bg=bg)
        self.banner_title.configure(bg=bg, fg=fg, text=lab)
        self.banner_sub.configure(bg=bg, fg=sub, text=expl)
        self.banner_icon.delete("all")
        shield(self.banner_icon, 0, 0, 34, fg, "check" if level == "ok" else "alert", width=2)
        self._set_note(self.warn_lbl, warn)
        self._set_note(self.info_lbl, " ".join(x for x in (group_note, details) if x), pady=(6, 0))
        self.filter = "All"
        self.group_open = {g["name"]: not ss_groups.collapsed_by_default(g["name"]) for g in self.groups}
        self.render_findings()
        self.show("results")

    def set_filter(self, name):
        self.filter = name
        self.render_findings()

    def _toggle_group(self, name):
        self.group_open[name] = not self.group_open.get(name, True)
        self.render_findings(keep_scroll=True)

    def _open_finding(self, path):
        err = core.open_in_default_app(path)
        if err:
            messagebox.showwarning("Could not open the file", err)

    def render_findings(self, keep_scroll=False):
        for n, b in self.filter_btns.items():
            style_pill(b, n == self.filter, dark=True)
        inner = self.list_area.inner
        for w in inner.winfo_children():
            w.destroy()
        if self.findings is None:
            t = tk.Text(inner, height=18, font=(MONO, 9), wrap="word", relief="flat", bg=RAIL_BG)
            t.insert("1.0", (self.scan_result or {}).get("raw_text", ""))
            t.configure(state="disabled")
            t.pack(fill="both", expand=True, padx=2, pady=4)
            return
        shown = [f for f in self.findings if self.filter in ("All", f["severity"])]
        groups = core.group_findings(shown)
        if not shown:
            tk.Label(inner, text="Nothing to show here.", bg=WHITE, fg=MUTED, font=(FONT, 10)).pack(pady=24)
        for g in groups:
            self._render_group(inner, g)

    def _render_group(self, inner, g):
        name, n = g["name"], g["total"]
        is_open = self.group_open.get(name, True) and n > 0
        bg = RAIL_BG
        head = tk.Frame(inner, bg=bg, highlightthickness=1, highlightbackground=LINE,
                        cursor="hand2" if n else "arrow")
        head.pack(fill="x", pady=(8, 2), padx=(0, 6))
        arrow = tk.Label(head, text=("▾" if is_open else "▸") if n else " ", bg=bg, fg=INK, font=(FONT, 10, "bold"),
                         width=2)
        arrow.pack(side="left", padx=(10, 0), pady=9)
        title = tk.Label(head, text=name, bg=bg, fg=INK if n else MUTED, font=(FONT, 10, "bold"), anchor="w")
        title.pack(side="left", padx=(2, 10))
        summ = tk.Label(head, text=core.group_summary(g), bg=bg, fg=BODY if n else MUTED, font=(FONT, 9),
                        anchor="w")
        summ.pack(side="left")
        if n:
            for w in (head, arrow, title, summ):
                w.bind("<Button-1>", lambda e, nm=name: self._toggle_group(nm))
        if not is_open:
            return
        for f in g["findings"]:
            self._render_finding(inner, f)

    def _render_finding(self, inner, f):
        card = RBox(inner, fill=WHITE, outline=LINE, radius=8, pad=1)
        card.pack(fill="x", pady=5, padx=(0, 6))
        ci = card.inner
        head = tk.Frame(ci, bg=WHITE)
        head.pack(fill="x", padx=15, pady=(13, 4))
        bg, fg = SEV_COLORS.get(f["severity"], SEV_COLORS["Low"])
        tk.Label(head, text=" %s " % f["severity"].upper(), bg=bg, fg=fg, font=(FONT, 8, "bold")).pack(
            side="left", anchor="n")
        path = core.resolve_local_file(self.scan_root, f.get("file"))
        if path:  # only when a local copy of the scanned files exists
            pill_button(head, "Open file", lambda p=path: self._open_finding(p), height=28, size=9, padx=12).pack(
                side="right", anchor="n")
        tk.Label(head, text=f["title"], bg=WHITE, fg=INK, font=(FONT, 10, "bold"), wraplength=400,
                 justify="left", anchor="w").pack(side="left", padx=10, fill="x")
        if f["description"]:
            tk.Label(ci, text=f["description"], bg=WHITE, fg=BODY, font=(FONT, 9), wraplength=560,
                     justify="left", anchor="w").pack(fill="x", padx=15, pady=3)
        tk.Label(ci, text=f["where"], bg=WHITE, fg=MUTED, font=(MONO, 8), anchor="w").pack(
            fill="x", padx=15, pady=(2, 13))

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
                fh.write(core.to_markdown(self.last_target, self.findings, counts,
                                         (self.scan_result or {}).get("report")))

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
            self._paint_scan(finished=True)
            self.show_results(res)
            return
        self.show("ready")
        self._update_scan_button()
        if res.get("error") == "Cancelled.":
            self.err_var.set("Scan cancelled.")
        else:
            self.err_var.set(res.get("error") or "The scan failed.")
            details = ("Exit code: %s\n\nMessages from SkillSpector:\n%s\n\nRaw output:\n%s" % (
                res.get("returncode"), (res.get("log") or "(none)")[-1200:],
                (res.get("raw_text") or "(empty)")[:1500]))
            messagebox.showerror("Scan failed", (res.get("error") or "") + "\n\n" + details)

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
                        self.show("setup")
                elif kind == "rechecked":
                    self.status = val
                    if self.current == "setup":
                        self._refresh_deps()
                        self.status_var.set("SkillSpector is ready" if self._all_ok() else "SkillSpector is not installed")
                    self._refresh_rail()
                elif kind == "istep":
                    self._on_istep(val)
                elif kind == "ilog":
                    append_text(self.inst_log, val)
                elif kind == "idone":
                    self._on_idone(val)
                elif kind == "slog":
                    append_text(self.scan_log, val)
                    self.scan_last.configure(text=val[:160])
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
