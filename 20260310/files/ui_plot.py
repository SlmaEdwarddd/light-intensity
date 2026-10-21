"""
ui_plot.py
----------
Plot window (Toplevel) that shows one matplotlib chart per ROI plus a
scrollable text log on the right.

Public API
----------
  initialize_plot_area(n, root, confirm_close_cb)
      Build (or rebuild) the plot window for n ROIs.
  update_plots()
      Redraw all charts with the latest state.roi_data / state.timestamps.
  append_log(text)
      Thread-safe append to the text log widget.
  confirm_close_plot(start_btn, default_btn)
      Ask the user before closing; stops detection.
  save_plot_image(fig)
      Save a single figure as a PNG file.
"""

import datetime
import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import messagebox

import state


# ─────────────────────────────────────────────────────────────────────────────
# Build the window
# ─────────────────────────────────────────────────────────────────────────────

def initialize_plot_area(n, root, confirm_close_cb):
    """
    Create the plot + log Toplevel window.

    Parameters
    ----------
    n               : int         – number of ROIs (one chart each)
    root            : tk.Tk       – parent window
    confirm_close_cb: callable()  – bound to the window's close button
    """
    # Destroy previous window if any
    if state.plot_win:
        try:
            state.plot_win.destroy()
        except Exception:
            pass

    state.plot_win = tk.Toplevel(root)
    state.plot_win.title("ROI 平均光強度（每秒） / Avg ROI Intensity (per second)")
    state.plot_win.configure(bg="#1E1E1E")
    state.plot_win.protocol("WM_DELETE_WINDOW", confirm_close_cb)

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    win_w, win_h = int(sw * 0.9), int(sh * 0.9)
    state.plot_win.geometry(f"{win_w}x{win_h}")

    # ── Main paned layout ─────────────────────────────────────────────────────
    paned = tk.PanedWindow(
        state.plot_win, orient=tk.HORIZONTAL,
        sashrelief=tk.RAISED, sashwidth=10, bg="#1E1E1E"
    )
    paned.pack(fill="both", expand=True)

    # Left: scrollable chart area
    left_container = tk.Frame(paned, bg="#1E1E1E")
    paned.add(left_container, minsize=1000)

    state.canvas_frame = tk.Canvas(left_container, bg="#1E1E1E", highlightthickness=0)
    v_scroll = tk.Scrollbar(left_container, orient=tk.VERTICAL,   command=state.canvas_frame.yview)
    h_scroll = tk.Scrollbar(left_container, orient=tk.HORIZONTAL,  command=state.canvas_frame.xview)
    state.canvas_frame.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

    state.canvas_frame.grid(row=0, column=0, sticky="nsew")
    v_scroll.grid(row=0, column=1, sticky="ns")
    h_scroll.grid(row=1, column=0, sticky="ew")
    left_container.rowconfigure(0, weight=1)
    left_container.columnconfigure(0, weight=1)

    state.scrollable_frame = tk.Frame(state.canvas_frame, bg="#1E1E1E")
    state.canvas_frame.create_window((0, 0), window=state.scrollable_frame, anchor="nw")

    # Right: log text panel
    text_frame = tk.Frame(paned, bg="#1E1E1E")
    paned.add(text_frame, minsize=320)

    _build_log_panel(text_frame)

    # Mouse-wheel bindings for chart area
    def _on_canvas_wheel(event):
        try:
            state.canvas_frame.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            try:
                state.canvas_frame.yview_scroll(int(-1 * event.delta), "units")
            except Exception:
                pass

    state.canvas_frame.bind("<Enter>",  lambda e: state.canvas_frame.bind_all("<MouseWheel>", _on_canvas_wheel))
    state.canvas_frame.bind("<Leave>",  lambda e: state.canvas_frame.unbind_all("<MouseWheel>"))

    # ── Charts ────────────────────────────────────────────────────────────────
    state.plot_canvases.clear()
    state.plot_axes.clear()
    state.plot_figures.clear()

    for i in range(n):
        fig = Figure(figsize=(5.5, 3.5), dpi=100)
        ax  = fig.add_subplot(111)
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Intensity")
        ax.grid(True)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=state.scrollable_frame)
        widget = canvas.get_tk_widget()
        widget.grid(row=i // 2, column=i % 2, padx=10, pady=10)
        widget.bind("<Button-3>", lambda e, f=fig: save_plot_image(f))
        canvas.draw()

        state.plot_figures.append(fig)
        state.plot_canvases.append(canvas)
        state.plot_axes.append(ax)

    state.scrollable_frame.update_idletasks()
    state.canvas_frame.config(scrollregion=state.canvas_frame.bbox("all"))
    paned.sash_place(0, int(win_w * 0.75), 0)


def _build_log_panel(text_frame):
    """Build the scrollable text log on the right side of the plot window."""
    LOG_FONT = ("Arial", 18)

    text_container = tk.Frame(text_frame, bg="#1E1E1E")
    text_container.pack(side="top", fill="both", expand=True, padx=2, pady=(4, 4))

    state.log_text_widget = tk.Text(
        text_container, width=40, height=34, font=LOG_FONT,
        wrap="word", state="disabled",
        bg="#2B2B2B", fg="#00BFFF", insertbackground="#00BFFF"
    )
    state.log_text_widget.pack(side="left", fill="both", expand=True)

    scrollbar_text = tk.Scrollbar(text_container, orient=tk.VERTICAL, command=state.log_text_widget.yview)
    scrollbar_text.pack(side="right", fill="y", padx=(2, 0))
    state.log_text_widget.configure(yscrollcommand=scrollbar_text.set)

    # Scroll-to-bottom button
    button_frame = tk.Frame(text_frame, bg="#1E1E1E")
    button_frame.pack(side="bottom", fill="x", padx=4, pady=(2, 6))

    def _scroll_to_bottom():
        state.text_follow = True
        try:
            state.log_text_widget.see(tk.END)
        except Exception:
            pass

    tk.Button(
        button_frame, text="捲到最底 / Scroll to bottom",
        command=_scroll_to_bottom, font=("Arial", 11), height=2,
        bg="#0078D4", fg="white", activebackground="#107C10", activeforeground="white"
    ).pack(fill="x")

    # Pause auto-scroll when user scrolls manually
    def _on_wheel(event):
        state.text_follow = False
        delta = 0
        if hasattr(event, 'delta'):
            try:
                delta = int(event.delta / 120)
            except Exception:
                pass
        if hasattr(event, 'num'):
            delta = 1 if event.num == 4 else (-1 if event.num == 5 else 0)
        try:
            state.log_text_widget.yview_scroll(-delta, "units")
        except Exception:
            pass
        return "break"

    state.log_text_widget.bind("<MouseWheel>", _on_wheel)
    scrollbar_text.bind("<ButtonPress-1>", lambda e: setattr(state, 'text_follow', False))


# ─────────────────────────────────────────────────────────────────────────────
# Runtime helpers
# ─────────────────────────────────────────────────────────────────────────────

def update_plots():
    """Redraw every chart with the latest roi_data / timestamps."""
    for i, values in enumerate(state.roi_data):
        ax = state.plot_axes[i]
        ax.clear()
        ax.plot(state.timestamps, values, marker='o')
        ax.set_title(f"Light intensity of Sample {i+1}")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Intensity")
        ax.grid(True)
        ax.figure.tight_layout()
        state.plot_canvases[i].draw()


def append_log(text):
    """Append *text* to the log widget and optionally auto-scroll."""
    if state.log_text_widget:
        try:
            state.log_text_widget.config(state="normal")
            state.log_text_widget.insert(tk.END, text + "\n\n")
            if state.text_follow:
                state.log_text_widget.see(tk.END)
            state.log_text_widget.config(state="disabled")
        except Exception:
            pass


def confirm_close_plot(start_btn, default_btn):
    """Ask the user before closing the plot window; stops detection."""
    if messagebox.askokcancel(
        "關閉視窗 / Close Window",
        "關閉圖表視窗後，偵測將會停止。\nClosing the plot window will STOP detection."
    ):
        state.analyzing = False
        try:
            start_btn["text"] = "重新啟動偵測 / Restart Detection"
            default_btn.state(["disabled"])
        except Exception:
            pass
        try:
            state.plot_win.destroy()
        except Exception:
            pass


def save_plot_image(fig):
    """Save *fig* as a PNG with a timestamp filename."""
    now      = datetime.datetime.now()
    filename = f"Plot_{now:%Y_%m_%d_%H_%M_%S}.png"
    fig.savefig(filename)
    messagebox.showinfo(
        "儲存成功 / Saved",
        f"圖表已儲存為 {filename}\nPlot saved as {filename}"
    )
