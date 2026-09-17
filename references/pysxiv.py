#!/usr/bin/env python3
"""
pysxiv — a Python image viewer modeled after nsxiv.

Dependencies:
    pip install Pillow pyvips

Image decoding is done with libvips (via pyvips) which provides lazy,
shrink-on-load decoding. Pillow is only used as the Tkinter bridge
(ImageTk.PhotoImage) and for per-pixel enhancements (gamma/brightness/
contrast) and simple geometric transforms.

Concurrency model:
    * The current image is decoded on a background thread; the UI stays
      responsive and stale requests are discarded via a token.
    * Neighbouring images (n-1, n+1) are prefetched in parallel into a
      small LRU cache so stepping through a directory feels instant.
    * Thumbnails are decoded through a separate thread pool, a few at
      a time, only for the currently visible page of the grid.
    * Worker threads never touch Tk.  They post callbacks onto a
      thread-safe queue which the main thread drains periodically.

Not implemented (compared to nsxiv):
    * persistent thumbnail cache  (-c/--clean-cache, --update-cache)
    * libexif auto-orientation
    * embed into an existing window (-e)
    * X resources
    * external scripts: image-info, thumb-info, key-handler, win-title
    * inotify (autoreload is done via polling instead)
"""

import argparse
import os
import queue
import stat
import sys
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageOps, ImageEnhance
except ImportError:
    sys.stderr.write("Error: Pillow is required. Install with: pip install Pillow\n")
    sys.exit(1)

try:
    import pyvips
    import numpy as _np
    HAVE_VIPS = True
except ImportError:
    pyvips = None
    _np = None
    HAVE_VIPS = False

import tkinter as tk
from tkinter import font as tkfont


VERSION  = "0.1.0"
PROGNAME = "pysxiv"


# ---------------------------------------------------------------- constants
SCALE_DOWN   = 'd'
SCALE_FIT    = 'f'
SCALE_FILL   = 'F'
SCALE_WIDTH  = 'w'
SCALE_HEIGHT = 'h'
SCALE_ZOOM   = 'z'

ZOOM_LEVELS = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0, 8.0]
ZOOM_MIN, ZOOM_MAX = ZOOM_LEVELS[0], ZOOM_LEVELS[-1]

SLIDESHOW_DELAY   = 5      # seconds
DEF_ANIM_DELAY    = 75     # ms
CC_STEPS          = 32
GAMMA_MAX         = 10.0
BRIGHTNESS_MAX    = 2.0
CONTRAST_MAX      = 4.0

MODE_IMAGE, MODE_THUMB = 'i', 't'

FF_MARK, FF_WARN = 1, 2

THUMB_SIZES      = [32, 64, 96, 128, 160, 200, 240, 300, 400]
THUMB_SIZE_DEF   = 3

DIR_LEFT, DIR_RIGHT, DIR_UP, DIR_DOWN = 1, 2, 4, 8
DEGREE_90, DEGREE_180, DEGREE_270     = 1, 2, 3
FLIP_HORIZONTAL, FLIP_VERTICAL        = 1, 2
IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
    '.webp', '.ppm', '.pgm', '.pbm', '.pnm', '.ico', '.jpe',
    '.jfif', '.pcx', '.tga', '.xpm', '.jp2', '.j2k',
    '.avif', '.heic', '.heif',
}

# Maximum dimension used to downscale very large images on load. libvips
# performs shrink-on-load so we never fully materialise a giant bitmap.
MAX_LOAD_DIM = 4096

# --- concurrency knobs ----------------------------------------------------
IMG_WORKERS         = 4     # threads for current-image decode + prefetch
THUMB_WORKERS       = 4     # threads for thumbnail decode
PREFETCH_MAX        = 3     # entries kept in the neighbour LRU cache
THUMB_MAX_IN_FLIGHT = 8     # cap on concurrent+queued thumbnail jobs
QUEUE_POLL_MS       = 20    # main-thread poll interval for worker results


# ---------------------------------------------------------------- helpers
def file_is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def collect_dir(d, recursive, include_hidden):
    """Collect image files from a directory, returning a sorted list."""
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
        out.extend(collect_dir(s, recursive, include_hidden))
    return out


def _nearest_thumb_idx(size):
    """Find the closest index in THUMB_SIZES to the requested size."""
    best = 0
    best_d = abs(THUMB_SIZES[0] - size)
    for i, s in enumerate(THUMB_SIZES):
        d = abs(s - size)
        if d < best_d:
            best_d = d
            best = i
    return best


# ---------------------------------------------------------------- vips bridge
def _vips_to_pil(vimg):
    """Convert a pyvips Image into a Pillow Image (8-bit per channel)."""
    if vimg.format != 'uchar':
        vimg = vimg.cast('uchar')

    arr = vimg.numpy()

    if arr.ndim == 2:
        if not arr.flags['C_CONTIGUOUS']:
            arr = _np.ascontiguousarray(arr)
        return Image.fromarray(arr, 'L')

    b = arr.shape[2]
    if not arr.flags['C_CONTIGUOUS']:
        arr = _np.ascontiguousarray(arr)

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
    """Load an image (possibly animated) via libvips.

    Returns (list_of_PIL_frames, list_of_delays_ms).
    libvips evaluates the pipeline lazily: nothing is decoded until numpy()
    is called, and we optionally use shrink-on-load for large images.
    """
    try:
        vimg = pyvips.Image.new_from_file(path, n=-1)
    except Exception:
        vimg = pyvips.Image.new_from_file(path)

    # Capture page metadata *before* resizing.
    n_pages = 1
    try:
        n_pages = int(vimg.get('n-pages') or 1)
    except Exception:
        pass
    if n_pages < 1:
        n_pages = 1

    # Optional shrink-on-load to bound memory.
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
    """Pillow fallback for formats libvips might not handle."""
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
    """Load an image file into PIL frames. Tries libvips first.

    Safe to call from a worker thread.  Returns (frames, delays).
    """
    if HAVE_VIPS:
        try:
            return _vips_load_frames(path, max_dim=max_dim)
        except Exception:
            pass
    return _pil_load_frames(path)


def load_thumbnail(path, size):
    """Load and downscale a thumbnail. Uses libvips shrink-on-load.

    Safe to call from a worker thread.  Returns a PIL Image.
    """
    if HAVE_VIPS:
        try:
            vimg = pyvips.Image.thumbnail(path, size, height=size)
            pil_img = _vips_to_pil(vimg)
            if pil_img.mode != 'RGBA':
                pil_img = pil_img.convert('RGBA')
            return pil_img
        except Exception:
            pass
    im = Image.open(path).convert('RGBA')
    im.thumbnail((size, size), Image.LANCZOS)
    return im


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        prog=PROGNAME, add_help=False, allow_abbrev=False,
        usage='%(prog)s [-abcfHhiopqrtvZ0] [-A FRAMERATE] [-e WID] [-G GAMMA] '
              '[-g GEOMETRY] [-N NAME] [-n NUM] [-S DELAY] [-s MODE] '
              '[-T SIZE] [-z ZOOM] FILES...',
    )
    p.add_argument('-a', '--animate', action='store_true')
    p.add_argument('-A', '--framerate', type=int, default=0)
    p.add_argument('--assume-files', action='store_true')
    p.add_argument('-b', '--no-bar', action='store_true')
    p.add_argument('--bar', action='store_true')
    p.add_argument('-c', '--clean-cache', action='store_true')
    p.add_argument('-e', '--embed', type=int, default=0)
    p.add_argument('-f', '--fullscreen', action='store_true')
    p.add_argument('-G', '--gamma', type=int, default=0)
    p.add_argument('-g', '--geometry', default=None)
    p.add_argument('-H', '--hidden', action='store_true')
    p.add_argument('-h', '--help', action='store_true')
    p.add_argument('-i', '--stdin', action='store_true', dest='from_stdin')
    p.add_argument('-n', '--start-at', type=int, default=1)
    p.add_argument('-N', '--name', default=None)
    p.add_argument('--class', dest='class_', default=None)
    p.add_argument('-o', '--stdout', action='store_true')
    p.add_argument('-p', '--private', action='store_true', dest='private_mode')
    p.add_argument('-q', '--quiet', action='store_true')
    p.add_argument('-r', '--recursive', action='store_true')
    p.add_argument('-S', '--ss-delay', type=float, default=0.0)
    p.add_argument('-s', '--scale-mode', default='d')
    p.add_argument('-t', '--thumbnail', action='store_true', dest='thumb_mode')
    p.add_argument('-T', '--thumb-size', type=int, default=None,
                   help='thumbnail size in pixels (snapped to nearest of %s)'
                        % (THUMB_SIZES,))
    p.add_argument('-v', '--version', action='store_true')
    p.add_argument('-z', '--zoom', type=int, default=0)
    p.add_argument('-Z', '--zoom-100', action='store_true')
    p.add_argument('-0', '--null', action='store_true', dest='using_null')
    p.add_argument('--anti-alias',  nargs='?', const='yes', default='yes')
    p.add_argument('--alpha-layer', nargs='?', const='yes', default='no')
    p.add_argument('--cache-allow', default=None)
    p.add_argument('--cache-deny',  default=None)
    p.add_argument('--update-cache', action='store_true')
    p.add_argument('files', nargs='*')
    return p


# ---------------------------------------------------------------- actions
NORMAL_ACTIONS = {
    'q': 'quit',                'Q': 'pick_quit',
    'Return': 'switch_mode',    'f': 'toggle_fullscreen',
    'b': 'toggle_bar',          'g': 'first',           'G': 'last',
    'r': 'reload_image',        'D': 'remove_image',
    'plus': 'zoom_in',          'KP_Add': 'zoom_in',
    'minus': 'zoom_out',        'KP_Subtract': 'zoom_out',
    'm': 'toggle_mark',         'M': 'mark_range',
    'N': 'nav_marked_next',     'P': 'nav_marked_prev',
    'braceleft': 'gamma_down',  'braceright': 'gamma_up',
    'parenleft': 'contrast_down', 'parenright': 'contrast_up',
    'h': 'move_left',  'Left':  'move_left',
    'j': 'move_down',  'Down':  'move_down',
    'k': 'move_up',    'Up':    'move_up',
    'l': 'move_right', 'Right': 'move_right',
    'R': 't_reload_all',
    'n': 'navigate_next', 'space': 'navigate_next',
    'p': 'navigate_prev', 'BackSpace': 'navigate_prev',
    'bracketright': 'navigate_10', 'bracketleft': 'navigate_m10',
    'z': 'scroll_center', 'equal': 'zoom_100',
    'w': 'fit_down', 'W': 'fit', 'F': 'fill',
    'e': 'fit_width', 'E': 'fit_height',
    'less': 'rotate_270', 'greater': 'rotate_90', 'question': 'rotate_180',
    'bar': 'flip_h', 'underscore': 'flip_v',
    'a': 'toggle_antialias', 'A': 'toggle_alpha',
    's': 'slideshow',
    'H': 'edge_left', 'J': 'edge_down',
    'K': 'edge_up',   'L': 'edge_right',
}

CTRL_ACTIONS = {
    'h': 'scr_left',  'Left':  'scr_left',
    'j': 'scr_down',  'Down':  'scr_down',
    'k': 'scr_up',    'Up':    'scr_up',
    'l': 'scr_right', 'Right': 'scr_right',
    'm': 'reverse_marks', 'u': 'unmark_all',
    'g': 'gamma_reset',
    'bracketright': 'brightness_up', 'bracketleft': 'brightness_down',
    '6': 'alternate',
    'n': 'frame_next', 'p': 'frame_prev',
    'space': 'toggle_animation', 'a': 'toggle_animation',
}


# ---------------------------------------------------------------- app
class FileEntry:
    __slots__ = ('name', 'path', 'flags')
    def __init__(self, name):
        self.name = name
        self.path = name
        self.flags = 0


class NSXIVApp:
    def __init__(self, root, opts, files):
        self.root = root
        self.opts = opts
        self.files = [FileEntry(f) for f in files]

        if not self.files:
            raise SystemExit("no files")

        start = max(0, min(opts.start_at - 1, len(self.files) - 1))
        self.fileidx   = start
        self.mode      = MODE_THUMB if opts.thumb_mode else MODE_IMAGE
        self.prefix    = 0
        self.markidx   = 0
        self.alternate = 0
        self._timeout_ids = {}
        self._mtimes = {}
        self._resize_pending = False
        self._tns_photos = []
        self._quitting = False

        # ---- async infrastructure ------------------------------------
        self._img_executor   = ThreadPoolExecutor(
            max_workers=IMG_WORKERS, thread_name_prefix='pysxiv-img')
        self._thumb_executor = ThreadPoolExecutor(
            max_workers=THUMB_WORKERS, thread_name_prefix='pysxiv-thumb')
        self._main_queue     = queue.Queue()
        self._load_token     = 0
        self._files_gen      = 0
        self._img_in_flight  = {}                # n -> Future
        self._prefetch_cache = OrderedDict()     # n -> (frames, delays)
        self._thumb_in_flight = set()            # of (i, zl)

        # image state
        self.img_frames    = []
        self.img_delays    = []
        self.img_sel       = 0
        self.img_animate   = opts.animate
        self.img_multi_len = 0
        self.img_w = self.img_h = 0
        self.zoom = 1.0
        self.scalemode = opts.scale_mode
        self.img_x = self.img_y = 0.0
        self.gamma = opts.gamma
        self.brightness = 0
        self.contrast = 0
        self.anti_alias = (opts.anti_alias != 'no')
        self.alpha_layer = (opts.alpha_layer != 'no')

        if opts.zoom_100:
            self.scalemode, self.zoom = SCALE_ZOOM, 1.0
        elif opts.zoom > 0:
            self.scalemode, self.zoom = SCALE_ZOOM, opts.zoom / 100.0

        self.ss_on    = opts.ss_delay > 0
        self.ss_delay = int(opts.ss_delay * 10) if opts.ss_delay > 0 else SLIDESHOW_DELAY * 10

        # thumbnails
        self.tns_thumbs = [None] * len(self.files)
        self.tns_zl = THUMB_SIZE_DEF
        if opts.thumb_size and opts.thumb_size > 0:
            self.tns_zl = _nearest_thumb_idx(opts.thumb_size)
        self.tns_first = self.tns_end = 0
        self.tns_cols = self.tns_rows = 1
        self.tns_bw = 1
        self.tns_dim = 100
        self.tns_x = self.tns_y = 0

        self._setup_ui()
        self._setup_bindings()
        self.root.after(50, self._initial_load)
        self.root.after(500, self._poll_autoreload)
        self.root.after(QUEUE_POLL_MS, self._poll_main_queue)

    # ---------------------------------------------------------- UI
    def _setup_ui(self):
        self.bg = 'white'
        self.fg = 'black'
        self.mark_fg = '#00dd00'

        if self.opts.geometry:
            try:
                self.root.geometry(self.opts.geometry)
            except Exception:
                self.root.geometry('800x600')
        else:
            self.root.geometry('800x600')

        self.root.title(self.opts.name or 'pysxiv')
        if self.opts.fullscreen:
            self.root.attributes('-fullscreen', True)

        self.bar_font = tkfont.Font(family='monospace', size=10)
        self.bar_height = self.bar_font.metrics('linespace') + 4

        self.show_bar = (not self.opts.no_bar) or self.opts.bar

        self.canvas = tk.Canvas(self.root, bg=self.bg, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, side='top')

        self.status = tk.Label(self.root, text='', anchor='w',
                               bg=self.bg, fg=self.fg,
                               font=self.bar_font, padx=5)
        if self.show_bar:
            self.status.pack(fill='x', side='bottom')

        self.root.update_idletasks()
        self.win_w = max(1, self.canvas.winfo_width())
        self.win_h = max(1, self.canvas.winfo_height())

        self.tk_img = None

    def _setup_bindings(self):
        self.root.bind('<KeyPress>', self.on_key)
        for b in (1, 2, 3, 4, 5):
            self.canvas.bind(f'<ButtonPress-{b}>',
                             lambda e, btn=b: self.on_button(e, btn))
        self.canvas.bind('<Configure>', self.on_configure)
        self.root.protocol('WM_DELETE_WINDOW', lambda: self.quit(0))

    def _initial_load(self):
        if self.mode == MODE_IMAGE:
            self.load_image_async(self.fileidx)
        else:
            self.redraw()

    # ------------------------------------------------- main-thread queue
    def _post(self, fn):
        """Called from worker threads: schedule fn to run on main thread."""
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
            if not manual and not self.opts.quiet:
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

        # Indices shifted: invalidate all caches keyed by index.
        self._files_gen += 1
        self._prefetch_cache.clear()
        self._img_in_flight.clear()
        self._thumb_in_flight.clear()
        return True

    # ---------------------------------------------------------- image load
    def _set_current(self, n):
        if n == self.fileidx:
            return
        self.alternate = self.fileidx
        self.fileidx = n

    def _install_image(self, n, frames, delays):
        """Install decoded frames as the current image.  Main thread only."""
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
        """Synchronous, blocking load.  Used by slideshow and autoreload.

        Returns True on success.
        """
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
                if not self.opts.quiet:
                    sys.stderr.write(f"{PROGNAME}: {self.files[n].name}: {e}\n")
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
        return True

    def load_image_async(self, n):
        """Asynchronous load: returns immediately; installs on main thread.

        Updates self.fileidx immediately so subsequent navigation is
        responsive; the previous image stays on screen until the new
        one is ready.
        """
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
        """Main-thread handler for a completed async image decode."""
        if self._quitting:
            return
        if token != self._load_token:
            return          # a newer request superseded this one
        if n < 0 or n >= len(self.files):
            return
        if err is not None:
            # Reuse the synchronous error path (print, remove, advance).
            self.load_image(self.fileidx)
            if not self._quitting:
                self.redraw()
            return
        self._install_image(n, frames, delays)
        self.redraw()
        self._prefetch_neighbors(n)

    def _request_decode(self, n, callback):
        """Submit a decode of file n.

        callback(n, frames, delays, err) runs on the main thread.
        Concurrent requests for the same n are coalesced into one decode.
        """
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
        """Warm the LRU cache with the adjacent files."""
        if self.mode != MODE_IMAGE:
            return
        for d in (1, -1):
            m = n + d
            if 0 <= m < len(self.files):
                self._submit_prefetch(m)

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

    # ---------------------------------------------------------- render
    def redraw(self):
        if self._quitting:
            return
        if self.mode == MODE_IMAGE:
            self.render_image()
        else:
            self.render_thumbnails()
        self.update_info()

    @staticmethod
    def _steps_to_range(d, mx, offset):
        return offset + d * ((1.0 if d <= 0 else (mx - 1.0)) / CC_STEPS)

    def _effective_image(self):
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
            lut = [min(255, int(255 * ((i / 255.0) ** inv) + 0.5)) for i in range(256)]
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
            return
        self._fit()
        self._check_pan()

        im = self._effective_image()
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
        self.canvas.create_image(self.img_x + ix0 * z,
                                 self.img_y + iy0 * z,
                                 anchor='nw', image=self.tk_img)

    # ----------------------------------------------------- lazy thumbs
    def _submit_thumb(self, i):
        """Request an async thumbnail decode for file index i."""
        if i < 0 or i >= len(self.files):
            return
        if self.tns_thumbs[i] is not None:
            return
        key = (i, self.tns_zl)
        if key in self._thumb_in_flight:
            return
        if len(self._thumb_in_flight) >= THUMB_MAX_IN_FLIGHT:
            return

        self._thumb_in_flight.add(key)
        size = THUMB_SIZES[self.tns_zl]
        zl_token = self.tns_zl
        gen = self._files_gen
        path = self.files[i].path

        fut = self._thumb_executor.submit(load_thumbnail, path, size)

        def _done(f, _i=i, _zl=zl_token, _gen=gen):
            try:
                pil = f.result()
            except Exception:
                pil = None
            self._post(lambda: self._on_thumb_ready(_i, _zl, _gen, pil))
        fut.add_done_callback(_done)

    def _on_thumb_ready(self, i, zl_token, gen, pil):
        """Main-thread handler for a completed thumbnail decode."""
        if self._quitting:
            return
        self._thumb_in_flight.discard((i, zl_token))
        if gen != self._files_gen:
            return
        if zl_token != self.tns_zl:
            return
        if i < 0 or i >= len(self.files):
            return

        if pil is None:
            self.tns_thumbs[i] = None
            return

        try:
            ph = ImageTk.PhotoImage(pil)
        except tk.TclError:
            return
        self.tns_thumbs[i] = (ph, pil.size[0], pil.size[1])

        if self.mode == MODE_THUMB and self.tns_first <= i < self.tns_end:
            self.render_thumbnails()
            self.update_info()

    def render_thumbnails(self):
        self.tns_bw  = min(4, ((THUMB_SIZES[self.tns_zl] - 1) >> 5) + 1)
        self.tns_dim = THUMB_SIZES[self.tns_zl] + 2 * self.tns_bw + 6
        self.tns_cols = max(1, self.win_w // self.tns_dim)
        self.tns_rows = max(1, self.win_h // self.tns_dim)

        cnt = len(self.files)

        if cnt < self.tns_cols * self.tns_rows:
            self.tns_first = 0
            visible = cnt
        else:
            if self.fileidx < self.tns_first:
                self.tns_first = (self.fileidx // self.tns_cols) * self.tns_cols
            elif self.fileidx >= self.tns_first + self.tns_cols * self.tns_rows:
                self.tns_first = ((self.fileidx // self.tns_cols)
                                  - self.tns_rows + 1) * self.tns_cols
                if self.tns_first < 0:
                    self.tns_first = 0
            visible = self.tns_cols * self.tns_rows
            if self.tns_first + visible > cnt:
                self.tns_first = max(0, ((cnt - 1) // self.tns_cols)
                                     - self.tns_rows + 1) * self.tns_cols
                visible = min(visible, cnt - self.tns_first)

        self.tns_end = self.tns_first + visible

        rows_used = (visible + self.tns_cols - 1) // self.tns_cols
        cols_used = min(visible, self.tns_cols)
        self.tns_x = (self.win_w - cols_used * self.tns_dim) // 2 + self.tns_bw + 3
        self.tns_y = (self.win_h - rows_used * self.tns_dim) // 2 + self.tns_bw + 3

        self.canvas.delete('all')
        self._tns_photos = []

        x, y = self.tns_x, self.tns_y
        for i in range(self.tns_first, self.tns_end):
            t = self.tns_thumbs[i]
            if t is None:
                # Placeholder frame; queue an async decode.
                self._submit_thumb(i)
                if i == self.fileidx:
                    self.canvas.create_rectangle(
                        x - self.tns_bw, y - self.tns_bw,
                        x + self.tns_dim, y + self.tns_dim,
                        outline=self.fg, width=self.tns_bw)
                if self.files[i].flags & FF_MARK:
                    s = THUMB_SIZES[self.tns_zl]
                    self.canvas.create_rectangle(
                        x + s - 2, y + s - 2, x + s + 4, y + s + 4,
                        fill=self.mark_fg, outline=self.mark_fg)
            else:
                ph, tw, th = t
                px = x + (THUMB_SIZES[self.tns_zl] - tw) // 2
                py = y + (THUMB_SIZES[self.tns_zl] - th) // 2
                self.canvas.create_image(px, py, anchor='nw', image=ph)
                self._tns_photos.append(ph)

                if i == self.fileidx:
                    self.canvas.create_rectangle(
                        x - self.tns_bw, y - self.tns_bw,
                        x + self.tns_dim, y + self.tns_dim,
                        outline=self.fg, width=self.tns_bw)

                if self.files[i].flags & FF_MARK:
                    s = THUMB_SIZES[self.tns_zl]
                    self.canvas.create_rectangle(
                        x + s - 2, y + s - 2, x + s + 4, y + s + 4,
                        fill=self.mark_fg, outline=self.mark_fg)

            if (i + 1 - self.tns_first) % self.tns_cols == 0:
                x, y = self.tns_x, y + self.tns_dim
            else:
                x += self.tns_dim

    def update_info(self):
        if not self.show_bar:
            return
        cnt = len(self.files)
        if cnt == 0:
            return
        fw = len(str(cnt))
        mark = '* ' if (self.files[self.fileidx].flags & FF_MARK) else ''
        name = os.path.basename(self.files[self.fileidx].name)

        if self.mode == MODE_THUMB:
            text = f"{mark}{self.fileidx + 1:0{fw}d}/{cnt}  {name}"
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
            parts.append(f"{self.fileidx + 1:0{fw}d}/{cnt}")
            text = f"{mark}{'  '.join(parts)}  {name}"
        self.status.config(text=text)

    # ---------------------------------------------------------- actions
    def quit(self, status=0):
        if self._quitting:
            return
        self._quitting = True

        if self.opts.stdout:
            sep = '\0' if self.opts.using_null else '\n'
            marked = [f for f in self.files if f.flags & FF_MARK]
            for f in (marked if marked else [self.files[self.fileidx]]):
                sys.stdout.write(f.name + sep)
            sys.stdout.flush()

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

    def _navigate(self, n):
        if 0 <= n < len(self.files) and n != self.fileidx:
            if self.mode == MODE_IMAGE:
                self.load_image_async(n)
            else:
                self.fileidx = n
                self.redraw()
            return True
        return False

    def act_pick_quit(self):
        self.quit(0)

    def act_switch_mode(self):
        if self.mode == MODE_IMAGE:
            self.mode = MODE_THUMB
            self.reset_timeout('animate')
            self.ss_on = False
            self.reset_timeout('slideshow')
            self.redraw()
        else:
            self.mode = MODE_IMAGE
            self.canvas.delete('all')
            self.tk_img = None
            self.load_image_async(self.fileidx)
            self.update_info()

    def act_toggle_fullscreen(self):
        cur = bool(self.root.attributes('-fullscreen'))
        self.root.attributes('-fullscreen', not cur)
        self.root.after(100, self._refresh_size)

    def act_toggle_bar(self):
        self.show_bar = not self.show_bar
        if self.show_bar:
            self.status.pack(fill='x', side='bottom')
        else:
            self.status.pack_forget()
        self.root.after(50, self._refresh_size)

    def _refresh_size(self):
        if self._quitting:
            return
        self.root.update_idletasks()
        self.win_w = max(1, self.canvas.winfo_width())
        self.win_h = max(1, self.canvas.winfo_height())
        self.redraw()

    def act_first(self):
        self._navigate(0)

    def act_last(self):
        n = self.prefix - 1 if 0 < self.prefix <= len(self.files) else len(self.files) - 1
        self._navigate(n)

    def act_reload(self):
        if self.mode == MODE_IMAGE:
            self._prefetch_cache.pop(self.fileidx, None)
            self.load_image_async(self.fileidx)
        else:
            self.tns_thumbs[self.fileidx] = None
            self.redraw()

    def act_remove(self):
        if self.remove_file(self.fileidx, True):
            if self.mode == MODE_IMAGE:
                self.load_image_async(self.fileidx)
            else:
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
        self._mark(self.fileidx, not (self.files[self.fileidx].flags & FF_MARK))
        self.markidx = self.fileidx
        self.redraw()

    def act_mark_range(self):
        if not self.files:
            return
        a = min(self.markidx, self.fileidx)
        b = max(self.markidx, self.fileidx)
        on = bool(self.files[self.markidx].flags & FF_MARK)
        for i in range(a, b + 1):
            self._mark(i, on)
        self.redraw()

    def act_reverse_marks(self):
        for f in self.files:
            f.flags ^= FF_MARK
        self.redraw()

    def act_unmark_all(self):
        for f in self.files:
            f.flags &= ~FF_MARK
        self.redraw()

    def act_nav_marked(self, d):
        n = self.prefix if self.prefix > 0 else 1
        if d < 0:
            n = -n
        i = self.fileidx
        step = 1 if d > 0 else -1
        while n != 0 and 0 <= i + step < len(self.files):
            i += step
            if self.files[i].flags & FF_MARK:
                n -= step
        self._navigate(i)

    def act_gamma(self, d):
        mult = self.prefix if self.prefix else 1
        newv = 0 if d == 0 else max(-CC_STEPS, min(CC_STEPS, self.gamma + d * mult))
        if newv != self.gamma:
            self.gamma = newv
            self.redraw()

    def act_brightness(self, d):
        mult = self.prefix if self.prefix else 1
        newv = max(-CC_STEPS, min(CC_STEPS, self.brightness + d * mult))
        if newv != self.brightness:
            self.brightness = newv
            self.redraw()

    def act_contrast(self, d):
        mult = self.prefix if self.prefix else 1
        newv = max(-CC_STEPS, min(CC_STEPS, self.contrast + d * mult))
        if newv != self.contrast:
            self.contrast = newv
            self.redraw()

    def act_scroll_screen(self, direction):
        if self.mode == MODE_IMAGE:
            self.act_scroll(direction, screen=True)
            return
        rows = self.tns_rows
        step = self.tns_cols * rows
        if direction == DIR_DOWN:
            self.tns_first = min(self.tns_first + step,
                                 max(0, len(self.files) - step))
            if self.fileidx < self.tns_first:
                self.fileidx = self.tns_first
        elif direction == DIR_UP:
            self.tns_first = max(0, self.tns_first - step)
            if self.fileidx >= self.tns_first + step:
                self.fileidx = self.tns_first + step - 1
        self.redraw()

    def _zoom_to(self, z):
        if ZOOM_MIN <= z <= ZOOM_MAX and self.zoom > 0:
            cx, cy = self.win_w / 2, self.win_h / 2
            self.img_x = cx - (cx - self.img_x) * z / self.zoom
            self.img_y = cy - (cy - self.img_y) * z / self.zoom
            self.zoom = z
            self.scalemode = SCALE_ZOOM

    def act_zoom(self, d):
        if self.mode == MODE_THUMB:
            old = self.tns_zl
            self.tns_zl = max(0, min(len(THUMB_SIZES) - 1, self.tns_zl + d))
            if self.tns_zl != old:
                self.tns_thumbs = [None] * len(self.files)
                self._thumb_in_flight.clear()
            self.redraw()
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

    def act_scroll_edge(self, direction):
        if self.mode != MODE_IMAGE:
            return
        if direction & DIR_LEFT:  self.img_x = 0
        if direction & DIR_RIGHT: self.img_x = self.win_w - self.img_w * self.zoom
        if direction & DIR_UP:    self.img_y = 0
        if direction & DIR_DOWN:  self.img_y = self.win_h - self.img_h * self.zoom
        self._check_pan()
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
        if self.prefix > 0:
            self.ss_on = True
            self.ss_delay = self.prefix * 10
        elif self.ss_on:
            self.ss_on = False
            self.reset_timeout('slideshow')
        else:
            self.ss_on = True
        if self.ss_on:
            self._schedule_slideshow()
        self.redraw()

    def _schedule_slideshow(self):
        if self.ss_on:
            delay = self.ss_delay * 100
            if len(self.img_frames) > 1 and self.img_animate:
                delay = max(delay, self.img_multi_len)
            self.set_timeout('slideshow', delay, self.slideshow_next, overwrite=False)

    def slideshow_next(self):
        n = self.fileidx + 1 if self.fileidx + 1 < len(self.files) else 0
        self.load_image(n)
        self.redraw()
        self._schedule_slideshow()

    def act_alternate(self):
        if self.alternate != self.fileidx:
            self._navigate(self.alternate)

    def act_frame_nav(self, d):
        if len(self.img_frames) > 1 and not self.img_animate:
            mult = self.prefix if self.prefix else 1
            n = max(0, min(len(self.img_frames) - 1, self.img_sel + d * mult))
            if n != self.img_sel:
                self.img_sel = n
                self.img_w, self.img_h = self.img_frames[n].size
                self.redraw()

    def act_toggle_animation(self):
        if len(self.img_frames) > 1:
            self.img_animate = not self.img_animate
            if self.img_animate:
                self.animate()
            else:
                self.reset_timeout('animate')

    def act_move_sel(self, direction):
        if self.mode != MODE_THUMB:
            return
        n = self.prefix if self.prefix > 0 else 1
        old = self.fileidx
        if   direction == DIR_UP:
            self.fileidx = max(self.fileidx - n * self.tns_cols,
                               self.fileidx % self.tns_cols)
        elif direction == DIR_DOWN:
            last_row = (len(self.files) - 1) // self.tns_cols
            col = self.fileidx % self.tns_cols
            maxtarget = last_row * self.tns_cols + min((len(self.files) - 1) % self.tns_cols, col)
            self.fileidx = min(self.fileidx + n * self.tns_cols, maxtarget)
        elif direction == DIR_LEFT:
            self.fileidx = max(self.fileidx - n, 0)
        elif direction == DIR_RIGHT:
            self.fileidx = min(self.fileidx + n, len(self.files) - 1)
        if self.fileidx != old:
            self.redraw()

    def act_navigate(self, d):
        if self.mode != MODE_IMAGE:
            return
        mult = self.prefix if self.prefix else 1
        new = max(0, min(len(self.files) - 1, self.fileidx + d * mult))
        if new != self.fileidx:
            self.load_image_async(new)

    # ---------------------------------------------------------- events
    def _dispatch(self, action):
        if   action == 'quit':              self.quit(0)
        elif action == 'pick_quit':         self.act_pick_quit()
        elif action == 'switch_mode':       self.act_switch_mode()
        elif action == 'toggle_fullscreen': self.act_toggle_fullscreen()
        elif action == 'toggle_bar':        self.act_toggle_bar()
        elif action == 'first':             self.act_first()
        elif action == 'last':              self.act_last()
        elif action == 'reload_image':      self.act_reload()
        elif action == 'remove_image':      self.act_remove()
        elif action == 'toggle_mark':       self.act_toggle_mark()
        elif action == 'mark_range':        self.act_mark_range()
        elif action == 'reverse_marks':     self.act_reverse_marks()
        elif action == 'unmark_all':        self.act_unmark_all()
        elif action == 'nav_marked_next':   self.act_nav_marked(1)
        elif action == 'nav_marked_prev':   self.act_nav_marked(-1)
        elif action == 'gamma_down':        self.act_gamma(-1)
        elif action == 'gamma_up':          self.act_gamma(1)
        elif action == 'gamma_reset':       self.act_gamma(0)
        elif action == 'brightness_up':     self.act_brightness(1)
        elif action == 'brightness_down':   self.act_brightness(-1)
        elif action == 'contrast_up':       self.act_contrast(1)
        elif action == 'contrast_down':     self.act_contrast(-1)
        elif action == 'zoom_in':           self.act_zoom(1)
        elif action == 'zoom_out':          self.act_zoom(-1)
        elif action == 'scr_left':          self.act_scroll_screen(DIR_LEFT)
        elif action == 'scr_right':         self.act_scroll_screen(DIR_RIGHT)
        elif action == 'scr_up':            self.act_scroll_screen(DIR_UP)
        elif action == 'scr_down':          self.act_scroll_screen(DIR_DOWN)
        elif action == 'move_left':
            if self.mode == MODE_IMAGE: self.act_scroll(DIR_LEFT)
            else:                       self.act_move_sel(DIR_LEFT)
        elif action == 'move_right':
            if self.mode == MODE_IMAGE: self.act_scroll(DIR_RIGHT)
            else:                       self.act_move_sel(DIR_RIGHT)
        elif action == 'move_up':
            if self.mode == MODE_IMAGE: self.act_scroll(DIR_UP)
            else:                       self.act_move_sel(DIR_UP)
        elif action == 'move_down':
            if self.mode == MODE_IMAGE: self.act_scroll(DIR_DOWN)
            else:                       self.act_move_sel(DIR_DOWN)
        elif action == 'navigate_next':     self.act_navigate(1)
        elif action == 'navigate_prev':     self.act_navigate(-1)
        elif action == 'navigate_10':       self.act_navigate(10)
        elif action == 'navigate_m10':      self.act_navigate(-10)
        elif action == 'alternate':         self.act_alternate()
        elif action == 'frame_next':        self.act_frame_nav(1)
        elif action == 'frame_prev':        self.act_frame_nav(-1)
        elif action == 'toggle_animation':  self.act_toggle_animation()
        elif action == 'edge_left':         self.act_scroll_edge(DIR_LEFT)
        elif action == 'edge_right':        self.act_scroll_edge(DIR_RIGHT)
        elif action == 'edge_up':           self.act_scroll_edge(DIR_UP)
        elif action == 'edge_down':         self.act_scroll_edge(DIR_DOWN)
        elif action == 'scroll_center':     self.act_scroll_center()
        elif action == 'zoom_100':
            self.scalemode = SCALE_ZOOM
            self._zoom_to(1.0)
            self.redraw()
        elif action == 'fit_down':          self.act_fit(SCALE_DOWN)
        elif action == 'fit':               self.act_fit(SCALE_FIT)
        elif action == 'fill':              self.act_fit(SCALE_FILL)
        elif action == 'fit_width':         self.act_fit(SCALE_WIDTH)
        elif action == 'fit_height':        self.act_fit(SCALE_HEIGHT)
        elif action == 'rotate_90':         self.act_rotate(DEGREE_90)
        elif action == 'rotate_180':        self.act_rotate(DEGREE_180)
        elif action == 'rotate_270':        self.act_rotate(DEGREE_270)
        elif action == 'flip_h':            self.act_flip(FLIP_HORIZONTAL)
        elif action == 'flip_v':            self.act_flip(FLIP_VERTICAL)
        elif action == 'toggle_antialias':  self.act_toggle_antialias()
        elif action == 'toggle_alpha':      self.act_toggle_alpha()
        elif action == 'slideshow':         self.act_slideshow()
        elif action == 't_reload_all':
            self.tns_thumbs = [None] * len(self.files)
            self._thumb_in_flight.clear()
            self.redraw()

    def on_key(self, event):
        keysym = event.keysym
        ctrl = bool(event.state & 0x4)
        alt  = bool(event.state & 0x8)

        if not ctrl and not alt and len(keysym) == 1 and keysym.isdigit():
            self.prefix = self.prefix * 10 + int(keysym)
            return

        if ctrl and not alt:
            act = CTRL_ACTIONS.get(keysym)
        elif not ctrl and not alt:
            act = NORMAL_ACTIONS.get(keysym)
        else:
            act = None

        if act:
            try:
                self._dispatch(act)
            except Exception as e:
                if not self.opts.quiet:
                    sys.stderr.write(f"{PROGNAME}: {e}\n")

        self.prefix = 0

    def on_button(self, event, button):
        ctrl = bool(event.state & 0x4)
        if self.mode == MODE_IMAGE:
            if button == 1 and not ctrl:
                nw = self.win_w // 3
                if event.x < nw:
                    self.act_navigate(-1)
                elif event.x > self.win_w - nw:
                    self.act_navigate(1)
            elif button == 1 and ctrl:
                pass  # drag: not implemented
            elif button == 3:
                self.act_switch_mode()
            elif button == 4:
                self.act_zoom(1)
            elif button == 5:
                self.act_zoom(-1)
        else:
            if button == 1:
                n = self._thumb_hit(event.x, event.y)
                if n is not None:
                    self.fileidx = n
                    self.redraw()
            elif button == 3:
                n = self._thumb_hit(event.x, event.y)
                if n is not None:
                    self._mark(n, not (self.files[n].flags & FF_MARK))
                    self.redraw()
            elif button == 4:
                self.tns_first = max(0, self.tns_first - self.tns_cols)
                self.redraw()
            elif button == 5:
                maxf = max(0, len(self.files) - self.tns_cols * self.tns_rows)
                self.tns_first = min(maxf, self.tns_first + self.tns_cols)
                self.redraw()

    def _thumb_hit(self, x, y):
        if x < self.tns_x or y < self.tns_y:
            return None
        col = (x - self.tns_x) // self.tns_dim
        row = (y - self.tns_y) // self.tns_dim
        if col < 0 or col >= self.tns_cols:
            return None
        n = self.tns_first + row * self.tns_cols + col
        if n >= self.tns_end or n >= len(self.files):
            return None
        return n

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
        self.win_w = max(1, self.canvas.winfo_width())
        self.win_h = max(1, self.canvas.winfo_height())
        self.redraw()

    def _poll_autoreload(self):
        try:
            if self.mode == MODE_IMAGE and self.img_frames:
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


# ---------------------------------------------------------------- main
def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.help:
        print(f"{PROGNAME} {VERSION}")
        print(parser.format_usage().rstrip())
        print("\nKey bindings (see nsxiv(1) for the full list):")
        print("  q        quit          Q       pick-quit")
        print("  Return   switch mode   f       fullscreen")
        print("  b        toggle bar    r       reload")
        print("  g/G      first/last    n/p     next/prev")
        print("  +/-      zoom          hjkl    scroll")
        print("  w/W/F/e/E fit modes    m       mark")
        print("  s        slideshow     a/A     antialias/alpha")
        print("  </>/|/_ rotate/flip    z       center")
        print("\nOptions:")
        print("  -t              start in thumbnail mode")
        print("  -T SIZE         thumbnail size in pixels")
        print("                  (snapped to nearest of %s)" % (THUMB_SIZES,))
        return 0

    if args.version:
        print(f"{PROGNAME} {VERSION}")
        return 0

    if args.class_:
        sys.stderr.write("pysxiv: --class is deprecated, use --name instead\n")
        if not args.name:
            args.name = args.class_

    if not HAVE_VIPS and not args.quiet:
        sys.stderr.write(f"{PROGNAME}: warning: pyvips not available; "
                         "falling back to Pillow for image decoding. "
                         "Install with: pip install pyvips\n")

    # collect files
    file_list = []
    if args.from_stdin or (len(args.files) == 1 and args.files[0] == '-'):
        sep = '\0' if args.using_null else '\n'
        data = sys.stdin.read()
        for e in data.split(sep):
            if e:
                file_list.append(e)
    else:
        for f in args.files:
            if not os.path.exists(f):
                if not args.quiet:
                    sys.stderr.write(f"{PROGNAME}: {f}: No such file or directory\n")
                continue
            if os.path.isdir(f):
                file_list.extend(collect_dir(f, args.recursive, args.hidden))
            else:
                file_list.append(f)

    if not file_list:
        sys.stderr.write(f"{PROGNAME}: No valid image file given, aborting\n")
        return 1

    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.stderr.write(f"{PROGNAME}: cannot open display: {e}\n")
        return 1

    NSXIVApp(root, args, file_list)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
