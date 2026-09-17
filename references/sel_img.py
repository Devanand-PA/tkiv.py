#!/usr/bin/env python3
"""
High-performance image selector with async loading, thumbnail caching,
lazy directory scanning, and multi-select support.

Usage:
    sel_img.py [directory...] [-r] [-t]
    -r  : recursively search subdirectories
    -t  : sort by modification time (newest first)

Dmenu mode:
    sel_img.py --dmenu-mode --list-file FILE --image-file FILE
    sel_img.py --dmenu-mode --list-entries "a\nb" --image-entries "1.png\n2.png"
    --return-label  : output the label instead of the image path (dmenu only)

Multi-select:
    <Control-Return>  : select / deselect current item
    <Return>          : confirm — prints all selected items + current item

Views:
    <Control-g>       : toggle between list view and gallery view
    <Tab>             : toggle between list view and gallery view
    --gallery-rows N  : target number of gallery rows visible (default 3.5)
    --gallery-cols N  : target number of gallery columns visible
    --gallery-tile-size N : explicit tile size in pixels (overrides rows/cols)


Pre-select:
    --pre-select "entry1\nentry2"      : pre-select labels at launch
    --pre-select-file FILE             : read pre-select labels from file

Performance notes:
  * Uses pyvips (libvips) when available — the same C library GdkPixbuf wraps.
    Falls back to PIL with draft()/reduce()/BILINEAR + reducing_gap.
  * Persistent on-disk WebP thumbnail cache under ~/.cache/sel_img_thumbs.
  * Decode workers are threads; libvips/libjpeg-turbo release the GIL inside
    their C decode+resize paths, so this scales well up to cpu_count workers.
"""

import sys
import os
import hashlib
import argparse
import threading
import queue
from pathlib import Path
from collections import deque
from tkinter import Tk, Frame, Listbox, Entry, Label, Scrollbar, StringVar, Canvas
from tkinter import BOTH, LEFT, RIGHT, TOP, BOTTOM, X, Y, END, SINGLE, NW, NSEW

# ── Optional fast-path decoders ──────────────────────────────────────────────
try:
    import pyvips  # type: ignore
    HAS_VIPS = True
except Exception:
    HAS_VIPS = False

try:
    import numpy as np  # noqa: F401
    HAS_NUMPY = True
except Exception:
    HAS_NUMPY = False

from PIL import Image, ImageTk, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

# ─── Configuration ───────────────────────────────────────────────────────────

SUPPORTED_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif'}

THEME = {
    "bg_primary":   "#2e3440",
    "bg_secondary": "#3b4252",
    "bg_input":     "#4c566a",
    "fg_text":      "#d8dee9",
    "fg_bright":    "#eceff4",
    "accent":       "#88c0d0",
    "accent_fg":    "#2e3440",
    "selected_bg":  "#5e81ac",
    "selected_fg":  "#eceff4",
    "hover_border": "#4c566a",
}

CACHE_SIZE = 800          # Max cached thumbnails in RAM
PRELOAD_AHEAD = 3         # How many images to preload ahead/behind (list view)

# Decode pool — scaled to CPU count. libvips + libjpeg-turbo release the GIL,
# so threads give real parallelism here.
DECODE_WORKERS = max(2, min(8, os.cpu_count() or 4))

# Persistent on-disk thumbnail cache
DISK_CACHE_ENABLED = True
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "sel_img_thumbs"
CACHE_WEBP_QUALITY = 82

# Gallery geometry — tile size scales with viewport size at runtime.
GALLERY_TILE_MIN = 180
GALLERY_TILE_MAX = 420
GALLERY_TARGET_ROWS = 3.5        # approx rows we want visible in the viewport
GALLERY_CAPTION_RATIO = 0.16     # caption height as fraction of tile size
GALLERY_CAPTION_MIN = 22
GALLERY_PAD_RATIO = 0.045        # inter-tile pad as fraction of tile size
GALLERY_PAD_MIN = 6
GALLERY_SIZE_QUANTUM = 8         # quantize tile size to reduce rebuild churn
GALLERY_OVERSCAN_ROWS = 2


# ─── Decode helpers (module-level, run on worker threads) ────────────────────

def _get_orig_size(path):
    """Cheap header-only read. Does not decode pixel data."""
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return (0, 0)


def _disk_cache_path(path, w, h):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = hashlib.sha1(
        f"{path}|{st.st_mtime_ns}|{st.st_size}|{w}x{h}".encode("utf-8")
    ).hexdigest()
    return CACHE_DIR / key[:2] / (key + ".webp")


def _decode_image(path, max_w, max_h):
    """Decode/thumbnail `path` to fit inside (max_w, max_h).

    Returns (PIL.Image or None, (orig_w, orig_h)).
    Uses the on-disk WebP cache when possible.
    """
    orig_size = _get_orig_size(path)

    cache_file = _disk_cache_path(path, max_w, max_h) if DISK_CACHE_ENABLED else None

    # ── 1) On-disk cache hit ──
    if cache_file is not None and cache_file.exists():
        try:
            with Image.open(cache_file) as img:
                img.load()
                return img, orig_size
        except Exception:
            try:
                cache_file.unlink()
            except OSError:
                pass

    pil_img = None

    # ── 2) pyvips fast path ──
    if HAS_VIPS and HAS_NUMPY:
        try:
            v = pyvips.Image.thumbnail(path, max_w, height=max_h, size="down")
            arr = v.numpy()
            if v.bands == 4:
                pil_img = Image.fromarray(arr.copy(), "RGBA")
            elif v.bands == 3:
                pil_img = Image.fromarray(arr.copy(), "RGB")
            else:
                pil_img = Image.fromarray(arr.copy()).convert("RGB")
        except Exception:
            pil_img = None

    # ── 3) PIL fallback ──
    if pil_img is None:
        try:
            with Image.open(path) as img:
                # Ask libjpeg for a pre-scaled decode (huge win on big JPEGs).
                if img.format == "JPEG":
                    img.draft("RGB", (max_w, max_h))

                # Box-filter pre-shrink for very large images (cheap O(n)).
                if img.width > max_w * 4 or img.height > max_h * 4:
                    factor = max(1, min(img.width // (max_w * 2),
                                        img.height // (max_h * 2)))
                    if factor > 1:
                        img = img.reduce(factor)

                # BILINEAR + reducing_gap is 2-3x faster than LANCZOS and
                # visually identical at thumbnail sizes.
                img.thumbnail((max_w, max_h),
                              Image.Resampling.BILINEAR,
                              reducing_gap=2.0)

                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")

                img.load()
                pil_img = img
        except Exception:
            pil_img = None

    # ── 4) Populate the on-disk cache ──
    if pil_img is not None and cache_file is not None:
        tmp = None
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_name(cache_file.name + ".tmp")
            pil_img.save(tmp, "WEBP", quality=CACHE_WEBP_QUALITY, method=0)
            os.replace(tmp, cache_file)
        except Exception:
            if tmp is not None:
                try:
                    tmp.unlink()
                except Exception:
                    pass

    return pil_img, orig_size


# ─── Gallery Tile ────────────────────────────────────────────────────────────

class GalleryTile(Frame):
    """A single thumbnail + caption tile in the gallery view."""

    __slots__ = ("app", "index", "label", "path", "_photo",
                 "_selected", "_current", "thumb", "caption")

    def __init__(self, parent, app, index, label, path):
        super().__init__(parent, bg=THEME["bg_secondary"],
                         highlightthickness=2, highlightbackground=THEME["bg_secondary"])
        self.app = app
        self.index = index
        self.label = label
        self.path = path
        self._photo = None
        self._selected = False
        self._current = False

        self.thumb = Label(self, bg=THEME["bg_secondary"], text="…",
                           fg=THEME["fg_text"], font=("sans-serif", 10),
                           width=1, height=1)
        self.thumb.pack(side=TOP, fill=BOTH, expand=True, padx=2, pady=(2, 0))

        self.caption = Label(self, bg=THEME["bg_secondary"], text=label,
                             fg=THEME["fg_text"], font=("sans-serif", 9),
                             anchor="center", justify="center",
                             wraplength=max(40, app._tile_w - 12))
        self.caption.pack(side=BOTTOM, fill=X, padx=2, pady=(0, 2))

        self.configure(width=app._tile_w,
                       height=app._tile_h + app._tile_caption_h)
        self.pack_propagate(False)

        for w in (self, self.thumb, self.caption):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Double-Button-1>", self._on_double)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_click(self, event=None):
        self.app._select_and_show(self.index, from_gallery=True)
        return "break"

    def _on_double(self, event=None):
        self.app._select_and_show(self.index, from_gallery=True)
        self.app._on_confirm()
        return "break"

    def _on_enter(self, event=None):
        if not self._selected and not self._current:
            self.configure(highlightbackground=THEME["hover_border"])

    def _on_leave(self, event=None):
        self._refresh_border()

    def set_photo(self, photo):
        self._photo = photo
        if photo is not None:
            self.thumb.config(image=photo, text="")
            self.thumb.image = photo
        else:
            self.thumb.config(image="", text="✕")

    def update_item(self, index, label, path):
        """Recycle this tile to a different item. Returns True if the
        underlying path changed and the thumbnail must be reloaded."""
        self.index = index
        if self.path == path:
            # Same image — only the label/index may have shifted.
            if self.label != label:
                self.label = label
                self.caption.config(text=label)
            return False
        self.label = label
        self.path = path
        self.caption.config(text=label)
        self._photo = None
        self.thumb.config(image="", text="…")
        return True


    def set_selected(self, selected):
        if self._selected == selected:
            return
        self._selected = selected
        self._refresh_border()

    def set_current(self, current):
        if self._current == current:
            return
        self._current = current
        self._refresh_border()

    def _refresh_border(self):
        if self._selected:
            self.configure(highlightbackground=THEME["selected_bg"],
                           highlightthickness=3)
        elif self._current:
            self.configure(highlightbackground=THEME["accent"],
                           highlightthickness=2)
        else:
            self.configure(highlightbackground=THEME["bg_secondary"],
                           highlightthickness=2)


# ─── Main Application ────────────────────────────────────────────────────────

class ImageSelector:

    def __init__(self, root, image_paths, display_labels=None,
                 pre_select_labels=None, pass_idx=0, idx_write_path="",
                 custom_title="", gallery_rows=None, gallery_cols=None,
                 gallery_tile_size=None):
        self._gallery_rows_opt = gallery_rows if gallery_rows and gallery_rows > 0 else None
        self._gallery_cols_opt = gallery_cols if gallery_cols and gallery_cols > 0 else None
        self._gallery_tile_opt = (gallery_tile_size
                                  if gallery_tile_size and gallery_tile_size > 0
                                  else None)

        self.idx_write_path = idx_write_path
        self.custom_title = custom_title

        self.root = root
        if display_labels is None:
            self.all_items = [(os.path.basename(p), p) for p in image_paths]
        else:
            if len(display_labels) != len(image_paths):
                raise ValueError("display_labels and image_paths must have same length")
            self.all_items = list(zip(display_labels, image_paths))
        self.filtered_items = self.all_items.copy()
        self.path_to_abs_index = {path: idx for idx, (_, path) in enumerate(self.all_items)}
        self._pending_future = None
        self._last_index = -1
        self._after_id = None
        self._scan_thread = None
        self._scan_done = threading.Event()
        self._scan_done.set()
        self.selected_path = None
        self.selected_label = None
        self.selected_paths = set()
        self._base_status_text = ""

        # View state
        self.view_mode = "list"
        self.view_mode = "list"
        self._gallery_resize_after = None
        self._gallery_gen = 0

        # Gallery tile metrics — recomputed from the viewport size.
        self._tile_w = 240
        self._tile_h = 240
        self._tile_caption_h = 34
        self._tile_pad = 10
        self._tile_thumb_max = (self._tile_w - 5, self._tile_h - 5)
        self._gallery_resize_after = None
        self._gallery_gen = 0

        # ── Lazy decode infrastructure ──
        self._decode_q = queue.Queue()
        self._decode_tokens = {}
        self._decode_token_lock = threading.Lock()
        self._decode_token_counter = 0
        self._decode_threads = []
        self._decode_stop = threading.Event()
        self._start_decode_workers()

        # PIL image cache (raw) and PhotoImage cache.
        # Entry format in _photo_cache: key=(path,w,h) -> (PhotoImage, orig_size)
        self._pil_cache = {}
        self._photo_cache = {}
        self._cache_lock = threading.Lock()

        # Currently displayed PhotoImages (keep refs alive)
        self._gallery_tiles = {}
        self._visible_range = (0, 0)
        self._gallery_cols = 1
        self._gallery_grid_dirty = True
        self._gallery_built = False
        self._pending_gallery_scroll = None

        if pre_select_labels:
            self._apply_pre_select(pre_select_labels)

        self._closing = False

        self._setup_window()
        self._build_ui()
        self._bind_events()
        self._populate_list()
        if self.filtered_items:
            self._select_and_show(pass_idx)
        self.input.focus_set()

    # ── Decode pool ───────────────────────────────────────────────────────────

    def _start_decode_workers(self):
        for _ in range(DECODE_WORKERS):
            t = threading.Thread(target=self._decode_worker, daemon=True)
            t.start()
            self._decode_threads.append(t)

    def _decode_worker(self):
        while not self._decode_stop.is_set():
            try:
                job = self._decode_q.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                break
            path, max_w, max_h, token, callback = job
            if self._closing or self._decode_stop.is_set():
                continue
            with self._decode_token_lock:
                latest = self._decode_tokens.get(path)
            if latest is not None and latest != token:
                continue

            pil_img, orig_size = _decode_image(path, max_w, max_h)

            if self._closing or self._decode_stop.is_set():
                continue
            try:
                self.root.after(0, callback, pil_img, token, orig_size)
            except Exception:
                pass

    def _request_decode(self, path, max_w, max_h, callback):
        """Queue a decode job. Only the latest request per path is honored."""
        with self._decode_token_lock:
            self._decode_token_counter += 1
            token = self._decode_token_counter
            self._decode_tokens[path] = token
        self._decode_q.put((path, max_w, max_h, token, callback))
        return token

    # ── Thumbnail cache helpers ───────────────────────────────────────────────

    def _cache_get(self, path, w, h):
        key = (path, w, h)
        with self._cache_lock:
            entry = self._photo_cache.get(key)
            if entry is not None:
                # LRU bump
                self._photo_cache.pop(key, None)
                self._photo_cache[key] = entry
            return entry

    def _cache_put(self, path, w, h, entry):
        key = (path, w, h)
        with self._cache_lock:
            self._photo_cache[key] = entry
            while len(self._photo_cache) > CACHE_SIZE:
                oldest = next(iter(self._photo_cache))
                del self._photo_cache[oldest]

    def _load_thumbnail_async(self, path, w, h, on_ready):
        """Return a PhotoImage if cached, else schedule a decode and call
        on_ready(photo_or_None, orig_size) on the main thread when done."""
        cached = self._cache_get(path, w, h)
        if cached is not None:
            photo, orig_size = cached
            on_ready(photo, orig_size)
            return photo

        def _done(pil_img, token, orig_size):
            if self._closing:
                return
            if pil_img is None:
                on_ready(None, orig_size)
                return
            try:
                photo = ImageTk.PhotoImage(pil_img)
            except Exception:
                on_ready(None, orig_size)
                return
            self._cache_put(path, w, h, (photo, orig_size))
            on_ready(photo, orig_size)

        self._request_decode(path, w, h, _done)
        return None

    # ── Pre-select ──
    def _apply_pre_select(self, pre_select_labels):
        target_labels = set(pre_select_labels)
        matched = set()
        for label, path in self.all_items:
            if label in target_labels and label not in matched:
                self.selected_paths.add(path)
                matched.add(label)

    # ── Window / UI ──
    def _setup_window(self):
        self.root.title(self.custom_title or "Image Selector")
        self.root.configure(bg=THEME["bg_primary"])
        self.root.attributes('-topmost', True)
        try:
            self.root.attributes('-type', 'dialog')
        except Exception:
            pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw - 100}x{sh - 100}+50+50")
        self.root.minsize(600, 400)

    def _build_ui(self):
        self.main_frame = Frame(self.root, bg=THEME["bg_primary"])
        self.main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # ── Shared bottom bar ──
        self.bottom_bar = Frame(self.main_frame, bg=THEME["bg_primary"])
        self.bottom_bar.pack(side=BOTTOM, fill=X, pady=(5, 0))

        self.status_label = Label(
            self.bottom_bar,
            bg=THEME["bg_primary"],
            fg=THEME["fg_text"],
            font=("sans-serif", 10),
            anchor="e"
        )
        self.status_label.pack(side=TOP, fill=X)

        self.search_var = StringVar()
        self.search_var.trace_add("write", self._on_search)
        self.input = Entry(
            self.bottom_bar,
            textvariable=self.search_var,
            bg=THEME["bg_input"],
            fg=THEME["fg_text"],
            insertbackground=THEME["fg_text"],
            highlightthickness=1,
            highlightbackground=THEME["bg_secondary"],
            highlightcolor=THEME["accent"],
            relief="flat",
            font=("sans-serif", 12)
        )
        self.input.pack(side=TOP, fill=X, pady=(0, 4))

        # ── Left panel (list view) ──
        self.left_frame = Frame(self.main_frame, bg=THEME["bg_primary"], width=300)
        self.left_frame.pack(side=LEFT, fill=BOTH, expand=False)
        self.left_frame.pack_propagate(False)

        list_container = Frame(self.left_frame, bg=THEME["bg_primary"])
        list_container.pack(side=TOP, fill=BOTH, expand=True)

        scrollbar = Scrollbar(list_container, bg=THEME["bg_secondary"])
        scrollbar.pack(side=RIGHT, fill=Y)

        self.listbox = Listbox(
            list_container,
            selectmode=SINGLE,
            bg=THEME["bg_secondary"],
            fg=THEME["fg_text"],
            selectbackground=THEME["accent"],
            selectforeground=THEME["accent_fg"],
            borderwidth=0,
            highlightthickness=0,
            font=("sans-serif", 11),
            activestyle="none",
            yscrollcommand=scrollbar.set,
            takefocus=0
        )
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # ── Right panel (list view image preview) ──
        self.right_frame = Frame(self.main_frame, bg=THEME["bg_primary"])
        self.right_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))

        self.filename_label = Label(
            self.right_frame,
            bg=THEME["bg_primary"],
            fg=THEME["fg_bright"],
            font=("sans-serif", 12, "bold"),
            anchor="w"
        )
        self.filename_label.pack(side=TOP, fill=X, pady=(0, 5))

        self.image_container = Frame(self.right_frame, bg=THEME["bg_secondary"])
        self.image_container.pack(fill=BOTH, expand=True)

        self.image_label = Label(
            self.image_container,
            bg=THEME["bg_secondary"],
            text="Loading...",
            fg=THEME["fg_text"],
            font=("sans-serif", 14)
        )
        self.image_label.place(relx=0.5, rely=0.5, anchor="center")

        # ── Gallery panel ──
        self.gallery_frame = Frame(self.main_frame, bg=THEME["bg_primary"])

        self.gallery_canvas = Canvas(
            self.gallery_frame, bg=THEME["bg_primary"],
            highlightthickness=0, bd=0
        )
        self.gallery_vsb = Scrollbar(self.gallery_frame, orient="vertical",
                                     command=self.gallery_canvas.yview,
                                     bg=THEME["bg_secondary"])
        self.gallery_canvas.configure(yscrollcommand=self.gallery_vsb.set)

        self.gallery_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.gallery_vsb.pack(side=RIGHT, fill=Y)

        self.gallery_inner = Frame(self.gallery_canvas, bg=THEME["bg_primary"])
        self._gallery_inner_id = self.gallery_canvas.create_window(
            (0, 0), window=self.gallery_inner, anchor=NW
        )
        self.gallery_inner.bind(
            "<Configure>",
            lambda e: self.gallery_canvas.configure(
                scrollregion=self.gallery_canvas.bbox("all"))
        )
        self.gallery_canvas.bind("<Configure>", self._on_gallery_canvas_resize)
        self.gallery_canvas.bind("<MouseWheel>", self._on_gallery_mousewheel)
        self.gallery_vsb.bind("<MouseWheel>", self._on_gallery_mousewheel)

    # ── Event bindings ──
    def _bind_events(self):
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self.listbox.bind("<Double-Button-1>", self._on_confirm)

        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        for widget in (self.input, self.listbox):
            widget.bind("<Up>", self._nav_up)
            widget.bind("<Down>", self._nav_down)
        self.input.bind("<Left>", self._nav_left)
        self.input.bind("<Right>", self._nav_right)

        self.input.bind("<Return>", self._on_confirm)
        self.input.bind("<Control-Return>", self._on_ctrl_return)
        self.input.bind("<Escape>", self._on_cancel)
        self.input.bind("<Control-c>", self._on_ctl_c)
        self.listbox.bind("<Return>", self._on_confirm)
        self.listbox.bind("<Control-Return>", self._on_ctrl_return)
        self.listbox.bind("<Escape>", self._on_cancel)
        self.listbox.bind("<Control-c>", self._on_ctl_c)

        self.listbox.bind("<Button-1>", self._refocus_entry)
        self.listbox.bind("<Key>", self._refocus_input)
        self.listbox.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.image_container.bind("<Configure>", self._on_container_resize)

        # View toggle
        self.root.bind("<Control-g>", self._toggle_view)
        self.root.bind("<Control-G>", self._toggle_view)
        self.input.bind("<Tab>", self._toggle_view)
        self.listbox.bind("<Tab>", self._toggle_view)
        self.gallery_canvas.bind("<Tab>", self._toggle_view)

        # Gallery keys
        self.gallery_canvas.bind("<Return>", self._on_confirm)
        self.gallery_canvas.bind("<Control-Return>", self._on_ctrl_return)
        self.gallery_canvas.bind("<Escape>", self._on_cancel)
        self.gallery_canvas.bind("<Control-c>", self._on_ctl_c)
        self.gallery_canvas.bind("<Up>", self._gallery_move_up)
        self.gallery_canvas.bind("<Down>", self._gallery_move_down)
        self.gallery_canvas.bind("<Left>", self._gallery_move_left)
        self.gallery_canvas.bind("<Right>", self._gallery_move_right)
        self.gallery_canvas.bind("<Prior>", lambda e: self._gallery_page(-1))
        self.gallery_canvas.bind("<Next>", lambda e: self._gallery_page(1))
        self.gallery_canvas.bind("<Button-1>", self._refocus_entry)
        self.gallery_canvas.bind("<Key>", self._gallery_key_to_entry)

        # Scroll events for lazy gallery refresh
        self.gallery_canvas.bind("<Configure>", self._on_gallery_scroll, add="+")

    # ── Refocus helpers ──
    def _refocus_entry(self, event=None):
        self.input.focus_set()
        return "break"

    def _refocus_input(self, event=None):
        if event and len(event.char) == 1 and event.char.isprintable():
            self.input.focus_set()
            self.input.insert(END, event.char)
            self.input.icursor(END)
            return "break"

    def _gallery_key_to_entry(self, event=None):
        if event and len(event.char) == 1 and event.char.isprintable():
            self.input.focus_set()
            self.input.insert(END, event.char)
            self.input.icursor(END)
            return "break"

    def _nav_up(self, event=None):
        if self.view_mode == "gallery":
            return self._gallery_move_up(event)
        return self._focus_list_up(event)

    def _nav_down(self, event=None):
        if self.view_mode == "gallery":
            return self._gallery_move_down(event)
        return self._focus_list_down(event)

    def _nav_left(self, event=None):
        if self.view_mode == "gallery":
            return self._gallery_move_left(event)

    def _nav_right(self, event=None):
        if self.view_mode == "gallery":
            return self._gallery_move_right(event)

    # ── List population ──
    def _populate_list(self):
        self.listbox.delete(0, END)
        for label, _ in self.filtered_items:
            self.listbox.insert(END, label)
        self._update_list_appearance()
        if self.filtered_items:
            self.listbox.select_set(0)

    def _update_list_appearance(self):
        for i, (label, path) in enumerate(self.filtered_items):
            if path in self.selected_paths:
                self.listbox.itemconfig(i, bg=THEME["selected_bg"], fg=THEME["selected_fg"])
            else:
                self.listbox.itemconfig(i, bg=THEME["bg_secondary"], fg=THEME["fg_text"])

    def _append_to_list(self, path):
        if self._closing:
            return
        label = os.path.basename(path)
        self.all_items.append((label, path))
        self.filtered_items.append((label, path))
        idx = len(self.filtered_items) - 1
        self.listbox.insert(END, label)
        if path in self.selected_paths:
            self.listbox.itemconfig(idx, bg=THEME["selected_bg"], fg=THEME["selected_fg"])
        self.path_to_abs_index[path] = len(self.all_items) - 1
        if self.view_mode == "gallery":
            self._reset_gallery_tiles()
            self._schedule_gallery_refresh()

        if idx == 0:
            self.listbox.select_set(0)
            self._select_and_show(0)

    # ── Search ──
    def _on_search(self, *args):
        query = self.search_var.get().lower().strip()
        terms = query.split() if query else []

        self.filtered_items = [
            item for item in self.all_items
            if not terms or all(term in item[0].lower() for term in terms)
        ]

        self._populate_list()
        if self.filtered_items:
            self._last_index = -1
            self._select_and_show(0)
        else:
            self._last_index = -1
            self.filename_label.config(text="No matches")
            self.image_label.config(image="", text="No matches")
            self._base_status_text = "No matches"
            self.status_label.config(
                text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected")

        if self.view_mode == "gallery":
            self._schedule_gallery_refresh()

    def _reset_gallery_tiles(self):
        for tile in self._gallery_tiles.values():
            tile.destroy()
        self._gallery_tiles.clear()
        self._gallery_gen += 1
        self._gallery_grid_dirty = True
        self._gallery_built = False

    # ── Selection & display ──
    def _on_list_select(self, event=None):
        sel = self.listbox.curselection()
        if sel:
            self._select_and_show(sel[0])
        self._refocus_entry()

    def _select_and_show(self, index, from_gallery=False):
        if not self.filtered_items:
            return
        index = max(0, min(index, len(self.filtered_items) - 1))
        if index == self._last_index and not from_gallery:
            return

        if self.idx_write_path:
            _, path = self.filtered_items[index]
            abs_idx = self.path_to_abs_index.get(path, -1)
            if abs_idx != -1:
                try:
                    with open(self.idx_write_path, 'w') as IDX_FILE:
                        IDX_FILE.write(str(abs_idx))
                except Exception:
                    pass

        self.listbox.selection_clear(0, END)
        self.listbox.select_set(index)
        self.listbox.see(index)

        self._last_index = index
        label, path = self.filtered_items[index]

        self._update_gallery_selection(index)

        if self.view_mode == "gallery":
            self._scroll_gallery_to(index)
            self._base_status_text = f"{index + 1} / {len(self.filtered_items)}"
            self.status_label.config(
                text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected")
            return

        self.filename_label.config(text=label)
        self.image_label.config(image="", text="Loading...")
        self._base_status_text = f"Loading...  |  {index + 1} / {len(self.filtered_items)}"
        self.status_label.config(
            text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected")

        cw = max(self.image_container.winfo_width() - 20, 50)
        ch = max(self.image_container.winfo_height() - 20, 50)
        self._load_thumbnail_async(
            path, cw, ch,
            lambda photo, orig_size, i=index, p=path:
                self._on_preview_ready(i, p, photo, orig_size)
        )

        self._preload_neighbors(index)

    def _on_preview_ready(self, index, path, photo, orig_size):
        if self._closing or index != self._last_index:
            return
        if self.view_mode != "list":
            return
        if photo is None:
            self.image_label.config(image="", text="Failed to load")
            self._base_status_text = "Error loading image"
        else:
            w, h = orig_size
            try:
                size_kb = os.path.getsize(path) / 1024
            except Exception:
                size_kb = 0
            self.image_label.config(image=photo, text="")
            self.image_label.image = photo
            self._base_status_text = (
                f"{w}×{h}  |  {size_kb:.1f} KB  |  "
                f"{index + 1} / {len(self.filtered_items)}"
            )
        self.status_label.config(
            text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected")

    def _preload_neighbors(self, center_index):
        if self._closing:
            return
        cw = max(self.image_container.winfo_width() - 20, 50)
        ch = max(self.image_container.winfo_height() - 20, 50)
        for offset in range(-PRELOAD_AHEAD, PRELOAD_AHEAD + 1):
            if offset == 0:
                continue
            idx = center_index + offset
            if 0 <= idx < len(self.filtered_items):
                _, path = self.filtered_items[idx]
                self._load_thumbnail_async(path, cw, ch,
                                           lambda photo, orig_size: None)

    def _on_container_resize(self, event=None):
        if self._closing:
            return
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(150, self._on_resize_done)

    def _on_resize_done(self):
        if self._closing:
            return
        if self._last_index >= 0 and self.filtered_items and self.view_mode == "list":
            self._select_and_show(self._last_index, from_gallery=True)

    # ── Navigation (list view) ──
    def _focus_list_up(self, event=None):
        if self.listbox.size() == 0:
            return "break"
        curr = self.listbox.curselection()
        idx = curr[0] if curr else 0
        new_idx = (idx - 1) % self.listbox.size()
        self._select_and_show(new_idx)
        return "break"

    def _focus_list_down(self, event=None):
        if self.listbox.size() == 0:
            return "break"
        curr = self.listbox.curselection()
        idx = curr[0] if curr else 0
        new_idx = (idx + 1) % self.listbox.size()
        self._select_and_show(new_idx)
        return "break"

    def _on_mousewheel(self, event=None):
        if self.view_mode == "gallery":
            self._on_gallery_mousewheel(event)
            return
        if event and self.listbox.winfo_exists():
            self.listbox.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Multi-select ──
    def _on_ctrl_return(self, event=None):
        if not self.filtered_items or self._last_index < 0:
            return "break"
        path = self.filtered_items[self._last_index][1]
        if path in self.selected_paths:
            self.selected_paths.discard(path)
        else:
            self.selected_paths.add(path)
        self._update_list_appearance()
        self._update_gallery_selection(self._last_index)
        self.status_label.config(
            text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected")
        return "break"

    def _on_ctl_c(self, event=None):
        self.selected_path = None
        self.selected_label = None
        self.selected_paths = set()
        self.selected_paths_list = []
        self.selected_labels_list = []
        self._shutdown()
        self.root.quit()
        sys.exit(99)

    def _on_confirm(self, event=None):
        result_paths = []
        result_labels = []
        for label, path in self.all_items:
            if path in self.selected_paths and path not in result_paths:
                result_paths.append(path)
                result_labels.append(label)

        if self._last_index >= 0 and self.filtered_items:
            current_label, current_path = self.filtered_items[self._last_index]
            if current_path not in result_paths:
                result_paths.append(current_path)
                result_labels.append(current_label)
            self.selected_path = current_path
            self.selected_label = current_label
        else:
            self.selected_path = None
            self.selected_label = None

        self.selected_paths_list = result_paths
        self.selected_labels_list = result_labels
        self._shutdown()
        self.root.quit()

    def _on_cancel(self, event=None):
        self.selected_path = None
        self.selected_label = None
        self.selected_paths = set()
        self.selected_paths_list = []
        self.selected_labels_list = []
        self._shutdown()
        self.root.quit()

    def _shutdown(self):
        if self._closing:
            return
        self._closing = True
        self._decode_stop.set()
        try:
            while True:
                self._decode_q.get_nowait()
        except queue.Empty:
            pass
        for _ in self._decode_threads:
            try:
                self._decode_q.put_nowait(None)
            except Exception:
                pass
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        if self._gallery_resize_after:
            try:
                self.root.after_cancel(self._gallery_resize_after)
            except Exception:
                pass

    # ── Lazy Scanning ──
    def start_lazy_scan(self, paths, recursive=False, sort_time=False):
        self._scan_done.clear()
        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(paths, recursive, sort_time),
            daemon=True
        )
        self._scan_thread.start()

    def _scan_worker(self, paths, recursive, sort_time):
        seen = set()
        for path in paths:
            if self._closing:
                break
            p = Path(path).expanduser().resolve()
            if not p.exists():
                continue
            if p.is_dir():
                pattern = "**/*" if recursive else "*"
                files = p.glob(pattern)
                if sort_time:
                    files = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
                else:
                    files = sorted(files)
                for f in files:
                    if self._closing:
                        return
                    if f.suffix.lower() in SUPPORTED_EXTS and f not in seen:
                        seen.add(f)
                        self.root.after(0, lambda fp=str(f): self._append_to_list(fp))
            elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTS and str(p) not in seen:
                seen.add(str(p))
                self.root.after(0, lambda fp=str(p): self._append_to_list(fp))
        self._scan_done.set()

    # ── View switching ──
    def _toggle_view(self, event=None):
        if self.view_mode == "list":
            self._show_gallery()
        else:
            self._show_list()
        return "break"

    def _show_list(self):
        self.view_mode = "list"
        self.gallery_frame.pack_forget()
        self.left_frame.pack(side=LEFT, fill=BOTH, expand=False)
        self.right_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(10, 0))
        self.input.focus_set()
        if self._last_index >= 0 and self.filtered_items:
            self._select_and_show(self._last_index, from_gallery=True)

    def _show_gallery(self):
        self.view_mode = "gallery"
        self.left_frame.pack_forget()
        self.right_frame.pack_forget()
        self.gallery_frame.pack(side=LEFT, fill=BOTH, expand=True)
        self._reset_gallery_tiles()
        self.input.focus_set()
        self.root.update_idletasks()
        self._schedule_gallery_refresh(immediate=True)
        if self._last_index >= 0:
            self._scroll_gallery_to(self._last_index)
        self._base_status_text = (
            f"Gallery  |  {self._last_index + 1 if self._last_index >= 0 else 0}"
            f" / {len(self.filtered_items)}"
        )
        self.status_label.config(
            text=f"{self._base_status_text}  |  {len(self.selected_paths)} selected"
        )

    # ── Lazy gallery ──────────────────────────────────────────────────────────

    def _schedule_gallery_refresh(self, immediate=False):
        if self._closing or self.view_mode != "gallery":
            return
        if self._gallery_resize_after:
            self.root.after_cancel(self._gallery_resize_after)
        delay = 0 if immediate else 50
        self._gallery_resize_after = self.root.after(delay, self._refresh_gallery)

    def _on_gallery_canvas_resize(self, event=None):
        self._gallery_grid_dirty = True
        self._schedule_gallery_refresh(immediate=True)

    def _on_gallery_scroll(self, event=None):
        self._schedule_gallery_refresh()

    def _on_gallery_mousewheel(self, event=None):
        if self.view_mode != "gallery" or event is None:
            return
        self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._schedule_gallery_refresh()

    def _compute_tile_metrics(self):
        """Return (tile_w, tile_h, caption_h, pad) sized for the viewport,
        honouring --gallery-rows / --gallery-cols / --gallery-tile-size."""
        cw = self.gallery_canvas.winfo_width()
        ch = self.gallery_canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw = max(self.root.winfo_width(), 1)
            ch = max(self.root.winfo_height(), 1)
        if cw <= 1 or ch <= 1:
            cw, ch = 1200, 800  # window not yet mapped

        if self._gallery_tile_opt is not None:
            base = float(self._gallery_tile_opt)
        else:
            candidates = []
            rows = self._gallery_rows_opt or GALLERY_TARGET_ROWS
            candidates.append(ch / float(rows))
            if self._gallery_cols_opt:
                candidates.append(cw / float(self._gallery_cols_opt))
            base = min(candidates)

        q = GALLERY_SIZE_QUANTUM
        tile = int(round(base / q)) * q
        tile = max(GALLERY_TILE_MIN, min(GALLERY_TILE_MAX, tile))
        pad = max(GALLERY_PAD_MIN, int(round(tile * GALLERY_PAD_RATIO)))
        cap = max(GALLERY_CAPTION_MIN, int(round(tile * GALLERY_CAPTION_RATIO)))
        return tile, tile, cap, pad

    def _update_tile_metrics(self):
        """Recompute tile metrics. Returns True if they changed."""
        tw, th, cap, pad = self._compute_tile_metrics()
        if (tw, th, cap, pad) == (self._tile_w, self._tile_h,
                                  self._tile_caption_h, self._tile_pad):
            return False
        self._tile_w = tw
        self._tile_h = th
        self._tile_caption_h = cap
        self._tile_pad = pad
        self._tile_thumb_max = (max(1, tw - 5), max(1, th - 5))
        return True

    def _compute_cols(self):
        canvas_w = max(self.gallery_canvas.winfo_width(), 1)
        cols = max(1, (canvas_w - self._tile_pad) // (self._tile_w + self._tile_pad))
        return cols


    def _refresh_gallery(self):
        if self._closing or self.view_mode != "gallery":
            return

        if self._update_tile_metrics():
            # Tile size changed — recycle everything so tiles pick up new geometry.
            for tile in self._gallery_tiles.values():
                tile.destroy()
            self._gallery_tiles.clear()
            self._gallery_gen += 1
            self._gallery_cols = 0  # force column recompute


        if not self.filtered_items:
            for tile in self._gallery_tiles.values():
                tile.destroy()
            self._gallery_tiles.clear()
            self._gallery_built = True
            self._pending_gallery_scroll = None
            return

        if (self.gallery_canvas.winfo_width() <= 1
                or self.gallery_canvas.winfo_height() <= 1):
            return

        cols = self._compute_cols()
        if cols != self._gallery_cols:
            self._gallery_cols = cols
            for tile in self._gallery_tiles.values():
                tile.destroy()
            self._gallery_tiles.clear()
            self._gallery_gen += 1

        row_h = self._tile_h + self._tile_caption_h + self._tile_pad
        col_w = self._tile_w + self._tile_pad
        total_rows = (len(self.filtered_items) + cols - 1) // cols
        total_h = total_rows * row_h + self._tile_pad

        self.gallery_inner.configure(width=cols * col_w + self._tile_pad,
                                     height=max(total_h, 1))
        self.gallery_canvas.coords(self._gallery_inner_id, 0, 0)
        self.gallery_canvas.configure(
            scrollregion=(0, 0, cols * col_w + self._tile_pad, total_h))

        if self._pending_gallery_scroll is not None:
            idx = self._pending_gallery_scroll
            self._pending_gallery_scroll = None
            self._apply_gallery_scroll(idx)

        canvas_h = max(self.gallery_canvas.winfo_height(), 1)
        y_top = self.gallery_canvas.canvasy(0)
        first_row = max(0, int(y_top // row_h) - GALLERY_OVERSCAN_ROWS)
        last_row = min(total_rows - 1,
                       int((y_top + canvas_h) // row_h) + GALLERY_OVERSCAN_ROWS)
        first_idx = first_row * cols
        last_idx = min(len(self.filtered_items), (last_row + 1) * cols)

        for idx in list(self._gallery_tiles.keys()):
            if idx < first_idx or idx >= last_idx:
                self._gallery_tiles.pop(idx).destroy()

        tw, th = self._tile_thumb_max
        for idx in range(first_idx, last_idx):
            label, path = self.filtered_items[idx]
            tile = self._gallery_tiles.get(idx)
            needs_thumb = False

            if tile is None:
                tile = GalleryTile(self.gallery_inner, self, idx, label, path)
                r = idx // cols
                c = idx % cols
                tile.place(x=c * col_w + self._tile_pad // 2,
                           y=r * row_h + self._tile_pad // 2,
                           width=self._tile_w,
                           height=self._tile_h + self._tile_caption_h)
                self._gallery_tiles[idx] = tile
                needs_thumb = True
            elif tile.update_item(idx, label, path):
                needs_thumb = True

            tile.set_selected(path in self.selected_paths)
            tile.set_current(idx == self._last_index)

            if needs_thumb:
                # Pass the expected path so a late callback from a previous
                # item at this grid slot can't paint the wrong thumbnail.
                self._load_thumbnail_async(
                    path, tw, th,
                    lambda photo, orig_size, i=idx, p=path, g=self._gallery_gen:
                        self._on_gallery_thumb_ready(i, p, photo, g)
                )



        self._gallery_built = True

    def _on_gallery_thumb_ready(self, index, expected_path, photo, gen):
        if self._closing or gen != self._gallery_gen:
            return
        tile = self._gallery_tiles.get(index)
        if tile is None or tile.path != expected_path:
            return
        tile.set_photo(photo)

    def _update_gallery_selection(self, current_index):
        for idx, tile in self._gallery_tiles.items():
            if idx >= len(self.filtered_items):
                continue
            path = self.filtered_items[idx][1]
            tile.set_selected(path in self.selected_paths)
            tile.set_current(idx == current_index)

    def _scroll_gallery_to(self, index):
        if index < 0 or index >= len(self.filtered_items):
            return
        self._pending_gallery_scroll = index
        self._schedule_gallery_refresh(immediate=True)

    def _apply_gallery_scroll(self, index):
        """Move the canvas so that item `index` is fully inside the viewport.

        Must be called only from `_refresh_gallery`, after the scrollregion
        and gallery_inner geometry have been set for the current column count.
        """
        cols = max(self._gallery_cols, 1)
        row = index // cols
        row_h = self._tile_h + self._tile_caption_h + self._tile_pad
        row_top = row * row_h
        row_bottom = row_top + row_h

        canvas_h = max(self.gallery_canvas.winfo_height(), 1)
        y_top = self.gallery_canvas.canvasy(0)
        y_bottom = y_top + canvas_h

        if row_top < y_top:
            new_top = row_top
        elif row_bottom > y_bottom:
            new_top = row_bottom - canvas_h
        else:
            return

        total = max(self.gallery_inner.winfo_reqheight(), 1)
        self.gallery_canvas.yview_moveto(max(0.0, min(1.0, new_top / total)))

    # ── Gallery navigation ──
    def _gallery_cols_count(self):
        return max(1, self._gallery_cols)

    def _gallery_move_up(self, event=None):
        if not self.filtered_items:
            return "break"
        idx = max(0, self._last_index - self._gallery_cols_count())
        self._select_and_show(idx, from_gallery=True)
        return "break"

    def _gallery_move_down(self, event=None):
        if not self.filtered_items:
            return "break"
        idx = min(len(self.filtered_items) - 1,
                  self._last_index + self._gallery_cols_count())
        self._select_and_show(idx, from_gallery=True)
        return "break"

    def _gallery_move_left(self, event=None):
        if not self.filtered_items:
            return "break"
        idx = max(0, self._last_index - 1)
        self._select_and_show(idx, from_gallery=True)
        return "break"

    def _gallery_move_right(self, event=None):
        if not self.filtered_items:
            return "break"
        idx = min(len(self.filtered_items) - 1, self._last_index + 1)
        self._select_and_show(idx, from_gallery=True)
        return "break"

    def _gallery_page(self, direction):
        if not self.filtered_items:
            return "break"
        cols = self._gallery_cols_count()
        canvas_h = max(self.gallery_canvas.winfo_height(), 1)
        rows = max(1, canvas_h // (self._tile_h + self._tile_caption_h + self._tile_pad))
        step = cols * rows * direction
        idx = max(0, min(len(self.filtered_items) - 1, self._last_index + step))
        self._select_and_show(idx, from_gallery=True)
        return "break"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def collect_images(paths, recursive=False, sort_time=False):
    images = []
    seen = set()
    for path in paths:
        p = Path(path).expanduser().resolve()
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files = p.glob(pattern)
            files = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True) if sort_time else sorted(files)
            for f in files:
                if f.suffix.lower() in SUPPORTED_EXTS and f not in seen:
                    images.append(str(f))
                    seen.add(f)
        elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTS and str(p) not in seen:
            images.append(str(p))
            seen.add(str(p))
    return images


def parse_args():
    parser = argparse.ArgumentParser(description="High-performance interactive image selector")
    parser.add_argument("paths", nargs="*", default=["."], help="Directories or files to browse")
    parser.add_argument("-r", "--recursive", action="store_true", help="Search recursively")
    parser.add_argument("-t", "--time", action="store_true", help="Sort by modification time (newest first)")
    parser.add_argument("--lazy", action="store_true", help="Lazy scan: show UI immediately, populate as files are found")
    parser.add_argument("--dmenu-mode", action="store_true", help="Enable dmenu mode (list entries + image paths)")
    parser.add_argument("--list-file", help="File containing newline-separated list entries")
    parser.add_argument("--list-entries", help="Newline-separated list entries (as a string)")
    parser.add_argument("--image-file", help="File containing newline-separated image file paths")
    parser.add_argument("--image-entries", help="Newline-separated image file paths (as a string)")
    parser.add_argument("--pass-idx", help="Pass the index to start the selector at")
    parser.add_argument("--idx-write-path", help="File path to write the current index for debugging")
    parser.add_argument("--return-label", action="store_true", help="In dmenu mode, output the selected list label instead of the image path")
    parser.add_argument("--pre-select", help="Newline-separated labels to pre-select at launch")
    parser.add_argument("--custom-title", help="Title of the window")
    parser.add_argument("--pre-select-file", help="File containing newline-separated labels to pre-select")
    parser.add_argument("--gallery", action="store_true", help="Start in gallery view")
    parser.add_argument("--gallery-rows", type=float, default=None,
                        help="Target number of gallery rows visible (default 3.5)")
    parser.add_argument("--gallery-cols", type=int, default=None,
                        help="Target number of gallery columns visible")
    parser.add_argument("--gallery-tile-size", type=int, default=None,
                        help="Explicit gallery tile size in pixels (overrides rows/cols)")
    return parser.parse_args()


def read_pre_select(args):
    if args.pre_select and args.pre_select_file:
        print("Error: both --pre-select and --pre-select-file provided.", file=sys.stderr)
        sys.exit(1)
    if args.pre_select_file:
        try:
            with open(args.pre_select_file, 'r') as f:
                return [line.rstrip('\n') for line in f]
        except Exception as e:
            print(f"Error reading pre-select file: {e}", file=sys.stderr)
            sys.exit(1)
    if args.pre_select:
        return args.pre_select.split('\n')
    return None


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    pre_select_labels = read_pre_select(args)
    custom_title = args.custom_title or ""
    pass_idx = int(args.pass_idx) if args.pass_idx else 0
    idx_write_path = args.idx_write_path or ""

    if args.dmenu_mode:
        if args.list_file and args.list_entries:
            print("Error: both --list-file and --list-entries provided.", file=sys.stderr)
            sys.exit(1)
        if args.list_file:
            try:
                with open(args.list_file, 'r') as f:
                    list_entries = [line.rstrip('\n') for line in f]
            except Exception as e:
                print(f"Error reading list file: {e}", file=sys.stderr)
                sys.exit(1)
        elif args.list_entries:
            list_entries = args.list_entries.split('\n')
        else:
            print("Error: must provide either --list-file or --list-entries", file=sys.stderr)
            sys.exit(1)

        if args.image_file and args.image_entries:
            print("Error: both --image-file and --image-entries provided.", file=sys.stderr)
            sys.exit(1)
        if args.image_file:
            try:
                with open(args.image_file, 'r') as f:
                    image_entries = [line.rstrip('\n') for line in f]
            except Exception as e:
                print(f"Error reading image file: {e}", file=sys.stderr)
                sys.exit(1)
        elif args.image_entries:
            image_entries = args.image_entries.split('\n')
        else:
            print("Error: must provide either --image-file or --image-entries", file=sys.stderr)
            sys.exit(1)

        if len(list_entries) != len(image_entries):
            print(f"Error: number of list entries ({len(list_entries)}) and image entries ({len(image_entries)}) do not match", file=sys.stderr)
            sys.exit(1)

        root = Tk()
        app = ImageSelector(root, image_entries, display_labels=list_entries,
                            pre_select_labels=pre_select_labels,
                            pass_idx=pass_idx, idx_write_path=idx_write_path,
                            custom_title=custom_title,
                            gallery_rows=args.gallery_rows,
                            gallery_cols=args.gallery_cols,
                            gallery_tile_size=args.gallery_tile_size)

        if args.gallery:
            app._show_gallery()
        root.mainloop()

        if hasattr(app, 'selected_paths_list') and app.selected_paths_list:
            if args.return_label:
                for label in app.selected_labels_list:
                    print(label)
            else:
                for path in app.selected_paths_list:
                    print(path)
            sys.stdout.flush()
            os._exit(0)
        elif app.selected_path is not None:
            if args.return_label:
                print(app.selected_label)
            else:
                print(app.selected_path)
            sys.stdout.flush()
            os._exit(0)
        else:
            os._exit(1)

    if args.lazy:
        root = Tk()
        app = ImageSelector(root, [], pre_select_labels=pre_select_labels,
                            pass_idx=pass_idx, idx_write_path=idx_write_path,
                            custom_title=custom_title,
                            gallery_rows=args.gallery_rows,
                            gallery_cols=args.gallery_cols,
                            gallery_tile_size=args.gallery_tile_size)
        if args.gallery:
            app._show_gallery()
        app.start_lazy_scan(args.paths, recursive=args.recursive, sort_time=args.time)
        root.mainloop()
    else:
        images = collect_images(args.paths, recursive=args.recursive, sort_time=args.time)
        if not images:
            print("No images found.", file=sys.stderr)
            sys.exit(1)

        root = Tk()
        app = ImageSelector(root, images, pre_select_labels=pre_select_labels,
                            pass_idx=pass_idx, idx_write_path=idx_write_path,
                            custom_title=custom_title,
                            gallery_rows=args.gallery_rows,
                            gallery_cols=args.gallery_cols,
                            gallery_tile_size=args.gallery_tile_size)

        if args.gallery:
            app._show_gallery()
        root.mainloop()

    if hasattr(app, 'selected_paths_list') and app.selected_paths_list:
        for path in app.selected_paths_list:
            print(path)
        sys.stdout.flush()
        os._exit(0)
    elif app.selected_path is not None:
        print(app.selected_path)
        sys.stdout.flush()
        os._exit(0)
    else:
        os._exit(1)


if __name__ == "__main__":
    main()
