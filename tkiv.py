#!/usr/bin/env python3
"""
tkiv — combined image viewer (nsxiv-like) and image selector (dmenu-like)
in a single program.

Usage:
    tkiv.py img [OPTIONS] FILES...
        Act as an image viewer.

    tkiv.py select [OPTIONS] PATHS...
        Act as an image selector / dmenu alternative.

Viewer keybindings (search bar is always focused; single-letter actions
use Ctrl+):
    q            Ctrl+Q        quit
    Tab          cycle mode (image -> gallery -> list -> image)
    Shift+Tab    reverse cycle
    Return       switch mode (image <-> gallery; list -> image)
    Esc          clear search if any, else quit
    f            Ctrl+F        fullscreen
    b            Ctrl+B        toggle status bar
    r            Ctrl+R        reload
    Ctrl+D       remove current file
    n / p        Ctrl+N / Ctrl+P     next / previous (respects filter)
    ] / [        Ctrl+] / Ctrl+[     +/- 10 files
    g / G        Ctrl+Home / Ctrl+End  first / last
    m            Ctrl+M        toggle mark
    w / W / F    Ctrl+W / Ctrl+Shift+W / Ctrl+Shift+F   fit down/fit/fill
    e / E        Ctrl+E / Ctrl+Shift+E   fit width / fit height
    + / -        Ctrl++ / Ctrl+-        zoom in / out
    Ctrl+0       100%% zoom
    z            Ctrl+Z        center image
    h j k l      Ctrl+H/J/K/L  pan
    Ctrl+Space   toggle animation
    s            Ctrl+S        slideshow
    < > ?        Ctrl+< / Ctrl+> / Ctrl+?  rotate
    | _          Ctrl+| / Ctrl+_  flip
    a / A        Ctrl+I / Ctrl+Shift+I  toggle antialias / alpha
    ( )          Ctrl+( / Ctrl+)  contrast down/up
    { }          Ctrl+{ / Ctrl+}  gamma down/up
"""

# ============================================================ imports
import argparse
import hashlib
import os
import queue
import stat
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageOps, ImageEnhance, ImageFile
except ImportError:
    sys.stderr.write("Error: Pillow is required. Install with: pip install Pillow\n")
    sys.exit(1)
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import pyvips
    import numpy as np
    HAVE_VIPS = True
    HAS_VIPS = True
    HAS_NUMPY = True
except ImportError:
    pyvips = None
    np = None
    HAVE_VIPS = False
    HAS_VIPS = False
    HAS_NUMPY = False

import tkinter as tk
from tkinter import font as tkfont
from tkinter import (Tk, Frame, Listbox, Entry, Label, Scrollbar, StringVar,
                     Canvas, BOTH, LEFT, RIGHT, TOP, BOTTOM, X, Y, END, SINGLE,
                     NW, NSEW)


# ============================================================ shared theme
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


# ============================================================ constants
VERSION  = "0.3.0"
PROGNAME = "tkiv"

SCALE_DOWN   = 'd'
SCALE_FIT    = 'f'
SCALE_FILL   = 'F'
SCALE_WIDTH  = 'w'
SCALE_HEIGHT = 'h'
SCALE_ZOOM   = 'z'

ZOOM_LEVELS = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0, 8.0]
ZOOM_MIN, ZOOM_MAX = ZOOM_LEVELS[0], ZOOM_LEVELS[-1]

SLIDESHOW_DELAY   = 5
DEF_ANIM_DELAY    = 75
CC_STEPS          = 32
GAMMA_MAX         = 10.0
BRIGHTNESS_MAX    = 2.0
CONTRAST_MAX      = 4.0

MODE_IMAGE, MODE_GALLERY, MODE_LIST = 'i', 'g', 'l'

FF_MARK, FF_WARN = 1, 2

DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN = 1, 2, 4, 8
DEGREE_90, DEGREE_180, DEGREE_270     = 1, 2, 3
FLIP_HORIZONTAL, FLIP_VERTICAL        = 1, 2

IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
    '.webp', '.ppm', '.pgm', '.pbm', '.pnm', '.ico', '.jpe',
    '.jfif', '.pcx', '.tga', '.xpm', '.jp2', '.j2k',
    '.avif', '.heic', '.heif',
}

MAX_LOAD_DIM = 4096

IMG_WORKERS         = 4
THUMB_WORKERS       = 4
PREFETCH_MAX        = 3
THUMB_MAX_IN_FLIGHT = 12
QUEUE_POLL_MS       = 20

GALLERY_TILE_MIN   = 96
GALLERY_TILE_MAX   = 512
GALLERY_TARGET_ROWS = 3.5
GALLERY_CAPTION_RATIO = 0.16
GALLERY_CAPTION_MIN   = 22
GALLERY_PAD_RATIO     = 0.045
GALLERY_PAD_MIN       = 6
GALLERY_SIZE_QUANTUM  = 8
GALLERY_OVERSCAN_ROWS = 2
GALLERY_ZOOM_STEP     = 32

# Aspect-ratio-aware tiles (mirrors sel_img.py behaviour)
GALLERY_ASPECT_DEFAULT = 16.0 / 9.0
GALLERY_ASPECT_MIN     = 0.4
GALLERY_ASPECT_MAX     = 3.0
GALLERY_ASPECT_SAMPLE  = 20

# selector-only constants
CACHE_SIZE = 800
PRELOAD_AHEAD = 3
DECODE_WORKERS = max(2, min(8, os.cpu_count() or 4))
DISK_CACHE_ENABLED = True
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "tkiv_thumbs"
CACHE_WEBP_QUALITY = 82


# ============================================================ helpers
def file_is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def collect_dir(d, recursive, include_hidden, sort_time=False):
    out = []
    try:
        entries = sorted(os.listdir(d))
    except OSError:
        return out

    subdirs = []
    for name in entries:
        if not include_hidden and name.startswith('.'):
            continue
        full = os.path.join(d, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            if recursive:
                subdirs.append(full)
        elif stat.S_ISREG(st.st_mode) and file_is_image(full):
            out.append(full)

    for s in subdirs:
        out.extend(collect_dir(s, recursive, include_hidden, sort_time))

    if sort_time:
        try:
            out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        except OSError:
            pass
    return out


def _vips_to_pil(vimg):
    if vimg.format != 'uchar':
        vimg = vimg.cast('uchar')
    arr = vimg.numpy()
    if arr.ndim == 2:
        if not arr.flags['C_CONTIGUOUS']:
            arr = np.ascontiguousarray(arr)
        return Image.fromarray(arr, 'L')
    b = arr.shape[2]
    if not arr.flags['C_CONTIGUOUS']:
        arr = np.ascontiguousarray(arr)
    if b == 1:
        return Image.fromarray(arr[:, :, 0], 'L')
    if b == 2:
        return Image.fromarray(arr, 'LA')
    if b == 3:
        return Image.fromarray(arr, 'RGB')
    if b == 4:
        return Image.fromarray(arr, 'RGBA')
    return Image.fromarray(arr[:, :, :4], 'RGBA')


def _vips_load_frames(path, max_dim=None):
    try:
        vimg = pyvips.Image.new_from_file(path, n=-1)
    except Exception:
        vimg = pyvips.Image.new_from_file(path)

    n_pages = 1
    try:
        n_pages = int(vimg.get('n-pages') or 1)
    except Exception:
        pass
    if n_pages < 1:
        n_pages = 1

    if max_dim is not None and max_dim > 0:
        try:
            scale = max(vimg.width / max_dim, vimg.height / max_dim)
            if scale > 1.0:
                vimg = vimg.resize(1.0 / scale)
        except Exception:
            pass

    if n_pages <= 1:
        return [_vips_to_pil(vimg)], [DEF_ANIM_DELAY]

    page_height = vimg.height // n_pages
    if page_height <= 0:
        page_height = vimg.height

    frames = []
    for i in range(n_pages):
        page = vimg.crop(0, i * page_height, vimg.width, page_height)
        frames.append(_vips_to_pil(page))

    delays = []
    try:
        d = vimg.get('delay')
        if isinstance(d, (list, tuple)):
            for v in d[:n_pages]:
                try:
                    delays.append(max(1, int(v)))
                except (TypeError, ValueError):
                    delays.append(DEF_ANIM_DELAY)
        elif d is not None:
            try:
                delays = [max(1, int(d))] * n_pages
            except (TypeError, ValueError):
                pass
    except Exception:
        pass

    while len(delays) < n_pages:
        delays.append(DEF_ANIM_DELAY)

    return frames, delays[:n_pages]


def _pil_load_frames(path):
    frames, delays = [], []
    im = Image.open(path)
    n_frames = getattr(im, 'n_frames', 1)
    if n_frames > 1:
        try:
            for i in range(n_frames):
                im.seek(i)
                f = im.convert('RGBA').copy()
                d = im.info.get('duration', DEF_ANIM_DELAY) or DEF_ANIM_DELAY
                frames.append(f)
                delays.append(max(1, d))
        except Exception:
            frames, delays = [], []
    if not frames:
        im = Image.open(path)
        if im.mode not in ('RGB', 'RGBA', 'L', 'LA'):
            im = im.convert('RGBA')
        frames, delays = [im], [DEF_ANIM_DELAY]
    return frames, delays


def load_frames(path, max_dim=MAX_LOAD_DIM):
    if HAVE_VIPS:
        try:
            return _vips_load_frames(path, max_dim=max_dim)
        except Exception:
            pass
    return _pil_load_frames(path)


def load_gallery_thumb(path, max_w, max_h):
    if HAVE_VIPS:
        try:
            vimg = pyvips.Image.thumbnail(path, max_w, height=max_h)
            pil_img = _vips_to_pil(vimg)
            if pil_img.mode != 'RGBA':
                pil_img = pil_img.convert('RGBA')
            return pil_img
        except Exception:
            pass
    im = Image.open(path).convert('RGBA')
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    return im


def _get_orig_size(path):
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


def _decode_thumb(path, max_w, max_h):
    """Decode with disk cache (selector path)."""
    orig_size = _get_orig_size(path)
    cache_file = _disk_cache_path(path, max_w, max_h) if DISK_CACHE_ENABLED else None

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

    if pil_img is None:
        try:
            with Image.open(path) as img:
                if img.format == "JPEG":
                    img.draft("RGB", (max_w, max_h))
                if img.width > max_w * 4 or img.height > max_h * 4:
                    factor = max(1, min(img.width // (max_w * 2),
                                        img.height // (max_h * 2)))
                    if factor > 1:
                        img = img.reduce(factor)
                img.thumbnail((max_w, max_h),
                              Image.Resampling.BILINEAR,
                              reducing_gap=2.0)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA" if "A" in img.mode else "RGB")
                img.load()
                pil_img = img
        except Exception:
            pil_img = None

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


# ============================================================ CLI
def _add_shared_ui_options(p, mode):
    """Options shared by both viewer and selector."""
    p.add_argument('-g', '-t', '--gallery', '--thumbnail',
                   action='store_true', dest='thumb_mode',
                   help='start in gallery mode')
    p.add_argument('-T', '--gallery-tile-size', '--thumb-size',
                   type=int, default=None, dest='thumb_size',
                   help='gallery tile size in pixels')
    p.add_argument('--gallery-rows', type=float, default=None,
                   help='target number of gallery rows visible (default 3.5)')
    p.add_argument('--gallery-cols', type=int, default=None,
                   help='target number of gallery columns visible')
    p.add_argument('--gallery-aspect', type=float, default=None,
                   help='gallery tile width/height ratio (default: auto-detect '
                        'from the images, e.g. 1.777 for 16:9)')
    p.add_argument('--lazy', action='store_true',
                   help='show UI immediately, populate as files are found')
    p.add_argument('-r', '--recursive', action='store_true',
                   help='search directories recursively')
    p.add_argument('-H', '--hidden', action='store_true',
                   help='include hidden files')
    p.add_argument('--time', action='store_true',
                   help='sort by modification time (newest first)')
    p.add_argument('-n', '--start-at', '--pass-idx',
                   type=int, default=1, dest='start_at',
                   help='start at index N (1-based)')
    p.add_argument('--name', '--custom-title', default=None, dest='name',
                   help='window title')
    p.add_argument('--idx-write-path', default=None,
                   help='write current index to this file (debug)')
    p.add_argument('--pre-select', default=None,
                   help='newline-separated labels to pre-select at launch')
    p.add_argument('--pre-select-file', default=None,
                   help='file containing pre-select labels')
    p.add_argument('-q', '--quiet', action='store_true')
    p.add_argument('-v', '--version', action='store_true')
    p.add_argument('-h', '--help', action='store_true')


def build_viewer_parser():
    p = argparse.ArgumentParser(
        prog=f"{PROGNAME} img", add_help=False, allow_abbrev=False,
        usage='%(prog)s [-abcgHhiopqrvZ0] [-A FRAMERATE] [-e WID] [-G GAMMA] '
              '[--geometry GEOMETRY] [-N NAME] [-n NUM] [-S DELAY] [-s MODE] '
              '[-T SIZE] [--gallery-rows N] [--gallery-cols N] '
              '[--gallery-aspect N] FILES...')
    p.add_argument('-a', '--animate', action='store_true')
    p.add_argument('-A', '--framerate', type=int, default=0)
    p.add_argument('--assume-files', action='store_true')
    p.add_argument('-b', '--no-bar', action='store_true')
    p.add_argument('--bar', action='store_true')
    p.add_argument('--floating-window', dest='floating_window',action='store_true')
    p.add_argument('-c', '--clean-cache', action='store_true')
    p.add_argument('-e', '--embed', type=int, default=0)
    p.add_argument('-f', '--fullscreen', action='store_true')
    p.add_argument('-G', '--gamma', type=int, default=0)
    p.add_argument('--geometry', default=None)
    p.add_argument('-i', '--stdin', action='store_true', dest='from_stdin')
    p.add_argument('-N', '--legacy-name', default=None, dest='legacy_name')
    p.add_argument('--class', dest='class_', default=None)
    p.add_argument('-o', '--stdout', action='store_true')
    p.add_argument('-p', '--private', action='store_true', dest='private_mode')
    p.add_argument('-S', '--ss-delay', type=float, default=0.0)
    p.add_argument('-s', '--scale-mode', default='d')
    p.add_argument('-z', '--zoom', type=int, default=0)
    p.add_argument('-Z', '--zoom-100', action='store_true')
    p.add_argument('-0', '--null', action='store_true', dest='using_null')
    p.add_argument('--anti-alias',  nargs='?', const='yes', default='yes')
    p.add_argument('--alpha-layer', nargs='?', const='no')
    p.add_argument('--cache-allow', default=None)
    p.add_argument('--cache-deny',  default=None)
    p.add_argument('--update-cache', action='store_true')
    _add_shared_ui_options(p, 'view')
    p.add_argument('files', nargs='*')
    return p


def build_selector_parser():
    p = argparse.ArgumentParser(
        prog=f"{PROGNAME} select", add_help=False, allow_abbrev=False,
        description="Interactive image selector (dmenu-like)")
    p.add_argument('--dmenu-mode', action='store_true',
                   help='enable dmenu mode (list entries + image paths)')
    p.add_argument('--list-file')
    p.add_argument('--list-entries')
    p.add_argument('--image-file')
    p.add_argument('--image-entries')
    p.add_argument('--return-label', action='store_true',
                   help='output the list label instead of the image path')
    _add_shared_ui_options(p, 'select')
    p.add_argument('paths', nargs='*', default=['.'])
    return p


def _read_pre_select(args):
    if args.pre_select and args.pre_select_file:
        sys.stderr.write("Error: both --pre-select and --pre-select-file provided.\n")
        sys.exit(1)
    if args.pre_select_file:
        try:
            with open(args.pre_select_file, 'r') as f:
                return [line.rstrip('\n') for line in f]
        except Exception as e:
            sys.stderr.write(f"Error reading pre-select file: {e}\n")
            sys.exit(1)
    if args.pre_select:
        return args.pre_select.split('\n')
    return None


# ============================================================ file entry
class FileEntry:
    __slots__ = ('name', 'path', 'flags', 'label')
    def __init__(self, name, label=None):
        self.name = name
        self.path = name
        self.flags = 0
        self.label = label if label is not None else os.path.basename(name)


# ============================================================ unified app
class TkivApp:
    """Unified viewer/selector app. `purpose` selects Enter behavior
    and output-on-exit semantics."""

    def __init__(self, root, opts, files, purpose='view',enable_floating_window=False):
        self.purpose = purpose
        self.enable_floating_window = enable_floating_window
        self.root = root
        self.opts = opts
        self.files = list(files)
        if not self.files and not getattr(opts, 'lazy', False):
            raise SystemExit("no files")

        start = max(0, min(getattr(opts, 'start_at', 1) - 1,
                           max(0, len(self.files) - 1))) if self.files else 0
        self.fileidx   = start
        self.mode      = MODE_GALLERY if opts.thumb_mode else MODE_IMAGE
        self.markidx   = 0
        self.alternate = 0
        self._timeout_ids = {}
        self._mtimes = {}
        self._resize_pending = False
        self._quitting = False
        self._scan_cancel = False

        # Filtering
        self._filter_text = ""
        self._visible_indices = list(range(len(self.files)))

        # Async infrastructure
        self._img_executor   = ThreadPoolExecutor(
            max_workers=IMG_WORKERS, thread_name_prefix='tkiv-img')
        self._thumb_executor = ThreadPoolExecutor(
            max_workers=THUMB_WORKERS, thread_name_prefix='tkiv-thumb')
        self._main_queue     = queue.Queue()
        self._load_token     = 0
        self._files_gen      = 0
        self._img_in_flight  = {}
        self._prefetch_cache = OrderedDict()

        # Image state
        self.img_frames    = []
        self.img_delays    = []
        self.img_sel       = 0
        self.img_animate   = getattr(opts, 'animate', False)
        self.img_multi_len = 0
        self.img_w = self.img_h = 0
        self.zoom = 1.0
        self.scalemode = getattr(opts, 'scale_mode', SCALE_DOWN)
        self.img_x = self.img_y = 0.0
        self.gamma = getattr(opts, 'gamma', 0)
        self.brightness = 0
        self.contrast = 0
        self.anti_alias = (getattr(opts, 'anti_alias', 'yes') != 'no')
        self.alpha_layer = (getattr(opts, 'alpha_layer', None) == 'yes')

        if getattr(opts, 'zoom_100', False):
            self.scalemode, self.zoom = SCALE_ZOOM, 1.0
        elif getattr(opts, 'zoom', 0) > 0:
            self.scalemode, self.zoom = SCALE_ZOOM, opts.zoom / 100.0

        ss_delay = getattr(opts, 'ss_delay', 0.0)
        self.ss_on    = ss_delay > 0
        self.ss_delay = (int(ss_delay * 10) if ss_delay > 0
                         else SLIDESHOW_DELAY * 10)

        # Gallery state
        self.tns_thumbs = [None] * len(self.files)
        self._gallery_in_flight = set()
        self._gallery_photos = []
        self._gallery_cols = 1
        self._gallery_rows_opt = (opts.gallery_rows
                                  if getattr(opts, 'gallery_rows', None)
                                  and opts.gallery_rows > 0 else None)
        self._gallery_cols_opt = (opts.gallery_cols
                                  if getattr(opts, 'gallery_cols', None)
                                  and opts.gallery_cols > 0 else None)
        self._gallery_tile_override = None
        ts = getattr(opts, 'thumb_size', None)
        if ts and ts > 0:
            self._gallery_tile_override = ts

        # Aspect-ratio-aware tile sizing
        ga = getattr(opts, 'gallery_aspect', None)
        self._gallery_aspect_opt = (float(ga)
                                    if ga is not None and ga > 0 else None)
        self._gallery_aspect_cache = None
        self._orig_sizes = {}   # path -> (w, h), for aspect auto-detection

        self._tile_w = 240
        self._tile_h = 240
        self._tile_caption_h = 34
        self._tile_pad = 10
        self._tile_thumb_max = (self._tile_w - 5, self._tile_h - 5)
        self._pending_gallery_scroll = None
        self._gallery_redraw_pending = False

        # Cached caption font metrics (monospace, so character count maps
        # directly to pixel width).
        self._caption_char_w = 1
        self._caption_line_h = 1

        # List state
        self._list_photo = None
        self._list_pending = -1

        # Pre-select (labels)
        pre_labels = _read_pre_select(opts) if hasattr(opts, 'pre_select') else None
        if pre_labels:
            self._apply_pre_select(pre_labels)

        self._setup_ui()
        self._setup_bindings()
        self._persist_index()
        self.root.after(50, self._initial_load)
        self.root.after(500, self._poll_autoreload)
        self.root.after(QUEUE_POLL_MS, self._poll_main_queue)

    # ---------------------------------------------------------- pre-select
    def _apply_pre_select(self, labels):
        target = set(labels)
        matched = set()
        for f in self.files:
            if f.label in target and f.label not in matched:
                f.flags |= FF_MARK
                matched.add(f.label)

    # ---------------------------------------------------------- UI
    def _setup_ui(self):
        self.bg = THEME['bg_primary']
        self.fg = THEME['fg_text']
        self.caption_fg = THEME['fg_text']
        self.border_fg = THEME['bg_secondary']
        self.mark_fg = THEME['accent']
        self.select_bg = THEME['selected_bg']
        self.select_fg = THEME['selected_fg']

        if getattr(self.opts, 'geometry', None):
            try:
                self.root.geometry(self.opts.geometry)
            except Exception:
                self.root.geometry('900x700')
        else:
            self.root.geometry('900x700')

        self.root.title(self.opts.name or 'tkiv')
        self.root.configure(bg=self.bg)

        # Selector windows use the same floating/centred setup as sel_img:
        # make the window a dialog, keep it above other windows, and give it
        # a 50px margin on every side of the screen.
        if (self.purpose == 'select') or self.enable_floating_window:
            self.root.attributes('-topmost', True)
            try:
                self.root.attributes('-type', 'dialog')
            except Exception:
                pass
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f'{sw - 100}x{sh - 100}+50+50')
            self.root.minsize(600, 400)
        elif getattr(self.opts, 'fullscreen', False):
            self.root.attributes('-fullscreen', True)

        self.bar_font = tkfont.Font(family='monospace', size=10)
        self.bar_height = self.bar_font.metrics('linespace') + 4

        # Cache caption font metrics for the ellipsis/wrap logic.  The
        # caption font is monospace, so character count maps to pixel width.
        self._caption_char_w = max(1, self.bar_font.measure('M'))
        self._caption_line_h = max(1, self.bar_font.metrics('linespace'))

        self.show_bar = (not getattr(self.opts, 'no_bar', False)
                         or getattr(self.opts, 'bar', False))

        self.content = tk.Frame(self.root, bg=self.bg)
        self.content.pack(side=TOP, fill=BOTH, expand=True)

        # image canvas
        self.canvas = tk.Canvas(self.content, bg=self.bg,
                                highlightthickness=0, takefocus=0)

        # gallery
        self.gallery_frame = tk.Frame(self.content, bg=self.bg)
        self.gallery_canvas = tk.Canvas(self.gallery_frame, bg=self.bg,
                                        highlightthickness=0, takefocus=0)
        self.gallery_vsb = tk.Scrollbar(self.gallery_frame, orient='vertical',
                                        command=self.gallery_canvas.yview,
                                        bg=THEME['bg_secondary'], troughcolor=self.bg,
                                        borderwidth=0, highlightthickness=0)
        self.gallery_canvas.configure(yscrollcommand=self.gallery_vsb.set)
        self.gallery_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.gallery_vsb.pack(side=RIGHT, fill=Y)
        self.gallery_canvas.bind('<Configure>', self._on_gallery_configure)
        self.gallery_canvas.bind('<MouseWheel>', self._on_gallery_mousewheel)
        self.gallery_vsb.bind('<MouseWheel>', self._on_gallery_mousewheel)

        # list
        self.list_frame = tk.Frame(self.content, bg=self.bg)
        lf_left = tk.Frame(self.list_frame, bg=self.bg, width=300)
        lf_left.pack(side=LEFT, fill=Y, expand=False)
        lf_left.pack_propagate(False)

        lf_sb = tk.Scrollbar(lf_left, orient='vertical',
                             bg=THEME['bg_secondary'], troughcolor=self.bg,
                             borderwidth=0, highlightthickness=0)
        lf_sb.pack(side=RIGHT, fill=Y)

        self.listbox = Listbox(
            lf_left, selectmode=SINGLE,
            bg=THEME['bg_secondary'], fg=THEME['fg_text'],
            selectbackground=THEME['selected_bg'],
            selectforeground=THEME['selected_fg'],
            borderwidth=0, highlightthickness=0,
            font=self.bar_font, activestyle='none',
            yscrollcommand=lf_sb.set, takefocus=0)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        lf_sb.config(command=self.listbox.yview)

        lf_right = tk.Frame(self.list_frame, bg=THEME['bg_secondary'])
        lf_right.pack(side=LEFT, fill=BOTH, expand=True, padx=(8, 0))
        self.list_preview = tk.Label(lf_right, bg=THEME['bg_secondary'],
                                     fg=THEME['fg_text'], font=self.bar_font)
        self.list_preview.pack(fill=BOTH, expand=True)
        self.list_filename = tk.Label(lf_right, bg=THEME['bg_secondary'],
                                      fg=THEME['fg_bright'],
                                      font=('sans-serif', 11, 'bold'),
                                      anchor='w')
        self.list_filename.pack(side=BOTTOM, fill=X, pady=(0, 4))

        self.listbox.bind('<<ListboxSelect>>', self._on_listbox_select)

        # status + search bar
        self.status = tk.Label(self.root, text='', anchor='w',
                               bg=self.bg, fg=self.fg,
                               font=self.bar_font, padx=8, pady=2)
        if self.show_bar:
            self.status.pack(side=BOTTOM, fill=X)

        self.search_var = StringVar()
        self.search_var.trace_add('write', self._on_search_change)
        self.search_entry = Entry(
            self.root, textvariable=self.search_var,
            bg=THEME['bg_input'], fg=THEME['fg_text'],
            insertbackground=THEME['fg_text'],
            highlightthickness=1,
            highlightbackground=THEME['bg_secondary'],
            highlightcolor=THEME['accent'],
            relief='flat', font=('sans-serif', 12))
        self.search_entry.pack(side=BOTTOM, fill=X, padx=4, pady=(2, 4))

        self._show_content()

        self.root.update_idletasks()
        self.win_w = max(1, self.content.winfo_width())
        self.win_h = max(1, self.content.winfo_height())

        self.tk_img = None

    def _show_content(self):
        self.canvas.pack_forget()
        self.gallery_frame.pack_forget()
        self.list_frame.pack_forget()
        if self.mode == MODE_IMAGE:
            self.canvas.pack(fill=BOTH, expand=True, side=TOP)
        elif self.mode == MODE_GALLERY:
            self.gallery_frame.pack(fill=BOTH, expand=True, side=TOP)
        else:
            self.list_frame.pack(fill=BOTH, expand=True, side=TOP)

    # ---------------------------------------------------------- bindings
    def _mk_break(self, fn):
        def handler(event=None):
            try:
                fn()
            except Exception as e:
                if not getattr(self.opts, 'quiet', False):
                    sys.stderr.write(f"{PROGNAME}: {e}\n")
            return "break"
        return handler

    def _setup_bindings(self):
        e = self.search_entry
        e.bind('<Up>',    self._mk_break(lambda: self._key_nav(DIR_UP)))
        e.bind('<Down>',  self._mk_break(lambda: self._key_nav(DIR_DOWN)))
        e.bind('<Left>',  self._mk_break(lambda: self._key_nav(DIR_LEFT)))
        e.bind('<Right>', self._mk_break(lambda: self._key_nav(DIR_RIGHT)))
        e.bind('<Prior>', self._mk_break(lambda: self._key_page(-1)))
        e.bind('<Next>',  self._mk_break(lambda: self._key_page(1)))
        e.bind('<Home>',  self._mk_break(self.act_first))
        e.bind('<End>',   self._mk_break(self.act_last))

        e.bind('<Tab>',          self._mk_break(lambda: self._cycle_mode(1)))
        e.bind('<Shift-Tab>',    self._mk_break(lambda: self._cycle_mode(-1)))
        e.bind('<ISO_Left_Tab>', self._mk_break(lambda: self._cycle_mode(-1)))
        e.bind('<Return>',       self._mk_break(self._key_return))
        e.bind('<KP_Enter>',     self._mk_break(self._key_return))
        e.bind('<Escape>',       self._mk_break(self._key_escape))
        e.bind('<Delete>',       self._mk_break(self._key_delete))

        ctrl_bindings = {
            'q':            self.quit,
            'b':            self.act_toggle_bar,
            'd':            self.act_remove,
            'e':            lambda: self.act_fit(SCALE_WIDTH),
            'f':            self.act_toggle_fullscreen,
            'g':            self.act_first,
            'h':            lambda: self._key_nav(DIR_LEFT),
            'i':            self.act_toggle_antialias,
            'j':            lambda: self._key_nav(DIR_DOWN),
            'k':            lambda: self._key_nav(DIR_UP),
            'l':            lambda: self._key_nav(DIR_RIGHT),
            'm':            self.act_toggle_mark,
            'n':            self._key_next,
            'p':            self._key_prev,
            'r':            self.act_reload,
            's':            self.act_slideshow,
            'u':            self.act_unmark_all,
            'w':            lambda: self.act_fit(SCALE_DOWN),
            'z':            self.act_scroll_center,
            'space':        self.act_toggle_animation,
            '0':            self._key_zoom_100,
            'plus':         lambda: self.act_zoom(1),
            'equal':        lambda: self.act_zoom(1),
            'minus':        lambda: self.act_zoom(-1),
            'KP_Add':       lambda: self.act_zoom(1),
            'KP_Subtract':  lambda: self.act_zoom(-1),
            'bracketright': lambda: self.act_navigate(10),
            'bracketleft':  lambda: self.act_navigate(-10),
            'braceleft':    lambda: self.act_gamma(-1),
            'braceright':   lambda: self.act_gamma(1),
            'parenleft':    lambda: self.act_contrast(-1),
            'parenright':   lambda: self.act_contrast(1),
            'less':         lambda: self.act_rotate(DEGREE_270),
            'greater':      lambda: self.act_rotate(DEGREE_90),
            'question':     lambda: self.act_rotate(DEGREE_180),
            'bar':          lambda: self.act_flip(FLIP_HORIZONTAL),
            'underscore':   lambda: self.act_flip(FLIP_VERTICAL),
        }
        for key, fn in ctrl_bindings.items():
            e.bind(f'<Control-{key}>', self._mk_break(fn))

        # Ctrl+Enter = toggle mark (used especially in selector)
        e.bind('<Control-Return>', self._mk_break(self.act_toggle_mark))

        # Shift+Ctrl variants
        e.bind('<Control-Shift-W>', self._mk_break(lambda: self.act_fit(SCALE_FIT)))
        e.bind('<Control-Shift-F>', self._mk_break(lambda: self.act_fit(SCALE_FILL)))
        e.bind('<Control-Shift-E>', self._mk_break(lambda: self.act_fit(SCALE_HEIGHT)))
        e.bind('<Control-Shift-I>', self._mk_break(self.act_toggle_alpha))

        for b in (1, 2, 3, 4, 5):
            self.canvas.bind(f'<ButtonPress-{b}>',
                             lambda ev, btn=b: self.on_button(ev, btn))
            self.gallery_canvas.bind(f'<ButtonPress-{b}>',
                                     lambda ev, btn=b: self.on_button(ev, btn))

        self.canvas.bind('<Configure>', self.on_configure)
        self.gallery_canvas.bind('<Configure>', self.on_configure, add='+')
        self.root.protocol('WM_DELETE_WINDOW',
                           lambda: self.quit(1 if self.purpose == 'select' else 0))

        self.root.bind('<KeyPress>', self._on_root_key)
        self.search_entry.focus_set()

    def _on_root_key(self, event):
        if self.root.focus_get() is self.search_entry:
            return
        self.search_entry.focus_set()
        if event.char and len(event.char) == 1 and event.char.isprintable():
            self.search_entry.insert(END, event.char)
            self.search_entry.icursor(END)

    # ---------------------------------------------------------- filtering
    def _on_search_change(self, *args):
        self._filter_text = self.search_var.get()
        self._rebuild_visible()

        if self._visible_indices and self.fileidx not in self._visible_indices:
            self.fileidx = self._visible_indices[0]
            self._persist_index()
            if self.mode == MODE_IMAGE:
                self.load_image_async(self.fileidx)
            else:
                self._pending_gallery_scroll = self.fileidx

        if self.mode == MODE_GALLERY:
            self.render_gallery()
            self.update_info()
        elif self.mode == MODE_LIST:
            self._populate_listbox()
            self.render_list()
            self.update_info()
        elif self.mode == MODE_IMAGE:
            self.update_info()

    def _rebuild_visible(self):
        query = self._filter_text.lower().strip()
        terms = query.split() if query else []
        if not terms:
            self._visible_indices = list(range(len(self.files)))
        else:
            self._visible_indices = [
                i for i, f in enumerate(self.files)
                if all(t in f.label.lower() or t in f.path.lower() for t in terms)
            ]

    def _initial_load(self):
        if not self.files:
            return
        if self.mode == MODE_IMAGE:
            self.load_image_async(self.fileidx)
        elif self.mode == MODE_GALLERY:
            self._pending_gallery_scroll = self.fileidx
            self.redraw()
        else:
            self._populate_listbox()
            self.redraw()

    # ---------------------------------------------------------- lazy scan
    def start_lazy_scan(self, paths, recursive=False, sort_time=False):
        def worker():
            seen = set()
            for path in paths:
                if self._scan_cancel or self._quitting:
                    return
                p = Path(path).expanduser()
                try:
                    p = p.resolve()
                except Exception:
                    continue
                if not p.exists():
                    continue
                if p.is_dir():
                    pattern = "**/*" if recursive else "*"
                    try:
                        entries = list(p.glob(pattern))
                    except Exception:
                        continue
                    if sort_time:
                        try:
                            entries = sorted(
                                entries,
                                key=lambda x: x.stat().st_mtime,
                                reverse=True)
                        except OSError:
                            pass
                    else:
                        entries = sorted(entries)
                    for f in entries:
                        if self._scan_cancel or self._quitting:
                            return
                        if f.suffix.lower() in IMAGE_EXTS:
                            sp = str(f)
                            if sp in seen:
                                continue
                            seen.add(sp)
                            self._post(lambda fp=sp: self._add_lazy_file(fp))
                elif p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    sp = str(p)
                    if sp in seen:
                        continue
                    seen.add(sp)
                    self._post(lambda fp=sp: self._add_lazy_file(fp))
        threading.Thread(target=worker, daemon=True,
                         name='tkiv-scan').start()

    def _add_lazy_file(self, path):
        if self._quitting:
            return
        self.files.append(FileEntry(path))
        self.tns_thumbs.append(None)
        self._files_gen += 1
        self._rebuild_visible()

        # Invalidate the aspect cache while we are still gathering the
        # sample images (mirrors sel_img.py).
        if (self._gallery_aspect_opt is None
                and len(self.files) <= GALLERY_ASPECT_SAMPLE):
            self._gallery_aspect_cache = None

        if len(self.files) == 1:
            self.fileidx = 0
            self._persist_index()
            if self.mode == MODE_IMAGE:
                self.load_image_async(0)
            elif self.mode == MODE_GALLERY:
                self._pending_gallery_scroll = 0
                self.redraw()
            else:
                self._populate_listbox()
                self.redraw()
        else:
            if self.mode in (MODE_GALLERY, MODE_LIST):
                self.redraw()
            elif self.mode == MODE_IMAGE:
                self._prefetch_neighbors(self.fileidx)

    # ---------------------------------------------------------- main-thread queue
    def _post(self, fn):
        self._main_queue.put(fn)

    def _poll_main_queue(self):
        try:
            processed = 0
            while processed < 64:
                try:
                    fn = self._main_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:
                    pass
                processed += 1
            self.root.after(QUEUE_POLL_MS, self._poll_main_queue)
        except tk.TclError:
            pass

    # ---------------------------------------------------------- timeouts
    def set_timeout(self, name, delay_ms, callback, overwrite=False):
        if name in self._timeout_ids:
            if not overwrite:
                return
            self.root.after_cancel(self._timeout_ids[name])
        self._timeout_ids[name] = self.root.after(
            delay_ms, lambda: self._run_timeout(name, callback))

    def _run_timeout(self, name, cb):
        self._timeout_ids.pop(name, None)
        cb()

    def reset_timeout(self, name):
        if name in self._timeout_ids:
            self.root.after_cancel(self._timeout_ids[name])
            del self._timeout_ids[name]

    # ---------------------------------------------------------- files
    def remove_file(self, n, manual):
        if n < 0 or n >= len(self.files):
            return False
        if len(self.files) == 1:
            if not manual and not getattr(self.opts, 'quiet', False):
                sys.stderr.write(f"{PROGNAME}: no more files to display, aborting\n")
            self.quit(0 if manual else 1)
            return False

        del self.files[n]
        del self.tns_thumbs[n]
        if self.fileidx > n or self.fileidx >= len(self.files):
            self.fileidx -= 1
        if self.fileidx < 0:
            self.fileidx = 0
        if self.alternate > n or self.alternate >= len(self.files):
            self.alternate -= 1
        if self.alternate < 0:
            self.alternate = 0
        if self.markidx > n or self.markidx >= len(self.files):
            self.markidx -= 1
        if self.markidx < 0:
            self.markidx = 0

        self._files_gen += 1
        self._prefetch_cache.clear()
        self._img_in_flight.clear()
        self._gallery_in_flight.clear()
        self._rebuild_visible()
        self._persist_index()
        return True

    # ---------------------------------------------------------- image load
    def _set_current(self, n):
        if n == self.fileidx:
            return
        self.alternate = self.fileidx
        self.fileidx = n

    def _persist_index(self):
        """Write the current index to idx_write_path, if configured.

        The value is 1-based, matching --start-at and the status bar.
        Idempotent; failures are swallowed (debug interface).
        """
        path = getattr(self.opts, 'idx_write_path', None)
        if not path:
            return
        try:
            with open(path, 'w') as fh:
                fh.write(str(self.fileidx + 1))
        except Exception:
            pass

    def _install_image(self, n, frames, delays):
        self.img_frames = frames
        self.img_delays = delays
        self.img_sel = 0
        self.img_w, self.img_h = frames[0].size
        self.img_multi_len = sum(delays)
        self.files[n].flags &= ~FF_WARN
        self.img_x = self.img_y = 0
        try:
            self._mtimes[n] = os.path.getmtime(self.files[n].path)
        except OSError:
            pass
        if len(frames) > 1 and self.img_animate:
            self._schedule_animate()

    def load_image(self, n):
        if n < 0 or n >= len(self.files):
            return False
        self.reset_timeout('animate')
        self.reset_timeout('slideshow')
        prev = n < self.fileidx
        while True:
            cached = self._prefetch_cache.pop(n, None)
            if cached is not None:
                frames, delays = cached
                break
            path = self.files[n].path
            try:
                frames, delays = load_frames(path, max_dim=MAX_LOAD_DIM)
            except Exception as e:
                if not getattr(self.opts, 'quiet', False):
                    sys.stderr.write(f"{PROGNAME}: {self.files[n].name}: {e}\n")
                if getattr(self.opts, 'assume_files', False):
                    self.img_frames = []
                    self.img_w = self.img_h = 0
                    return False
                if not self.remove_file(n, False):
                    return False
                if n >= len(self.files):
                    n = len(self.files) - 1
                elif n > 0 and prev:
                    n -= 1
                continue
            break
        self._load_token += 1
        self._set_current(n)
        self._install_image(n, frames, delays)
        self._persist_index()
        return True

    def load_image_async(self, n):
        if n < 0 or n >= len(self.files):
            return False
        self.reset_timeout('animate')
        self.reset_timeout('slideshow')
        self._load_token += 1
        token = self._load_token
        self._set_current(n)
        self.update_info()
        cached = self._prefetch_cache.pop(n, None)
        if cached is not None:
            frames, delays = cached
            self._post(lambda: self._apply_async_result(
                token, n, frames, delays, None))
            return True

        def cb(n2, frames, delays, err):
            self._apply_async_result(token, n2, frames, delays, err)
        self._request_decode(n, cb)
        return True

    def _apply_async_result(self, token, n, frames, delays, err):
        if self._quitting:
            return
        if token != self._load_token:
            return
        if n < 0 or n >= len(self.files):
            return
        if err is not None:
            if getattr(self.opts, 'assume_files', False):
                self.img_frames = []
                self.img_w = self.img_h = 0
                self.redraw()
                return
            self.load_image(self.fileidx)
            if not self._quitting:
                self.redraw()
            return
        self._install_image(n, frames, delays)
        self._persist_index()
        self.redraw()
        self._prefetch_neighbors(n)

    def _request_decode(self, n, callback):
        fut = self._img_in_flight.get(n)
        if fut is None:
            path = self.files[n].path
            fut = self._img_executor.submit(load_frames, path, MAX_LOAD_DIM)
            self._img_in_flight[n] = fut
            def _clear(f, _n=n):
                self._img_in_flight.pop(_n, None)
            fut.add_done_callback(_clear)

        def _done(f, _n=n, _cb=callback):
            try:
                frames, delays = f.result()
                err = None
            except Exception as e:
                frames, delays, err = None, None, e
            self._post(lambda: _cb(_n, frames, delays, err))
        fut.add_done_callback(_done)

    def _prefetch_neighbors(self, n):
        if self.mode != MODE_IMAGE:
            return
        if not self._visible_indices:
            return
        try:
            pos = self._visible_indices.index(n)
        except ValueError:
            return
        for d in (1, -1):
            m_pos = pos + d
            if 0 <= m_pos < len(self._visible_indices):
                self._submit_prefetch(self._visible_indices[m_pos])

    def _submit_prefetch(self, n):
        if n in self._prefetch_cache:
            return
        if n == self.fileidx:
            return
        gen = self._files_gen

        def cb(n2, frames, delays, err):
            if err is not None:
                return
            if gen != self._files_gen:
                return
            if n2 in self._prefetch_cache:
                self._prefetch_cache.move_to_end(n2)
                return
            self._prefetch_cache[n2] = (frames, delays)
            while len(self._prefetch_cache) > PREFETCH_MAX:
                self._prefetch_cache.popitem(last=False)
        self._request_decode(n, cb)

    def _schedule_animate(self):
        if len(self.img_frames) > 1 and self.img_animate:
            delay = self.img_delays[self.img_sel]
            self.set_timeout('animate', delay, self.animate, overwrite=True)

    def animate(self):
        if len(self.img_frames) > 1 and self.img_animate:
            self.img_sel = (self.img_sel + 1) % len(self.img_frames)
            self.img_w, self.img_h = self.img_frames[self.img_sel].size
            self.redraw()
            self._schedule_animate()

    # ---------------------------------------------------------- render dispatch
    def redraw(self):
        if self._quitting:
            return
        if self.mode == MODE_IMAGE:
            self.render_image()
        elif self.mode == MODE_GALLERY:
            self.render_gallery()
        else:
            self.render_list()
        self.update_info()

    # ---------------------------------------------------------- image rendering
    @staticmethod
    def _steps_to_range(d, mx, offset):
        return offset + d * ((1.0 if d <= 0 else (mx - 1.0)) / CC_STEPS)

    def _effective_image(self):
        if not self.img_frames:
            return None
        im = self.img_frames[self.img_sel]
        if im.mode == 'RGBA':
            bg = Image.new('RGB', im.size, self.bg)
            bg.paste(im, (0, 0), im)
            im = bg
        elif im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')

        if self.brightness:
            b = self._steps_to_range(self.brightness, BRIGHTNESS_MAX, 0.0)
            im = ImageEnhance.Brightness(im).enhance(max(0.01, b))
        if self.contrast:
            c = self._steps_to_range(self.contrast, CONTRAST_MAX, 1.0)
            im = ImageEnhance.Contrast(im).enhance(max(0.01, c))
        if self.gamma:
            g = self._steps_to_range(self.gamma, GAMMA_MAX, 1.0)
            inv = 1.0 / max(0.01, g)
            lut = [min(255, int(255 * ((i / 255.0) ** inv) + 0.5))
                   for i in range(256)]
            if im.mode == 'L':
                im = im.point(lut)
            else:
                im = im.point(lut * 3)
        return im

    def _fit(self):
        if self.scalemode == SCALE_ZOOM:
            return
        if self.img_w <= 0 or self.img_h <= 0:
            return
        zw = self.win_w / self.img_w
        zh = self.win_h / self.img_h
        if   self.scalemode == SCALE_FILL:   z = max(zw, zh)
        elif self.scalemode == SCALE_WIDTH:  z = zw
        elif self.scalemode == SCALE_HEIGHT: z = zh
        else:                                z = min(zw, zh)
        if self.scalemode == SCALE_DOWN:
            z = min(z, 1.0)
        z = min(z, ZOOM_MAX)
        self.zoom = z

    def _check_pan(self):
        w = self.img_w * self.zoom
        h = self.img_h * self.zoom
        if w < self.win_w:
            self.img_x = (self.win_w - w) / 2
        elif self.img_x > 0:
            self.img_x = 0
        elif self.img_x + w < self.win_w:
            self.img_x = self.win_w - w
        if h < self.win_h:
            self.img_y = (self.win_h - h) / 2
        elif self.img_y > 0:
            self.img_y = 0
        elif self.img_y + h < self.win_h:
            self.img_y = self.win_h - h

    def render_image(self):
        if not self.img_frames:
            self.canvas.delete('all')
            self.tk_img = None
            return
        self._fit()
        self._check_pan()

        im = self._effective_image()
        if im is None:
            return
        iw, ih = im.size
        if iw == 0 or ih == 0:
            return

        z  = self.zoom
        cw, ch = self.win_w, self.win_h

        x0 = max(0.0, -self.img_x) / z
        y0 = max(0.0, -self.img_y) / z
        x1 = min(iw, (cw - self.img_x) / z)
        y1 = min(ih, (ch - self.img_y) / z)
        if x1 <= x0 or y1 <= y0:
            self.canvas.delete('all')
            self.tk_img = None
            return

        ix0, iy0 = int(x0), int(y0)
        ix1, iy1 = min(iw, int(x1 + 0.5) + 1), min(ih, int(y1 + 0.5) + 1)
        if ix1 <= ix0: ix1 = ix0 + 1
        if iy1 <= iy0: iy1 = iy0 + 1

        cropped = im.crop((ix0, iy0, ix1, iy1))
        dw = max(1, int((ix1 - ix0) * z + 0.5))
        dh = max(1, int((iy1 - iy0) * z + 0.5))

        resample = Image.BICUBIC if self.anti_alias else Image.NEAREST
        try:
            resized = cropped.resize((dw, dh), resample)
        except Exception:
            resized = cropped

        self.tk_img = ImageTk.PhotoImage(resized)
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, cw, ch))
        self.canvas.create_image(self.img_x + ix0 * z,
                                 self.img_y + iy0 * z,
                                 anchor='nw', image=self.tk_img)

    # ---------------------------------------------------------- aspect detection
    def _get_gallery_aspect(self):
        """Return the tile aspect ratio (width / height).

        When `--gallery-aspect` was supplied, use it directly.  Otherwise
        sample the first GALLERY_ASPECT_SAMPLE files and take the median
        aspect ratio, clamped to [GALLERY_ASPECT_MIN, GALLERY_ASPECT_MAX].
        Mirrors sel_img.py's behaviour.
        """
        if self._gallery_aspect_cache is not None:
            return self._gallery_aspect_cache

        a = None
        if self._gallery_aspect_opt is not None:
            a = float(self._gallery_aspect_opt)
        else:
            ratios = []
            for f in self.files[:GALLERY_ASPECT_SAMPLE]:
                sz = self._orig_sizes.get(f.path)
                if sz is None:
                    sz = _get_orig_size(f.path)
                    self._orig_sizes[f.path] = sz
                w, h = sz
                if w > 0 and h > 0:
                    ratios.append(w / h)
            if ratios:
                ratios.sort()
                a = ratios[len(ratios) // 2]

        if a is None or a <= 0:
            a = GALLERY_ASPECT_DEFAULT

        a = max(GALLERY_ASPECT_MIN, min(GALLERY_ASPECT_MAX, a))
        self._gallery_aspect_cache = a
        return a

    # ---------------------------------------------------------- gallery rendering
    def _compute_tile_metrics(self):
        """Return (tile_w, tile_h, caption_h, pad).

        Tiles are no longer forced to be square: their aspect ratio is
        derived from the gallery aspect (auto-detected or --gallery-aspect).
        """
        cw = max(self.win_w, 1)
        ch = max(self.win_h, 1)
        aspect = self._get_gallery_aspect()

        if self._gallery_tile_override is not None:
            # `--gallery-tile-size` / Ctrl+zoom specifies the long side.
            long_side = float(self._gallery_tile_override)
            if aspect >= 1.0:
                base_w = long_side
                base_h = long_side / aspect
            else:
                base_h = long_side
                base_w = long_side * aspect
        else:
            rows = self._gallery_rows_opt or GALLERY_TARGET_ROWS
            denom_v = 1.0 + GALLERY_CAPTION_RATIO + GALLERY_PAD_RATIO
            tile_h_from_rows = (ch / float(rows)) / denom_v
            tile_w_from_rows = tile_h_from_rows * aspect

            if self._gallery_cols_opt:
                denom_h = 1.0 + GALLERY_PAD_RATIO
                tile_w_from_cols = (cw / float(self._gallery_cols_opt)) / denom_h
                base_w = min(tile_w_from_rows, tile_w_from_cols)
            else:
                base_w = tile_w_from_rows
            base_h = base_w / aspect

        q = GALLERY_SIZE_QUANTUM
        tile_w = int(round(base_w / q)) * q
        tile_h = int(round(base_h / q)) * q
        tile_w = max(q, tile_w)
        tile_h = max(q, tile_h)

        long_side = max(tile_w, tile_h)
        if long_side < GALLERY_TILE_MIN:
            scale = GALLERY_TILE_MIN / float(long_side)
            tile_w = max(q, int(round(tile_w * scale / q)) * q)
            tile_h = max(q, int(round(tile_h * scale / q)) * q)
        elif long_side > GALLERY_TILE_MAX:
            scale = GALLERY_TILE_MAX / float(long_side)
            tile_w = max(q, int(round(tile_w * scale / q)) * q)
            tile_h = max(q, int(round(tile_h * scale / q)) * q)

        pad = max(GALLERY_PAD_MIN, int(round(tile_h * GALLERY_PAD_RATIO)))
        cap = max(GALLERY_CAPTION_MIN, int(round(tile_h * GALLERY_CAPTION_RATIO)))
        return tile_w, tile_h, cap, pad

    def _update_tile_metrics(self):
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

    def _compute_gallery_cols(self):
        pad = self._tile_pad
        return max(1, (self.win_w - pad) // (self._tile_w + pad))

    def _fit_caption(self, label, max_w, max_h):
        """Return a (possibly multi-line) caption string that fits within
        (max_w, max_h) pixels using the monospace caption font.

        Tk's Canvas.create_text does not clip text, so we pre-wrap and
        truncate here: over-long words are hard-broken, and if the label
        cannot fit in the available lines, the last line is ended with an
        ellipsis.  Because the caption font is monospace, character count
        maps directly to pixel width.
        """
        char_w = self._caption_char_w
        line_h = self._caption_line_h
        if char_w <= 0 or line_h <= 0 or max_w <= 1 or max_h <= 1:
            return label

        cpl = max(1, int(max_w // char_w))        # chars per line
        max_lines = max(1, int(max_h // line_h))  # lines we can draw
        ell = '…'

        if len(label) <= cpl:
            return label

        # Tokenise: split on whitespace, then hard-break over-long words.
        tokens = []
        for w in label.split():
            while len(w) > cpl:
                tokens.append(w[:cpl])
                w = w[cpl:]
            if w:
                tokens.append(w)

        lines = []
        cur = ''
        consumed = 0
        truncated = False
        for w in tokens:
            if not cur:
                cur = w
                consumed += 1
            elif len(cur) + 1 + len(w) <= cpl:
                cur = cur + ' ' + w
                consumed += 1
            else:
                lines.append(cur)
                if len(lines) >= max_lines:
                    truncated = True
                    break
                cur = w
                consumed += 1

        if not truncated:
            if cur and len(lines) < max_lines:
                lines.append(cur)
            elif cur:
                # No room for `cur` — need to truncate.
                truncated = True

        if not truncated and consumed >= len(tokens):
            return '\n'.join(lines)

        # Truncate the last retained line with an ellipsis.
        if lines:
            last = lines[-1]
            if len(last) >= cpl:
                lines[-1] = last[:cpl - 1] + ell
            else:
                lines[-1] = last + ell
        elif cur:
            lines.append(cur[:cpl - 1] + ell if len(cur) >= cpl else cur + ell)
        else:
            return ell

        return '\n'.join(lines)

    def _submit_gallery_tile(self, i):
        if i < 0 or i >= len(self.files):
            return
        if self.tns_thumbs[i] is not None:
            return
        if i in self._gallery_in_flight:
            return
        if len(self._gallery_in_flight) >= THUMB_MAX_IN_FLIGHT:
            return
        self._gallery_in_flight.add(i)
        tw, th = self._tile_thumb_max
        gen = self._files_gen
        path = self.files[i].path
        fut = self._thumb_executor.submit(load_gallery_thumb, path, tw, th)

        def _done(f, _i=i, _gen=gen):
            try:
                pil = f.result()
            except Exception:
                pil = None
            self._post(lambda: self._on_gallery_tile_ready(_i, _gen, pil))
        fut.add_done_callback(_done)

    def _on_gallery_tile_ready(self, i, gen, pil):
        if self._quitting:
            return
        self._gallery_in_flight.discard(i)
        if gen != self._files_gen:
            return
        if i < 0 or i >= len(self.files) or pil is None:
            return
        if self.tns_thumbs[i] is not None:
            return
        try:
            ph = ImageTk.PhotoImage(pil)
        except tk.TclError:
            return
        self.tns_thumbs[i] = (ph, pil.size[0], pil.size[1])
        if self.mode == MODE_GALLERY:
            self._schedule_gallery_redraw()

    def _schedule_gallery_redraw(self):
        """Coalesce many thumbnail-ready events into one redraw.
        Runs as an idle task, so Tk processes buffered key events first."""
        if self._gallery_redraw_pending:
            return
        self._gallery_redraw_pending = True
        self.root.after_idle(self._do_gallery_redraw)

    def _do_gallery_redraw(self):
        self._gallery_redraw_pending = False
        if self._quitting or self.mode != MODE_GALLERY:
            return
        self.render_gallery()
        self.update_info()

    def _apply_gallery_scroll(self, index):
        if index < 0 or index >= len(self.files):
            return
        try:
            pos = self._visible_indices.index(index)
        except ValueError:
            return
        cols = max(self._gallery_cols, 1)
        row = pos // cols
        row_h = self._tile_h + self._tile_caption_h + self._tile_pad
        row_top = row * row_h
        row_bottom = row_top + row_h

        vh = max(self.gallery_canvas.winfo_height(), 1)
        y_top = self.gallery_canvas.canvasy(0)
        y_bot = y_top + vh

        if row_top < y_top:
            new_top = row_top
        elif row_bottom > y_bot:
            new_top = row_bottom - vh
        else:
            return
        sr = self.gallery_canvas.cget('scrollregion')
        try:
            _, _, _, total_h = map(float, sr.split())
        except Exception:
            total_h = max(new_top + vh, 1)
        if total_h <= 0:
            return
        self.gallery_canvas.yview_moveto(
            max(0.0, min(1.0, new_top / total_h)))

    def render_gallery(self):
        if not self._visible_indices:
            self.gallery_canvas.delete('all')
            self.gallery_canvas.configure(
                scrollregion=(0, 0, self.win_w, self.win_h))
            self.gallery_canvas.create_text(
                self.win_w // 2, self.win_h // 2,
                text="No matches", fill=THEME['fg_text'],
                font=self.bar_font)
            return

        self._update_tile_metrics()
        cols = self._compute_gallery_cols()
        self._gallery_cols = cols

        row_h = self._tile_h + self._tile_caption_h + self._tile_pad
        col_w = self._tile_w + self._tile_pad
        n = len(self._visible_indices)
        total_rows = (n + cols - 1) // cols
        total_h = max(total_rows * row_h + self._tile_pad, self.win_h)
        total_w = max(cols * col_w + self._tile_pad, self.win_w)

        self.gallery_canvas.delete('all')
        self.gallery_canvas.configure(scrollregion=(0, 0, total_w, total_h))

        if self._pending_gallery_scroll is not None:
            self._apply_gallery_scroll(self._pending_gallery_scroll)
            self._pending_gallery_scroll = None

        vh = max(self.gallery_canvas.winfo_height(), 1)
        y_top = self.gallery_canvas.canvasy(0)
        y_bot = y_top + vh
        first_row = max(0, int(y_top // row_h) - GALLERY_OVERSCAN_ROWS)
        last_row = min(total_rows - 1,
                       int(y_bot // row_h) + GALLERY_OVERSCAN_ROWS)
        first_pos = first_row * cols
        last_pos = min(n, (last_row + 1) * cols)

        self._gallery_photos = []

        for pos in range(first_pos, last_pos):
            abs_i = self._visible_indices[pos]
            r = pos // cols
            c = pos % cols
            x = c * col_w + self._tile_pad // 2
            y = r * row_h + self._tile_pad // 2

            if abs_i == self.fileidx:
                border_color = THEME['accent']
                bw = 3
            else:
                border_color = THEME['hover_border']
                bw = 2

            self.gallery_canvas.create_rectangle(
                x - bw, y - bw,
                x + self._tile_w + bw,
                y + self._tile_h + self._tile_caption_h + bw,
                outline=border_color, width=bw)

            entry = self.tns_thumbs[abs_i]
            if entry is not None:
                ph, tw, th = entry
                px = x + (self._tile_w - tw) // 2
                py = y + (self._tile_h - th) // 2
                self.gallery_canvas.create_image(px, py, anchor='nw', image=ph)
                self._gallery_photos.append(ph)
            else:
                self._submit_gallery_tile(abs_i)

            if self.files[abs_i].flags & FF_MARK:
                self.gallery_canvas.create_rectangle(
                    x + self._tile_w - 12, y + self._tile_h - 12,
                    x + self._tile_w - 2,  y + self._tile_h - 2,
                    fill=self.mark_fg, outline=self.mark_fg)

            # Caption: pre-truncate/wrap so it never overflows the tile.
            caption = self._fit_caption(
                self.files[abs_i].label,
                max(20, self._tile_w - 4),
                max(1, self._tile_caption_h - 2))
            self.gallery_canvas.create_text(
                x + self._tile_w // 2,
                y + self._tile_h + self._tile_caption_h // 2,
                text=caption, fill=self.caption_fg,
                anchor='center')

    def _gallery_hit(self, event_x, event_y):
        cx = self.gallery_canvas.canvasx(event_x)
        cy = self.gallery_canvas.canvasy(event_y)
        cols = max(self._gallery_cols, 1)
        row_h = self._tile_h + self._tile_caption_h + self._tile_pad
        col_w = self._tile_w + self._tile_pad
        if cx < 0 or cy < 0:
            return None
        col = int(cx // col_w)
        row = int(cy // row_h)
        if col < 0 or col >= cols:
            return None
        pos = row * cols + col
        if 0 <= pos < len(self._visible_indices):
            return self._visible_indices[pos]
        return None

    def _gallery_scroll_by(self, dy):
        sr = self.gallery_canvas.cget('scrollregion')
        try:
            _, _, _, total_h = map(float, sr.split())
        except Exception:
            return
        if total_h <= 0:
            return
        vh = max(self.gallery_canvas.winfo_height(), 1)
        max_top = max(0, total_h - vh)
        y_top = self.gallery_canvas.canvasy(0)
        new_top = max(0, min(max_top, y_top + dy))
        self.gallery_canvas.yview_moveto(new_top / total_h)
        self.render_gallery()

    def _gallery_zoom(self, d):
        step = GALLERY_ZOOM_STEP * d
        base = (self._gallery_tile_override
                if self._gallery_tile_override is not None
                else max(self._tile_w, self._tile_h))
        new_size = base + step
        new_size = max(GALLERY_TILE_MIN, min(GALLERY_TILE_MAX, new_size))
        if new_size == self._gallery_tile_override:
            return
        self._gallery_tile_override = new_size
        self.tns_thumbs = [None] * len(self.files)
        self._gallery_in_flight.clear()
        self._pending_gallery_scroll = self.fileidx
        self.redraw()

    def _on_gallery_configure(self, event=None):
        self._refresh_size()

    def _on_gallery_mousewheel(self, event=None):
        if self.mode != MODE_GALLERY or event is None:
            return
        self._gallery_scroll_by(int(-1 * (event.delta / 120)) *
                                max(self._tile_h // 2, 30))

    # ---------------------------------------------------------- list rendering
    def _populate_listbox(self):
        self.listbox.delete(0, END)
        for i in self._visible_indices:
            self.listbox.insert(END, self.files[i].label)
        for pos, i in enumerate(self._visible_indices):
            if self.files[i].flags & FF_MARK:
                self.listbox.itemconfig(pos, bg=THEME['selected_bg'],
                                        fg=THEME['selected_fg'])
            else:
                self.listbox.itemconfig(pos, bg=THEME['bg_secondary'],
                                        fg=THEME['fg_text'])
        if self._visible_indices:
            if self.fileidx in self._visible_indices:
                pos = self._visible_indices.index(self.fileidx)
            else:
                pos = 0
            self.listbox.selection_clear(0, END)
            self.listbox.select_set(pos)
            self.listbox.see(pos)

    def _on_listbox_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        pos = sel[0]
        if 0 <= pos < len(self._visible_indices):
            new_idx = self._visible_indices[pos]
            if new_idx != self.fileidx:
                self.fileidx = new_idx
                self._persist_index()
                try:
                    self._mtimes[new_idx] = os.path.getmtime(
                        self.files[new_idx].path)
                except OSError:
                    pass
                self.render_list()
                self.update_info()

    def render_list(self):
        if not self._visible_indices:
            self.list_preview.config(image='', text='No matches')
            self.list_preview.image = None
            self.list_filename.config(text='')
            return

        if self.fileidx not in self._visible_indices:
            self.fileidx = self._visible_indices[0]
            self._persist_index()
        pos = self._visible_indices.index(self.fileidx)
        self.listbox.selection_clear(0, END)
        self.listbox.select_set(pos)
        self.listbox.see(pos)

        name = self.files[self.fileidx].label
        self.list_filename.config(text=name)
        self.list_preview.config(image='', text=f'Loading {name}…')

        target = self.fileidx
        self._list_pending = target

        self.root.update_idletasks()
        pw = max(self.list_preview.winfo_width(), 64)
        ph = max(self.list_preview.winfo_height(), 64)

        def _done(f, _i=target):
            try:
                frames, _delays = f.result()
            except Exception:
                frames = None
            self._post(lambda: self._apply_list_preview(_i, frames))

        fut = self._img_executor.submit(load_frames,
                                        self.files[target].path,
                                        max(pw, ph))
        fut.add_done_callback(_done)

    def _apply_list_preview(self, idx, frames):
        if self._quitting or self.mode != MODE_LIST:
            return
        if idx != self._list_pending:
            return
        if not frames:
            self.list_preview.config(image='', text='Failed to load')
            return
        im = frames[0].copy()
        pw = max(self.list_preview.winfo_width(), 64)
        ph = max(self.list_preview.winfo_height(), 64)
        im.thumbnail((pw, ph), Image.LANCZOS)
        self._list_photo = ImageTk.PhotoImage(im)
        self.list_preview.config(image=self._list_photo, text='')

    # ---------------------------------------------------------- update info
    def update_info(self):
        if not self.show_bar:
            return
        cnt_all = len(self.files)
        if cnt_all == 0:
            self.status.config(text='')
            return
        cnt_vis = len(self._visible_indices)
        fw = len(str(cnt_all))
        mark = '* ' if (self.files[self.fileidx].flags & FF_MARK) else ''
        name = self.files[self.fileidx].label

        vis_pos = 0
        if self.fileidx in self._visible_indices:
            vis_pos = self._visible_indices.index(self.fileidx) + 1

        if self.mode == MODE_GALLERY or self.mode == MODE_LIST:
            if self._filter_text:
                text = (f"{mark}{vis_pos:0{fw}d}/{cnt_vis} "
                        f"({cnt_all})  {name}")
            else:
                text = f"{mark}{self.fileidx + 1:0{fw}d}/{cnt_all}  {name}"
        else:
            parts = []
            if self.ss_on:
                d = self.ss_delay / 10
                parts.append(f"{int(d)}s" if d == int(d) else f"{d:.1f}s")
            if self.gamma:      parts.append(f"G{self.gamma:+d}")
            if self.brightness: parts.append(f"B{self.brightness:+d}")
            if self.contrast:   parts.append(f"C{self.contrast:+d}")
            parts.append(f"{int(self.zoom * 100)}%")
            if len(self.img_frames) > 1:
                parts.append(f"{self.img_sel + 1}/{len(self.img_frames)}")
            if self._filter_text:
                parts.append(f"{vis_pos}/{cnt_vis} ({cnt_all})")
            else:
                parts.append(f"{self.fileidx + 1:0{fw}d}/{cnt_all}")
            text = f"{mark}{'  '.join(parts)}  {name}"
        self.status.config(text=text)

    # ---------------------------------------------------------- quit / output
    def _collect_selection(self):
        marked = [f for f in self.files if f.flags & FF_MARK]
        if not marked and 0 <= self.fileidx < len(self.files):
            marked = [self.files[self.fileidx]]
        return marked

    def _emit_selector_output(self):
        marked = self._collect_selection()
        if not marked:
            return
        return_label = getattr(self.opts, 'return_label', False)
        out = []
        for f in marked:
            out.append(f.label if return_label else f.path)
        sep = '\0' if getattr(self.opts, 'using_null', False) else '\n'
        for line in out:
            sys.stdout.write(line + sep)
        sys.stdout.flush()

    def _emit_viewer_output(self):
        if not getattr(self.opts, 'stdout', False):
            return
        sep = '\0' if getattr(self.opts, 'using_null', False) else '\n'
        marked = [f for f in self.files if f.flags & FF_MARK]
        if not marked and 0 <= self.fileidx < len(self.files):
            marked = [self.files[self.fileidx]]
        for f in marked:
            sys.stdout.write(f.name + sep)
        sys.stdout.flush()

    def quit(self, status=0):
        if self._quitting:
            return
        self._quitting = True
        self._scan_cancel = True
        try:
            if self.purpose == 'select':
                if status == 0:
                    self._emit_selector_output()
            else:
                if status == 0:
                    self._emit_viewer_output()
        except Exception:
            pass
        for exc in (self._img_executor, self._thumb_executor):
            try:
                exc.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                try:
                    exc.shutdown(wait=False)
                except Exception:
                    pass
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            sys.exit(status)
        except SystemExit:
            raise

    # ---------------------------------------------------------- navigation
    def _navigate(self, n):
        if n < 0 or n >= len(self.files):
            return False
        if n == self.fileidx and self.mode != MODE_IMAGE:
            return False
        if self.mode == MODE_IMAGE:
            self.load_image_async(n)
        else:
            self._set_current(n)
            self._pending_gallery_scroll = n
            self._persist_index()
            self.redraw()
        return True

    def _nav_visible(self, delta):
        if not self._visible_indices:
            return
        try:
            pos = self._visible_indices.index(self.fileidx)
        except ValueError:
            pos = 0 if delta >= 0 else len(self._visible_indices) - 1
            self._navigate(self._visible_indices[pos])
            return
        new_pos = pos + delta
        if 0 <= new_pos < len(self._visible_indices):
            self._navigate(self._visible_indices[new_pos])

    def _key_next(self):
        self._nav_visible(1)

    def _key_prev(self):
        self._nav_visible(-1)

    def _key_nav(self, direction):
        if self.mode == MODE_IMAGE:
            if direction == DIR_LEFT:  self.act_scroll(DIR_LEFT)
            elif direction == DIR_RIGHT: self.act_scroll(DIR_RIGHT)
            elif direction == DIR_UP:  self.act_scroll(DIR_UP)
            elif direction == DIR_DOWN: self.act_scroll(DIR_DOWN)
        elif self.mode == MODE_LIST:
            if direction == DIR_UP:
                self._nav_visible(-1)
            elif direction == DIR_DOWN:
                self._nav_visible(1)
        else:
            cols = max(self._gallery_cols, 1)
            if direction == DIR_UP:
                self._nav_visible(-cols)
            elif direction == DIR_DOWN:
                self._nav_visible(cols)
            elif direction == DIR_LEFT:
                self._nav_visible(-1)
            elif direction == DIR_RIGHT:
                self._nav_visible(1)

    def _key_page(self, direction):
        if self.mode == MODE_IMAGE:
            self.act_navigate(direction * 10)
        elif self.mode == MODE_LIST:
            self._nav_visible(direction * 20)
        else:
            rows = max(1, self.win_h // (self._tile_h + self._tile_caption_h
                                         + self._tile_pad))
            self._nav_visible(direction * rows * max(self._gallery_cols, 1))

    def _key_return(self):
        if self.purpose == 'select':
            self.quit(0)
            return
        if self.mode == MODE_LIST:
            self._enter_image_mode()
        elif self.mode == MODE_GALLERY:
            self._enter_image_mode()
        else:
            self._enter_gallery_mode()

    def _key_escape(self):
        if self._filter_text:
            self.search_var.set("")
        else:
            self.quit(1 if self.purpose == 'select' else 0)

    def _key_delete(self):
        self.act_remove()

    def _key_zoom_100(self):
        self.scalemode = SCALE_ZOOM
        self._zoom_to(1.0)
        self.redraw()

    def _cycle_mode(self, direction):
        order = [MODE_IMAGE, MODE_GALLERY, MODE_LIST]
        try:
            idx = order.index(self.mode)
        except ValueError:
            idx = 0
        idx = (idx + direction) % len(order)
        target = order[idx]
        if target == MODE_IMAGE:
            self._enter_image_mode()
        elif target == MODE_GALLERY:
            self._enter_gallery_mode()
        else:
            self._enter_list_mode()

    def _enter_image_mode(self):
        was = self.mode
        self.mode = MODE_IMAGE
        self.reset_timeout('animate')
        self.reset_timeout('slideshow')
        if was != MODE_IMAGE:
            self._show_content()
            if self.files:
                self.load_image_async(self.fileidx)
        self.search_entry.focus_set()

    def _enter_gallery_mode(self):
        was = self.mode
        self.mode = MODE_GALLERY
        self.reset_timeout('animate')
        self.ss_on = False
        self.reset_timeout('slideshow')
        self._pending_gallery_scroll = self.fileidx
        if was != MODE_GALLERY:
            self._show_content()
            self.root.update_idletasks()
            self.win_w = max(1, self.content.winfo_width())
            self.win_h = max(1, self.content.winfo_height())
        self.redraw()
        self.search_entry.focus_set()

    def _enter_list_mode(self):
        was = self.mode
        self.mode = MODE_LIST
        self.reset_timeout('animate')
        self.ss_on = False
        self.reset_timeout('slideshow')
        if was != MODE_LIST:
            self._show_content()
            self.root.update_idletasks()
            self.win_w = max(1, self.content.winfo_width())
            self.win_h = max(1, self.content.winfo_height())
        self._populate_listbox()
        self.redraw()
        self.search_entry.focus_set()

    # ---------------------------------------------------------- actions
    def act_first(self):
        if self._visible_indices:
            self._navigate(self._visible_indices[0])

    def act_last(self):
        if self._visible_indices:
            self._navigate(self._visible_indices[-1])

    def act_toggle_fullscreen(self):
        cur = bool(self.root.attributes('-fullscreen'))
        self.root.attributes('-fullscreen', not cur)
        self.root.after(100, self._refresh_size)

    def act_toggle_bar(self):
        self.show_bar = not self.show_bar
        if self.show_bar:
            self.status.pack(side=BOTTOM, fill=X,
                             before=self.search_entry)
        else:
            self.status.pack_forget()
        self.root.after(50, self._refresh_size)

    def _refresh_size(self):
        if self._quitting:
            return
        self.root.update_idletasks()
        self.win_w = max(1, self.content.winfo_width())
        self.win_h = max(1, self.content.winfo_height())
        if self.mode == MODE_GALLERY:
            self._pending_gallery_scroll = self.fileidx
        self.redraw()

    def act_reload(self):
        if not self.files:
            return
        if self.mode == MODE_IMAGE:
            self._prefetch_cache.pop(self.fileidx, None)
            self.load_image_async(self.fileidx)
        else:
            self.tns_thumbs[self.fileidx] = None
            self.redraw()

    def act_remove(self):
        if not self.files:
            return
        if self.remove_file(self.fileidx, True):
            if self.mode == MODE_IMAGE:
                self.load_image_async(self.fileidx)
            else:
                self._pending_gallery_scroll = self.fileidx
                if self.mode == MODE_LIST:
                    self._populate_listbox()
                self.redraw()

    def _mark(self, n, on):
        if 0 <= n < len(self.files):
            old = bool(self.files[n].flags & FF_MARK)
            if old != on:
                if on: self.files[n].flags |= FF_MARK
                else:  self.files[n].flags &= ~FF_MARK
                return True
        return False

    def act_toggle_mark(self):
        if not self.files:
            return
        self._mark(self.fileidx, not (self.files[self.fileidx].flags & FF_MARK))
        self.markidx = self.fileidx
        if self.mode == MODE_LIST:
            self._populate_listbox()
        self.redraw()

    def act_unmark_all(self):
        for f in self.files:
            f.flags &= ~FF_MARK
        if self.mode == MODE_LIST:
            self._populate_listbox()
        self.redraw()

    def act_gamma(self, d):
        newv = max(-CC_STEPS, min(CC_STEPS, self.gamma + d))
        if newv != self.gamma:
            self.gamma = newv
            self.redraw()

    def act_brightness(self, d):
        newv = max(-CC_STEPS, min(CC_STEPS, self.brightness + d))
        if newv != self.brightness:
            self.brightness = newv
            self.redraw()

    def act_contrast(self, d):
        newv = max(-CC_STEPS, min(CC_STEPS, self.contrast + d))
        if newv != self.contrast:
            self.contrast = newv
            self.redraw()

    def _zoom_to(self, z):
        if ZOOM_MIN <= z <= ZOOM_MAX and self.zoom > 0:
            cx, cy = self.win_w / 2, self.win_h / 2
            self.img_x = cx - (cx - self.img_x) * z / self.zoom
            self.img_y = cy - (cy - self.img_y) * z / self.zoom
            self.zoom = z
            self.scalemode = SCALE_ZOOM

    def act_zoom(self, d):
        if self.mode == MODE_GALLERY:
            self._gallery_zoom(d)
            return
        if self.mode == MODE_LIST:
            return
        if d > 0:
            for z in ZOOM_LEVELS:
                if z > self.zoom + 1e-9:
                    self._zoom_to(z); break
        else:
            for z in reversed(ZOOM_LEVELS):
                if z < self.zoom - 1e-9:
                    self._zoom_to(z); break
        self.redraw()

    def _pan(self, dx, dy):
        self.img_x += dx
        self.img_y += dy
        self._check_pan()

    def act_scroll(self, direction, screen=False):
        if self.mode != MODE_IMAGE:
            return
        if screen:
            x = self.win_w
            y = self.win_h
        else:
            x = self.win_w / 5
            y = self.win_h / 5
        dx = dy = 0
        if   direction == DIR_LEFT:  dx =  x
        elif direction == DIR_RIGHT: dx = -x
        elif direction == DIR_UP:    dy =  y
        elif direction == DIR_DOWN:  dy = -y
        self._pan(dx, dy)
        self.redraw()

    def act_scroll_center(self):
        if self.mode != MODE_IMAGE:
            return
        self.img_x = (self.win_w - self.img_w * self.zoom) / 2
        self.img_y = (self.win_h - self.img_h * self.zoom) / 2
        self._check_pan()
        self.redraw()

    def act_fit(self, mode):
        self.scalemode = mode
        if self.mode == MODE_IMAGE:
            self.redraw()

    def act_rotate(self, degree):
        if self.mode != MODE_IMAGE or not self.img_frames:
            return
        self.img_frames = [f.rotate(90 * degree, expand=True)
                           for f in self.img_frames]
        self.img_w, self.img_h = self.img_frames[0].size
        self._check_pan()
        self.redraw()

    def act_flip(self, direction):
        if self.mode != MODE_IMAGE or not self.img_frames:
            return
        if direction == FLIP_HORIZONTAL:
            self.img_frames = [f.transpose(Image.FLIP_LEFT_RIGHT)
                               for f in self.img_frames]
        else:
            self.img_frames = [f.transpose(Image.FLIP_TOP_BOTTOM)
                               for f in self.img_frames]
        self.redraw()

    def act_toggle_antialias(self):
        self.anti_alias = not self.anti_alias
        self.redraw()

    def act_toggle_alpha(self):
        self.alpha_layer = not self.alpha_layer
        self.redraw()

    def act_slideshow(self):
        if self.ss_on:
            self.ss_on = False
            self.reset_timeout('slideshow')
        else:
            self.ss_on = True
            self._schedule_slideshow()
        self.redraw()

    def _schedule_slideshow(self):
        if self.ss_on:
            delay = self.ss_delay * 100
            if len(self.img_frames) > 1 and self.img_animate:
                delay = max(delay, self.img_multi_len)
            self.set_timeout('slideshow', delay, self.slideshow_next,
                             overwrite=False)

    def slideshow_next(self):
        if not self._visible_indices:
            return
        try:
            pos = self._visible_indices.index(self.fileidx)
        except ValueError:
            pos = -1
        new_pos = (pos + 1) % len(self._visible_indices)
        self.load_image(self._visible_indices[new_pos])
        self.redraw()
        self._schedule_slideshow()

    def act_toggle_animation(self):
        if len(self.img_frames) > 1:
            self.img_animate = not self.img_animate
            if self.img_animate:
                self.animate()
            else:
                self.reset_timeout('animate')

    def act_navigate(self, d):
        if self.mode != MODE_IMAGE:
            return
        self._nav_visible(d)

    # ---------------------------------------------------------- mouse
    def on_button(self, event, button):
        if self.mode == MODE_IMAGE:
            if button == 1:
                nw = self.win_w // 3
                if event.x < nw:
                    self.act_navigate(-1)
                elif event.x > self.win_w - nw:
                    self.act_navigate(1)
            elif button == 3:
                self._enter_gallery_mode()
            elif button == 4:
                self.act_zoom(1)
            elif button == 5:
                self.act_zoom(-1)
        elif self.mode == MODE_GALLERY:
            if button == 1:
                n = self._gallery_hit(event.x, event.y)
                if n is not None:
                    if self.purpose == 'select':
                        # Single-click selects in gallery; use Ctrl-click to toggle mark
                        ctrl = bool(event.state & 0x0004)
                        if ctrl:
                            self._mark(n, not (self.files[n].flags & FF_MARK))
                            self.redraw()
                        else:
                            self.fileidx = n
                            self._pending_gallery_scroll = n
                            self._persist_index()
                            self.redraw()
                    else:
                        self.fileidx = n
                        self._pending_gallery_scroll = n
                        self._persist_index()
                        self.redraw()
            elif button == 3:
                n = self._gallery_hit(event.x, event.y)
                if n is not None:
                    self._mark(n, not (self.files[n].flags & FF_MARK))
                    self.redraw()
            elif button == 4:
                self._gallery_scroll_by(-max(self._tile_h // 2, 30))
            elif button == 5:
                self._gallery_scroll_by(max(self._tile_h // 2, 30))
        else:
            if button == 1:
                sel = self.listbox.nearest(event.y)
                if sel >= 0:
                    self.listbox.selection_clear(0, END)
                    self.listbox.select_set(sel)
                    self._on_listbox_select()
            elif button == 3:
                sel = self.listbox.nearest(event.y)
                if 0 <= sel < len(self._visible_indices):
                    idx = self._visible_indices[sel]
                    self._mark(idx, not (self.files[idx].flags & FF_MARK))
                    self._populate_listbox()
                    self.redraw()

    def on_configure(self, event):
        self.win_w = max(1, event.width)
        self.win_h = max(1, event.height)
        if not self._resize_pending:
            self._resize_pending = True
            self.root.after(75, self._do_resize)

    def _do_resize(self):
        self._resize_pending = False
        if self._quitting:
            return
        self.root.update_idletasks()
        self.win_w = max(1, self.content.winfo_width())
        self.win_h = max(1, self.content.winfo_height())
        if self.mode == MODE_GALLERY:
            self._pending_gallery_scroll = self.fileidx
        self.redraw()

    def _poll_autoreload(self):
        try:
            if (self.mode == MODE_IMAGE and self.img_frames
                    and 0 <= self.fileidx < len(self.files)):
                path = self.files[self.fileidx].path
                try:
                    mt = os.path.getmtime(path)
                except OSError:
                    mt = None
                old = self._mtimes.get(self.fileidx)
                if old is not None and mt is not None and mt != old:
                    self._mtimes[self.fileidx] = mt
                    self._prefetch_cache.pop(self.fileidx, None)
                    self.load_image_async(self.fileidx)
            self.root.after(500, self._poll_autoreload)
        except tk.TclError:
            pass


# ============================================================ entry points
def run_viewer():
    parser = build_viewer_parser()
    args = parser.parse_args()

    if args.help:
        print(f"{PROGNAME} img {VERSION}")
        print(parser.format_usage().rstrip())
        print("\nKey bindings (search bar is always focused; actions use Ctrl+):")
        print("  Tab / Shift+Tab  cycle mode (image -> gallery -> list)")
        print("  Return           switch image <-> gallery (or list -> image)")
        print("  Esc              clear filter, or quit if empty")
        print("  Ctrl+Q           quit")
        print("  Ctrl+F           fullscreen")
        print("  Ctrl+B           toggle bar")
        print("  Ctrl+R           reload")
        print("  Ctrl+D           remove file")
        print("  Ctrl+N / Ctrl+P  next / previous (respects filter)")
        print("  Ctrl+H/J/K/L     pan")
        print("  Ctrl++ / Ctrl+-  zoom (image) / tile size (gallery)")
        print("  Ctrl+0           100% zoom")
        print("  Ctrl+M           mark    Ctrl+U  unmark all")
        print("  Ctrl+S           slideshow")
        print("  Ctrl+Space       toggle animation")
        print("  Ctrl+E           fit width   Ctrl+W  fit-down")
        print("  Ctrl+Shift+W     fit         Ctrl+Shift+F  fill")
        print("\nOptions:")
        print("  -g/-t, --gallery            start in gallery mode")
        print("  -T N,  --gallery-tile-size  gallery tile size in pixels")
        print("  --gallery-rows N            target rows visible")
        print("  --gallery-cols N            target cols visible")
        print("  --gallery-aspect N          tile width/height ratio "
              "(default: auto-detect)")
        print("  --lazy                      populate file list as it is scanned")
        return 0

    if args.version:
        print(f"{PROGNAME} img {VERSION}")
        return 0

    if args.name is None and args.legacy_name:
        args.name = args.legacy_name

    if args.class_:
        sys.stderr.write("tkiv img: --class is deprecated, use --name instead\n")
        if not args.name:
            args.name = args.class_

    if not HAVE_VIPS and not args.quiet:
        sys.stderr.write(f"{PROGNAME}: warning: pyvips not available; "
                         "falling back to Pillow for image decoding. "
                         "Install with: pip install pyvips\n")

    file_list = []
    scan_paths = []
    if args.from_stdin or (len(args.files) == 1 and args.files[0] == '-'):
        sep = '\0' if args.using_null else '\n'
        data = sys.stdin.read()
        for e in data.split(sep):
            if e:
                file_list.append(e)
    else:
        if args.lazy:
            # expand directories later, lazily
            for f in args.files:
                if os.path.isdir(f):
                    scan_paths.append(f)
                else:
                    file_list.append(f)
            if scan_paths:
                # keep non-existent single paths? skip
                pass
        else:
            for f in args.files:
                if not os.path.exists(f):
                    if not args.quiet:
                        sys.stderr.write(
                            f"{PROGNAME}: {f}: No such file or directory\n")
                    continue
                if os.path.isdir(f):
                    file_list.extend(
                        collect_dir(f, args.recursive, args.hidden, args.time))
                else:
                    file_list.append(f)

    if not file_list and not scan_paths:
        sys.stderr.write(f"{PROGNAME}: No valid image file given, aborting\n")
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.stderr.write(f"{PROGNAME}: cannot open display: {e}\n")
        return 1

    entries = [FileEntry(p) for p in file_list]
    app = TkivApp(root, args, entries, purpose='view',enable_floating_window=args.floating_window)
    if args.lazy and scan_paths:
        app.start_lazy_scan(scan_paths, recursive=args.recursive,
                            sort_time=args.time)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


def run_selector():
    parser = build_selector_parser()
    args = parser.parse_args()

    if args.help:
        print(f"{PROGNAME} select {VERSION}")
        print(parser.format_usage().rstrip())
        print("\nKey bindings match the viewer. Press Return to accept and print,")
        print("Esc to cancel. Ctrl+M (or Ctrl+Enter) toggles a mark; when any")
        print("file is marked, all marked files are printed on accept.")
        return 0

    if args.version:
        print(f"{PROGNAME} select {VERSION}")
        return 0

    if not HAVE_VIPS and not args.quiet:
        sys.stderr.write(f"{PROGNAME}: warning: pyvips not available; "
                         "falling back to Pillow for image decoding.\n")

    # --- Build entries list -------------------------------------------------
    entries = []
    scan_paths = []

    if args.dmenu_mode:
        if args.list_file and args.list_entries:
            sys.stderr.write("Error: both --list-file and --list-entries provided.\n")
            sys.exit(1)
        if args.list_file:
            try:
                with open(args.list_file, 'r') as f:
                    list_entries = [line.rstrip('\n') for line in f]
            except Exception as e:
                sys.stderr.write(f"Error reading list file: {e}\n")
                sys.exit(1)
        elif args.list_entries:
            list_entries = args.list_entries.split('\n')
        else:
            sys.stderr.write("Error: must provide either --list-file or "
                             "--list-entries\n")
            sys.exit(1)

        if args.image_file and args.image_entries:
            sys.stderr.write("Error: both --image-file and --image-entries provided.\n")
            sys.exit(1)
        if args.image_file:
            try:
                with open(args.image_file, 'r') as f:
                    image_entries = [line.rstrip('\n') for line in f]
            except Exception as e:
                sys.stderr.write(f"Error reading image file: {e}\n")
                sys.exit(1)
        elif args.image_entries:
            image_entries = args.image_entries.split('\n')
        else:
            sys.stderr.write("Error: must provide either --image-file or "
                             "--image-entries\n")
            sys.exit(1)

        if len(list_entries) != len(image_entries):
            sys.stderr.write(
                f"Error: number of list entries ({len(list_entries)}) and "
                f"image entries ({len(image_entries)}) do not match\n")
            sys.exit(1)

        entries = [FileEntry(path, label)
                   for label, path in zip(list_entries, image_entries)]
        # dmenu entries may point at arbitrary paths — don't try to remove them
        args.assume_files = True
    else:
        paths = args.paths or ['.']
        if args.lazy:
            for f in paths:
                if os.path.isdir(f):
                    scan_paths.append(f)
                elif os.path.isfile(f) and file_is_image(f):
                    entries.append(FileEntry(f))
            if not entries and not scan_paths:
                sys.stderr.write("No images found.\n")
                sys.exit(1)
        else:
            file_list = []
            for f in paths:
                if not os.path.exists(f):
                    if not args.quiet:
                        sys.stderr.write(f"{PROGNAME}: {f}: No such file or directory\n")
                    continue
                if os.path.isdir(f):
                    file_list.extend(
                        collect_dir(f, args.recursive, args.hidden, args.time))
                elif os.path.isfile(f) and file_is_image(f):
                    file_list.append(f)
            if not file_list:
                sys.stderr.write("No images found.\n")
                sys.exit(1)
            entries = [FileEntry(p) for p in file_list]

    if not entries and not scan_paths:
        sys.stderr.write("No images found.\n")
        sys.exit(1)

    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.stderr.write(f"{PROGNAME}: cannot open display: {e}\n")
        sys.exit(1)

    app = TkivApp(root, args, entries, purpose='select')
    if args.lazy and scan_paths:
        app.start_lazy_scan(scan_paths, recursive=args.recursive,
                            sort_time=args.time)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


# ============================================================ dispatcher
def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        sys.stderr.write(
            f"usage: {os.path.basename(sys.argv[0])} {{img|select}} [OPTIONS] ...\n"
            "\n"
            f"  {os.path.basename(sys.argv[0])} img    [OPTIONS] FILES...   image viewer\n"
            f"  {os.path.basename(sys.argv[0])} select [OPTIONS] PATHS...   image selector / dmenu\n")
        return 0 if len(sys.argv) >= 2 else 1

    mode = sys.argv[1]
    rest = sys.argv[2:]

    if mode in ('img', 'view', 'viewer', 'pysxiv'):
        sys.argv = [sys.argv[0]] + rest
        return run_viewer()
    elif mode in ('select', 'sel', 'selector', 'sel_img'):
        sys.argv = [sys.argv[0]] + rest
        return run_selector()
    else:
        sys.stderr.write(f"tkiv: unknown mode: {mode!r}\n")
        sys.stderr.write(
            f"usage: {os.path.basename(sys.argv[0])} {{img|select}} [OPTIONS] ...\n")
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
