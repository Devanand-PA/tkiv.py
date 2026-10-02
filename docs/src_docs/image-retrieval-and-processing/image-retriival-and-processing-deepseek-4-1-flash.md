# Image Retrieval and Processing in `tkiv.py`

This document describes how `tkiv.py` retrieves image files and processes them for display in its three modes: image viewer, gallery, and list. It covers file discovery, filtering/sorting, decoding via `pyvips` or Pillow, asynchronous loading, caching, rendering, color adjustments, animation, thumbnails, and error handling.

The code is a single unified application (`TkivApp`) used by both `tkiv.py img` and `tkiv.py select`.

---

## 1. High-level architecture

At a high level, image handling is split into four layers:

1. **File retrieval**
   - CLI arguments and stdin are converted into `FileEntry` objects.
   - Directories are scanned either eagerly (`collect_dir`) or lazily (`start_lazy_scan`).
   - A visible subset is maintained by search/filtering and sorting.

2. **Decoding**
   - Full images are decoded by `load_frames()`.
   - Gallery thumbnails are decoded by `load_gallery_thumb()`.
   - List previews use `load_frames()` at a reduced size.
   - `pyvips` is preferred when available; Pillow is the fallback.

3. **Asynchronous scheduling and caching**
   - Full-image decodes run in a 4-worker `ThreadPoolExecutor`.
   - Thumbnail decodes run in a separate 4-worker executor.
   - Results are posted back to the Tk main thread through a `queue.Queue`.
   - A small in-memory prefetch cache (`OrderedDict`, max 3) holds neighboring full images.
   - Gallery thumbnails are cached in `tns_thumbs`.
   - A disk-backed WEBP thumbnail cache exists in `_decode_thumb()` / `_disk_cache_path()` but is not called by `TkivApp` in this version.

4. **Rendering and processing**
   - Viewer mode crops the visible region, applies brightness/contrast/gamma, flattens alpha, resizes, and draws to a `Canvas`.
   - Gallery mode computes tile metrics, renders only visible tiles, and fits captions.
   - List mode shows a listbox and a preview label.

---

## 2. File retrieval

### 2.1 Image extensions

`IMAGE_EXTS` defines the recognized image suffixes:

```python
IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
    '.webp', '.ppm', '.pgm', '.pbm', '.pnm', '.ico', '.jpe',
    '.jfif', '.pcx', '.tga', '.xpm', '.jp2', '.j2k',
    '.avif', '.heic', '.heif',
}
```

`file_is_image(path)` simply checks `os.path.splitext(path)[1].lower()` against this set.

### 2.2 Eager directory collection

`collect_dir(d, recursive, include_hidden, sort_time=False)` walks a directory:

- Uses `os.listdir(d)` and sorts entries by name.
- Skips hidden names unless `include_hidden=True`.
- Calls `os.stat()` on each entry.
- If it is a directory and `recursive=True`, it is queued for recursion.
- If it is a regular file and `file_is_image()` is true, it is appended to `out`.
- After processing the current directory, it recurses into subdirectories.
- If `sort_time=True`, the final list is sorted by `os.path.getmtime()` in reverse order (newest first).

Important ordering behavior: without `sort_time`, files in the current directory appear before files from recursive subdirectories, and each directory’s entries are name-sorted. The list is not globally name-sorted.

### 2.3 Lazy scanning

With `--lazy`, the UI starts before the file list is fully known. `start_lazy_scan(paths, recursive, sort_time)` starts a daemon thread that:

1. Resolves each path.
2. For directories, uses `Path.glob("**/*")` if recursive, else `Path.glob("*")`.
3. Sorts entries by name, or by mtime descending if `sort_time=True`.
4. Filters by `IMAGE_EXTS`.
5. De-duplicates with a `seen` set.
6. Accumulates batches of `LAZY_BATCH_SIZE` (128) paths.
7. Posts each batch to the Tk main thread via `_post()`.

The main thread calls `_queue_lazy_files()` and `_commit_lazy_batch()`:

- Converts paths to `FileEntry` objects.
- Extends `self.files` and `self.tns_thumbs`.
- Updates `self._visible_indices`.
- Invalidates the gallery aspect cache if the scan crosses `GALLERY_ASPECT_SAMPLE` (20) files.
- On the first batch, selects `_desired_start` and triggers the initial load.
- Schedules a redraw.

When scanning finishes, `_lazy_scan_finished()` commits any remaining batch and applies sorting if a sort mode is active.

### 2.4 Stdin, viewer, and selector retrieval

`tkiv.py img`:

- If `--stdin` or a single `-` file is given, reads stdin split by `\n` or `\0`.
- Otherwise, for each argument:
  - Directories are scanned with `collect_dir()` unless `--lazy` is active.
  - Files are appended directly.
- With `--lazy`, directories are passed to `start_lazy_scan()` instead of being scanned eagerly.

`tkiv.py select`:

- In normal mode, paths are scanned similarly to the viewer.
- In `--dmenu-mode`, it reads two lists: `--list-entries`/`--list-file` and `--image-entries`/`--image-file`. They must have the same length. Each pair becomes a `FileEntry(path, label)`. File existence is not checked; `args.assume_files = True`.

### 2.5 Filtering and visibility

The search bar updates `self._filter_text`. `_rebuild_visible()` builds `self._visible_indices`:

- If the search bar is disabled, all indices are visible.
- Otherwise, the query is lowercased and split on whitespace.
- A file is visible if every term appears in either `f.label.lower()` or `f.path.lower()`.

`_visible_indices` is used for navigation, gallery rendering, list population, and status display.

### 2.6 Sorting

`_apply_sort()` supports:

- `SORT_NONE`
- `SORT_NAME`
- `SORT_MTIME`
- `SORT_SIZE`

Key functions:

```python
SORT_NAME  -> f.label.lower()
SORT_MTIME -> os.path.getmtime(f.path)
SORT_SIZE  -> os.path.getsize(f.path)
```

For `mtime` and `size`, the effective reverse flag is inverted:

```python
rev = self._sort_reverse
if self._sort_mode in (SORT_MTIME, SORT_SIZE):
    rev = not rev
```

This makes the default `mtime` order newest-first and the default `size` order largest-first.

Sorting invalidates:

- `_prefetch_cache`
- `_img_in_flight`
- `_gallery_in_flight`
- `_mtimes`
- gallery aspect cache
- increments `_files_gen` and `_load_token`

It also re-finds the current file by path and refreshes the active mode.

---

## 3. Image decoding pipelines

### 3.1 `load_frames()`: full image decoding

`load_frames(path, max_dim=MAX_LOAD_DIM)` is the main full-image decoder.

```python
def load_frames(path, max_dim=MAX_LOAD_DIM):
    if HAVE_VIPS:
        try:
            return _vips_load_frames(path, max_dim=max_dim)
        except Exception:
            pass
    return _pil_load_frames(path)
```

If `pyvips` and NumPy are importable, `HAVE_VIPS` is true. Any vips exception falls back to Pillow.

#### vips path: `_vips_load_frames()`

1. Opens with `pyvips.Image.new_from_file(path, n=-1)` to load all pages.
2. If that fails, retries without `n=-1`.
3. Reads `n-pages` to determine frame count.
4. If `max_dim` is positive and the image is larger, resizes by a scale factor:
   ```python
   scale = max(vimg.width / max_dim, vimg.height / max_dim)
   if scale > 1.0:
       vimg = vimg.resize(1.0 / scale)
   ```
5. For single-page images, converts to PIL via `_vips_to_pil()` and uses `DEF_ANIM_DELAY`.
6. For multi-page images:
   - Computes `page_height = vimg.height // n_pages`.
   - Crops each page with `vimg.crop(0, i * page_height, vimg.width, page_height)`.
   - Converts each page to PIL.
   - Reads animation delays from `vimg.get('delay')`.
   - Fills missing delays with `DEF_ANIM_DELAY`.

`_vips_to_pil()`:

- Casts to `uchar` if needed.
- Converts to a NumPy array.
- Ensures C-contiguity.
- Maps band count to Pillow modes:
  - 1 band → `L`
  - 2 bands → `LA`
  - 3 bands → `RGB`
  - 4 bands → `RGBA`
  - other → first 4 bands as `RGBA`

#### Pillow path: `_pil_load_frames()`

1. Opens with `Image.open(path)`.
2. Checks `im.n_frames`.
3. If multi-frame:
   - Seeks each frame.
   - Converts to `RGBA` and copies.
   - Reads `duration` from `im.info`, defaulting to `DEF_ANIM_DELAY`.
   - On any exception, discards all frames and falls back to single-frame.
4. If single-frame:
   - Seeks to 0 or reopens.
   - Converts if mode is not `RGB`, `RGBA`, `L`, or `LA`.
   - Returns one frame with `DEF_ANIM_DELAY`.

Pillow is also configured globally with:

```python
ImageFile.LOAD_TRUNCATED_IMAGES = True
```

so partially truncated images can still load.

### 3.2 Gallery thumbnail decoding: `load_gallery_thumb()`

```python
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
```

This is optimized for thumbnail generation:

- vips uses `thumbnail()`, which can use shrink-on-load for JPEG.
- Pillow uses `convert('RGBA')` and `thumbnail(..., LANCZOS)`.

The result is always `RGBA`.

### 3.3 Original size probing: `_get_orig_size()`

Returns `(width, height)` without decoding full pixels:

- vips: `pyvips.Image.new_from_file(path, access='sequential')`
- Pillow: `Image.open(path).size`
- On failure: `(0, 0)`

Used for gallery aspect detection and for disk-cache keys.

### 3.4 Disk thumbnail cache: `_disk_cache_path()` and `_decode_thumb()`

`_disk_cache_path(path, w, h)` builds a SHA-1 key from:

```text
path | st_mtime_ns | st_size | WxH
```

The cache file is stored under:

```text
$XDG_CACHE_HOME/tkiv_thumbs/<first-2-hex>/<hash>.webp
```

`_decode_thumb(path, max_w, max_h)`:

1. Gets original size.
2. Checks the disk cache. If present, opens and returns it.
3. Otherwise decodes:
   - vips: `thumbnail(..., size="down")`, then NumPy → PIL.
   - Pillow: JPEG `draft()`, optional `reduce()`, `thumbnail(BILINEAR, reducing_gap=2.0)`, mode conversion.
4. Saves as WEBP quality 82, method 0, atomically via `.tmp` and `os.replace()`.
5. Returns `(pil_img, orig_size)`.

**Note:** In the provided `TkivApp`, `_decode_thumb()` is not called. Gallery tiles use `load_gallery_thumb()` directly and are not disk-cached. The disk-cache helpers appear to be selector-oriented infrastructure that is currently unused.

---

## 4. Asynchronous loading and caching

### 4.1 Executors, queue, and tokens

The app uses two thread pools:

```python
self._img_executor   = ThreadPoolExecutor(max_workers=IMG_WORKERS)   # 4
self._thumb_executor = ThreadPoolExecutor(max_workers=THUMB_WORKERS) # 4
```

Worker threads do not touch Tk widgets. They post callables to `self._main_queue`. `_poll_main_queue()` runs every `QUEUE_POLL_MS` (20 ms), processes up to 64 callables, and also applies a pending sort if `_sort_dirty` is set.

Important generation/token fields:

| Field | Purpose |
|---|---|
| `_load_token` | Discards stale full-image decodes |
| `_files_gen` | Discards stale gallery thumbnails after file list/sort changes |
| `_aspect_gen` | Discards stale aspect-ratio workers |
| `_list_pending` | Discards stale list previews |
| `_img_in_flight` | Deduplicates full-image decodes by index |
| `_gallery_in_flight` | Tracks active gallery thumbnail decodes |
| `_prefetch_cache` | OrderedDict of predecoded neighboring images |

### 4.2 Full-image asynchronous flow

`load_image_async(n)`:

1. Cancels animation and slideshow timers.
2. Increments `_load_token`.
3. Updates `fileidx` via `_set_current(n)`.
4. Updates status.
5. If `n` is in `_prefetch_cache`, posts `_apply_async_result()` immediately.
6. Otherwise calls `_request_decode(n, callback)`.

`_request_decode(n, callback)`:

- If a future for `n` already exists in `_img_in_flight`, reuses it.
- Otherwise submits `load_frames(path, self._max_load_dim)` to `_img_executor`.
- Adds a done callback that posts `(n, frames, delays, error)` back to the main thread.

`_apply_async_result(token, n, frames, delays, err)`:

- Ignores if quitting, token mismatch, or invalid index.
- On error:
  - If `assume_files=True`, clears image and redraws.
  - Otherwise calls synchronous `load_image(self.fileidx)`, which may remove the bad file and try a neighbor.
- On success:
  - Calls `_install_image(n, frames, delays)`.
  - Persists index.
  - Redraws.
  - Calls `_prefetch_neighbors(n)`.

`_install_image()` sets:

- `img_frames`
- `img_delays`
- `img_sel = 0`
- `img_w`, `img_h`
- `img_multi_len`
- clears `FF_WARN`
- resets pan
- records mtime
- schedules animation if multi-frame and animation is on

### 4.3 Prefetch cache

After a successful full-image load, `_prefetch_neighbors(n)` finds the current position in `_visible_indices` and prefetches the previous and next visible images.

`_submit_prefetch(n)`:

- Skips if already cached or if `n == fileidx`.
- Captures `_files_gen`.
- Decodes via `_request_decode()`.
- On success, if generation still matches, stores `(frames, delays)` in `_prefetch_cache`.
- Evicts oldest entries beyond `PREFETCH_MAX` (3).

The cache is cleared on sort, remove, reload, or generation changes.

### 4.4 Gallery thumbnail asynchronous flow

`_submit_gallery_tile(i)`:

- Skips if the thumbnail already exists.
- Skips if already in `_gallery_in_flight`.
- Limits in-flight thumbnails to `THUMB_MAX_IN_FLIGHT` (12).
- Uses `self._tile_thumb_max = (tile_w - 5, tile_h - 5)`.
- Submits `load_gallery_thumb(path, tw, th)` to `_thumb_executor`.

When done, `_on_gallery_tile_ready(i, gen, pil)` runs on the main thread:

- Discards from `_gallery_in_flight`.
- Checks `_files_gen`.
- Creates `ImageTk.PhotoImage`.
- Stores `(photo, width, height)` in `self.tns_thumbs[i]`.
- Schedules a gallery redraw.

### 4.5 List preview asynchronous flow

`render_list()`:

- Ensures the current file is visible.
- Updates listbox selection.
- Sets `_list_pending = target`.
- Submits `load_frames(path, max(pw, ph))` to `_img_executor`.

`_apply_list_preview(idx, frames)`:

- Ignores if quitting, mode is not list, or `idx != _list_pending`.
- Uses `frames[0]`, copies it, thumbnails to the preview label size with `LANCZOS`.
- Stores the `PhotoImage` in `_list_photo` and updates the label.

---

## 5. Full-image viewer processing and rendering

### 5.1 Fit, zoom, and pan

`_fit()` computes `self.zoom` based on `self.scalemode`:

| Mode | Zoom |
|---|---|
| `SCALE_DOWN` | `min(win_w / img_w, win_h / img_h, 1.0)` |
| `SCALE_FIT` | `min(win_w / img_w, win_h / img_h)` |
| `SCALE_FILL` | `max(win_w / img_w, win_h / img_h)` |
| `SCALE_WIDTH` | `win_w / img_w` |
| `SCALE_HEIGHT` | `win_h / img_h` |
| `SCALE_ZOOM` | unchanged |

Zoom is clamped to `ZOOM_MAX` (8.0).

`_check_pan()`:

- If the scaled image is smaller than the window, centers it.
- Otherwise clamps `img_x` and `img_y` so edges do not leave gaps.

`_zoom_to(z)` zooms around the window center and sets `SCALE_ZOOM`.

### 5.2 Visible-region crop

`render_image()` avoids resizing the whole image. It computes the visible source rectangle:

```python
x0 = max(0.0, -self.img_x) / z
y0 = max(0.0, -self.img_y) / z
x1 = min(iw, (cw - self.img_x) / z)
y1 = min(ih, (ch - self.img_y) / z)
```

Then crops:

```python
cropped = frame.crop((ix0, iy0, ix1, iy1))
```

This means only the on-screen portion is processed.

### 5.3 Color adjustments and alpha

`_prepare_crop(im)`:

1. If mode is `RGBA`, pastes it over a solid background of `self.bg` and converts to `RGB`. This flattens transparency.
2. Converts unsupported modes to `RGB`.
3. Applies brightness if `self.brightness != 0`:
   - `_steps_to_range(brightness, BRIGHTNESS_MAX, 0.0)`
   - `ImageEnhance.Brightness(...).enhance(...)`
4. Applies contrast if `self.contrast != 0`:
   - `_steps_to_range(contrast, CONTRAST_MAX, 1.0)`
   - `ImageEnhance.Contrast(...).enhance(...)`
5. Applies gamma if `self.gamma != 0`:
   - Builds a 256-entry LUT.
   - `inv = 1.0 / max(0.01, g)`
   - For each intensity `i`: `min(255, int(255 * ((i / 255.0) ** inv + 0.5)))`
   - Applies with `im.point(lut)` for `L`, or `im.point(lut * 3)` for RGB.

`_steps_to_range()` maps discrete steps in `[-CC_STEPS, CC_STEPS]` to a value between an offset and a maximum.

The `alpha_layer` flag is toggled by `act_toggle_alpha()`, but `_prepare_crop()` does not consult it. In this version, RGBA images are always flattened for the viewer.

### 5.4 Resampling and canvas drawing

After cropping and color processing:

- Target size is computed from the cropped size and zoom:
  ```python
  dw = max(1, int((ix1 - ix0) * z + 0.5))
  dh = max(1, int((iy1 - iy0) * z + 0.5))
  ```
- Resampling filter:
  - `Image.BICUBIC` if `self.anti_alias`
  - `Image.NEAREST` otherwise
- `ImageTk.PhotoImage(resized)` is created.
- The canvas is cleared and the image is drawn at:
  ```python
  self.img_x + ix0 * z,
  self.img_y + iy0 * z
  ```
  with anchor `nw`.

The canvas scrollregion is set to `(0, 0, cw, ch)`.

### 5.5 Rotation, flip, animation, slideshow, auto-reload

- `act_rotate(degree)` rotates every frame with `Image.rotate(90 * degree, expand=True)` and updates `img_w`, `img_h`.
- `act_flip(direction)` transposes every frame with `FLIP_LEFT_RIGHT` or `FLIP_TOP_BOTTOM`.
- `act_toggle_animation()` toggles `img_animate`; if enabled, `animate()` advances `img_sel` and reschedules.
- `_schedule_animate()` uses the current frame’s delay in milliseconds.
- `act_slideshow()` toggles slideshow mode. `_schedule_slideshow()` sets a timer for `ss_delay * 100` ms. `slideshow_next()` advances to the next visible file.
- `_poll_autoreload()` runs every 500 ms. In image mode, it compares the current file’s mtime with `_mtimes[fileidx]`. If changed, it clears the prefetch entry and reloads asynchronously.

---

## 6. Gallery processing and rendering

### 6.1 Aspect-ratio detection

`_get_gallery_aspect()` returns tile width/height ratio:

- If `--gallery-aspect` was given, clamp it to `[GALLERY_ASPECT_MIN, GALLERY_ASPECT_MAX]` (0.4 to 3.0) and cache it.
- Otherwise, if no worker is pending:
  - Increments `_aspect_gen`.
  - Samples the first `GALLERY_ASPECT_SAMPLE` (20) files.
  - Starts a daemon thread.
  - The worker gets each file’s original size via `_get_orig_size()`, computes `w / h`, and posts `_finish_aspect()`.
- While waiting, returns `GALLERY_ASPECT_DEFAULT` (16:9).

`_finish_aspect()`:

- Checks generation.
- Sorts ratios and takes the median.
- Clamps to the allowed range.
- If the aspect changed:
  - Increments `_files_gen`.
  - Resets all thumbnails to `None`.
  - Clears `_gallery_in_flight`.
  - Redraws gallery if active.

### 6.2 Tile metrics

`_compute_tile_metrics()` calculates tile width, height, caption height, and padding.

If `--gallery-tile-size` is set, that long side is used directly.

Otherwise:

- `rows = _gallery_rows_opt or GALLERY_TARGET_ROWS` (3.5)
- `denom_v = 1.0 + GALLERY_CAPTION_RATIO + GALLERY_PAD_RATIO`
- `tile_h_from_rows = (win_h / rows) / denom_v`
- `tile_w_from_rows = tile_h_from_rows * aspect`
- If `--gallery-cols` is set:
  - `denom_h = 1.0 + GALLERY_PAD_RATIO`
  - `tile_w_from_cols = (win_w / cols) / denom_h`
  - `base_w = min(tile_w_from_rows, tile_w_from_cols)`
- Else `base_w = tile_w_from_rows`
- `base_h = base_w / aspect`

Then:

- Quantizes tile sizes to `GALLERY_SIZE_QUANTUM` (8).
- Clamps long side to `[GALLERY_TILE_MIN, GALLERY_TILE_MAX]` (96 to 512).
- Computes padding and caption height from ratios, with minimums.

`_update_tile_metrics()` updates `_tile_w`, `_tile_h`, `_tile_caption_h`, `_tile_pad`, and `_tile_thumb_max = (tile_w - 5, tile_h - 5)`.

### 6.3 Visible tile rendering and caption fitting

`render_gallery()`:

- If no visible files, draws `"No matches"`.
- Updates tile metrics.
- Computes columns:
  ```python
  cols = max(1, (win_w - pad) // (tile_w + pad))
  ```
- Computes total rows, total height, total width, and scrollregion.
- Applies any pending scroll to the current file.
- Determines visible rows using `y_top`, `y_bot`, and `GALLERY_OVERSCAN_ROWS` (2).
- Clears `_gallery_photos`.
- For each visible tile position:
  - Computes absolute file index.
  - Draws a border: accent + 3 px for current, hover border + 2 px otherwise.
  - If `tns_thumbs[abs_i]` exists, draws the image and appends the `PhotoImage` to `_gallery_photos` to prevent garbage collection.
  - Otherwise calls `_submit_gallery_tile(abs_i)`.
  - Draws a mark square if `FF_MARK` is set.
  - Fits the caption with `_fit_caption()` and draws it centered below the tile.

`_fit_caption()` wraps text to the tile width using monospace character metrics, limits to the available caption height, and adds an ellipsis `…` if truncated.

### 6.4 Scrolling and zoom

- `_gallery_scroll_by(dy)` adjusts `yview_moveto` and calls `render_gallery()`.
- `_apply_gallery_scroll(index)` ensures the selected tile is visible.
- `_gallery_zoom(d)` changes `_gallery_tile_override` by `GALLERY_ZOOM_STEP` (32), clamps to min/max, invalidates all thumbnails, and redraws.

Mouse wheel over the gallery scrolls by half a tile height.

---

## 7. List mode processing

`_populate_listbox()`:

- Deletes all listbox items.
- Inserts labels in chunks of `LISTBOX_INSERT_CHUNK` (1000).
- Applies marked-item colors only for marked files.
- Selects and scrolls to the current file.

`render_list()`:

- Ensures the current file is visible.
- Updates selection.
- Displays the filename.
- Shows `"Loading <name>…"`.
- Submits a full decode at `max(preview_width, preview_height)` to `_img_executor`.

`_apply_list_preview()`:

- Ignores stale results.
- Copies `frames[0]`.
- Thumbnails to the label size with `LANCZOS`.
- Stores `_list_photo` and updates the label.

List mode does not apply color adjustments; it is a preview only.

---

## 8. Mode transitions and navigation

The three modes are:

```python
MODE_IMAGE = 'i'
MODE_GALLERY = 'g'
MODE_LIST = 'l'
```

`Tab` / `Shift+Tab` cycles modes via `_cycle_mode()`.

- Entering image mode loads the current image asynchronously.
- Entering gallery mode resets animation/slideshow, sets `_pending_gallery_scroll`, and redraws.
- Entering list mode populates the listbox and redraws.

Navigation:

- `_nav_visible(delta)` moves through `_visible_indices`.
- In image mode, arrow keys pan; `Ctrl+N` / `Ctrl+P` navigate files.
- In gallery mode, left/right navigate by one, up/down by one row.
- In list mode, up/down navigate by one.
- PageUp/PageDown navigate by larger steps depending on mode.
- `Home` / `End` go to first/last visible.
- `Return`:
  - In selector mode, accepts and quits.
  - In list or gallery mode, enters image mode.
  - In image mode, enters gallery mode.
- `Esc` clears the filter if non-empty, else quits.
- `Delete` removes the current or marked files.

Mouse:

- Image mode: left third previous, right third next, right-click gallery, wheel zoom.
- Gallery mode: left-click selects, Ctrl+left or right-click toggles mark, wheel scrolls.
- List mode: left-click selects, right-click toggles mark.

---

## 9. Error handling and edge cases

- **Pillow missing:** exits with an error message.
- **pyvips missing:** warns and falls back to Pillow.
- **Truncated images:** allowed by `ImageFile.LOAD_TRUNCATED_IMAGES = True`.
- **Decode failure with vips:** silently falls back to Pillow.
- **Decode failure with both:** if `assume_files` is false, `load_image()` removes the bad file and tries the next or previous file. If `assume_files` is true, it shows an empty image.
- **No files:** viewer exits with an error; selector exits with `"No images found."`.
- **No display:** catches `tk.TclError` and exits.
- **Config errors:** any syntax error discards the entire config and uses defaults.
- **Stale async results:** discarded using tokens and generation counters.
- **Sorting during lazy scan:** applied after scan finishes.
- **Aspect cache invalidation:** happens when sorting, crossing the sample threshold during lazy scan, or changing tile zoom.

---

## 10. Key data structures and constants

### Data structures

| Structure | Meaning |
|---|---|
| `FileEntry` | `name`, `path`, `flags`, `label` |
| `self.files` | List of `FileEntry` |
| `self.tns_thumbs` | List of `(PhotoImage, w, h)` or `None` for gallery tiles |
| `self._visible_indices` | Indices of files matching the filter |
| `self._prefetch_cache` | `OrderedDict` of index → `(frames, delays)` |
| `self._img_in_flight` | Index → `Future` for full-image decodes |
| `self._gallery_in_flight` | Set of indices currently decoding thumbnails |
| `self._orig_sizes` | Path → `(width, height)` cache for aspect detection |
| `self._gallery_photos` | References to visible `PhotoImage` objects to prevent GC |
| `self._mtimes` | Index → mtime for auto-reload |
| `self._timeout_ids` | Named `after()` timer IDs |

### Relevant constants

| Constant | Value | Purpose |
|---|---|---|
| `MAX_LOAD_DIM` | 4096 | Max dimension for full image decode |
| `IMG_WORKERS` | 4 | Full-image decode threads |
| `THUMB_WORKERS` | 4 | Gallery thumbnail threads |
| `PREFETCH_MAX` | 3 | In-memory prefetch cache size |
| `THUMB_MAX_IN_FLIGHT` | 12 | Max concurrent gallery thumbnail decodes |
| `QUEUE_POLL_MS` | 20 | Main-thread queue polling interval |
| `FILTER_DEBOUNCE_MS` | 60 | Search filter debounce |
| `LAZY_BATCH_SIZE` | 128 | Files per lazy scan batch |
| `LISTBOX_INSERT_CHUNK` | 1000 | Listbox insertion chunk size |
| `GALLERY_TARGET_ROWS` | 3.5 | Default visible gallery rows |
| `GALLERY_TILE_MIN/MAX` | 96 / 512 | Tile long-side bounds |
| `GALLERY_ASPECT_SAMPLE` | 20 | Files sampled for aspect ratio |
| `GALLERY_ASPECT_DEFAULT` | 16/9 | Provisional aspect ratio |
| `ZOOM_LEVELS` | `[0.125 … 8.0]` | Viewer zoom steps |
| `DEF_ANIM_DELAY` | 75 | Default animation delay in ms |
| `CC_STEPS` | 32 | Color adjustment step range |
| `CACHE_WEBP_QUALITY` | 82 | Disk thumbnail WEBP quality |

---

## 11. Summary flows

### Viewer startup

```text
CLI args
  → run_viewer()
  → build_viewer_parser()
  → collect_dir() or start_lazy_scan()
  → FileEntry list
  → TkivApp(...)
  → _setup_ui()
  → _setup_bindings()
  → _initial_load()
  → load_image_async(fileidx)
  → _request_decode()
  → load_frames()
  → _apply_async_result()
  → _install_image()
  → render_image()
```

### Full image display

```text
render_image()
  → _fit()
  → _check_pan()
  → crop visible region
  → _prepare_crop()       # alpha flatten, brightness, contrast, gamma
  → resize (BICUBIC/NEAREST)
  → ImageTk.PhotoImage
  → Canvas.create_image()
```

### Gallery tile display

```text
render_gallery()
  → _update_tile_metrics()
  → compute visible rows
  → for each visible tile:
       if thumbnail missing:
           _submit_gallery_tile()
             → load_gallery_thumb()
             → _on_gallery_tile_ready()
             → tns_thumbs[i] = PhotoImage
       draw image, border, mark, caption
```

### Lazy scan

```text
start_lazy_scan()
  → worker thread
  → Path.glob()
  → filter IMAGE_EXTS
  → batch (128)
  → _post(_queue_lazy_files)
  → _commit_lazy_batch()
  → extend self.files
  → redraw
```

---

## 12. Notable observations

- `_decode_thumb()` and the disk WEBP cache are implemented but not used by `TkivApp` in this version.
- `alpha_layer` is toggled but not consulted during rendering; RGBA images are always flattened in `_prepare_crop()`.
- The viewer decodes full images at up to `MAX_LOAD_DIM` (4096) by default, so very large images are downscaled before display processing.
- Gallery thumbnails are decoded at tile size, not full size, and are only requested for visible tiles plus overscan.
- Prefetching is limited to the previous and next visible images and capped at three cached entries.
- All Tk updates happen on the main thread through `_post()` and `_poll_main_queue()`.
- Generation counters are the primary defense against stale asynchronous results after sorting, filtering, or file removal.
