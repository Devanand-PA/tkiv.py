# tkiv.py Source Code Documentation

`tkiv.py` is a combined image viewer and image selector written in Python with Tkinter. It has two main modes:

- `tkiv.py img [OPTIONS] FILES...` — an `nsxiv`-like image viewer.
- `tkiv.py select [OPTIONS] PATHS...` — a `dmenu`-like image selector.

The program uses Pillow for image loading and optionally uses `pyvips` + `numpy` for faster decoding and thumbnail generation. It supports gallery mode, list mode, filtering, sorting, marking, lazy directory scanning, configuration files, direct-key mode, slideshow, animation, color adjustments, and more.

---

## 1. Module docstring

The top-level docstring explains:

- Usage of `img` and `select` modes.
- Viewer keybindings.
- Direct-key mode, toggled with `F2` or `--no-searchbar`.
- Configuration file location and format:
  - `~/.config/tkiv.py/config`
  - or `$XDG_CONFIG_HOME/tkiv.py/config`
  - INI-like sections: `[keys]`, `[theme]`, `[behavior]`.

Any config syntax error causes the entire config to be discarded and defaults used.

---

## 2. Imports

### Standard library imports

- `argparse` — command-line argument parsing.
- `hashlib` — creates cache keys for thumbnail disk cache.
- `os` — filesystem and environment access.
- `queue` — thread-safe main-thread callback queue.
- `re` — regular expressions for config validation.
- `stat` — file type checks.
- `sys` — stdin/stdout/stderr and program exit.
- `threading` — background aspect-ratio detection and lazy scanning.
- `collections.OrderedDict` — prefetch cache with LRU behavior.
- `concurrent.futures.ThreadPoolExecutor` — image and thumbnail worker pools.
- `pathlib.Path` — path handling.

### Pillow imports

Pillow is required. The program exits with an error if it is missing.

Imported names:

- `Image`
- `ImageTk`
- `ImageOps`
- `ImageEnhance`
- `ImageFile`

`ImageFile.LOAD_TRUNCATED_IMAGES = True` allows loading partially corrupted images.

### Optional pyvips/numpy imports

The program tries to import:

- `pyvips`
- `numpy`

If successful, flags are set:

- `HAVE_VIPS = True`
- `HAS_VIPS = True`
- `HAS_NUMPY = True`

If not available, the program falls back to Pillow.

### Tkinter imports

Imports `tkinter as tk`, `tkinter.font`, and several widgets/constants.

---

## 3. Shared theme

`THEME` is a dictionary of default UI colors:

- `bg_primary`
- `bg_secondary`
- `bg_input`
- `fg_text`
- `fg_bright`
- `accent`
- `accent_fg`
- `selected_bg`
- `selected_fg`
- `hover_border`

Config file theme values override these at runtime.

---

## 4. Constants

### Program metadata

- `VERSION = "0.4.0"`
- `PROGNAME = "tkiv"`

### Scale modes

Used for image fitting:

- `SCALE_DOWN = 'd'`
- `SCALE_FIT = 'f'`
- `SCALE_FILL = 'F'`
- `SCALE_WIDTH = 'w'`
- `SCALE_HEIGHT = 'h'`
- `SCALE_ZOOM = 'z'`

### Zoom levels

- `ZOOM_LEVELS` — list of preset zoom factors.
- `ZOOM_MIN`, `ZOOM_MAX` — bounds.

### Timing and limits

- `SLIDESHOW_DELAY = 5`
- `DEF_ANIM_DELAY = 75`
- `CC_STEPS = 32`
- `GAMMA_MAX = 10.0`
- `BRIGHTNESS_MAX = 2.0`
- `CONTRAST_MAX = 4.0`

### Modes

- `MODE_IMAGE = 'i'`
- `MODE_GALLERY = 'g'`
- `MODE_LIST = 'l'`

### File flags

- `FF_MARK = 1` — marked file.
- `FF_WARN = 2` — warning flag, used internally.

### Directions, rotations, flips

- `DIR_LEFT`, `DIR_RIGHT`, `DIR_UP`, `DIR_DOWN`
- `DEGREE_90`, `DEGREE_180`, `DEGREE_270`
- `FLIP_HORIZONTAL`, `FLIP_VERTICAL`

### Sorting

- `SORT_NONE`
- `SORT_NAME`
- `SORT_MTIME`
- `SORT_SIZE`

### Image extensions

`IMAGE_EXTS` is a set of supported image file extensions.

### Performance and rendering constants

- `MAX_LOAD_DIM = 4096`
- `IMG_WORKERS = 4`
- `THUMB_WORKERS = 4`
- `PREFETCH_MAX = 3`
- `THUMB_MAX_IN_FLIGHT = 12`
- `QUEUE_POLL_MS = 20`
- `FILTER_DEBOUNCE_MS = 60`

### Lazy-scan tuning

- `LAZY_BATCH_SIZE = 128`
- `LISTBOX_INSERT_CHUNK = 1000`

### Gallery layout constants

- Tile size min/max.
- Target rows.
- Caption and padding ratios.
- Overscan rows.
- Zoom step.
- Aspect ratio defaults and limits.

### Selector-only constants

- `CACHE_SIZE = 800`
- `PRELOAD_AHEAD = 3`
- `DECODE_WORKERS`
- `DISK_CACHE_ENABLED = True`
- `CACHE_DIR`
- `CACHE_WEBP_QUALITY = 82`

---

## 5. Configuration file handling

### Paths

- `CONFIG_DIR`
- `CONFIG_FILE`

### Default key bindings

`DEFAULT_KEYS` maps action names to lists of human-friendly key specs. Examples:

- `quit`: `Ctrl+Q`
- `next`: `Ctrl+N`
- `prev`: `Ctrl+P`
- `fit`: `Ctrl+Shift+W`
- `toggle_searchbar`: `F2`

These are translated to Tkinter sequences at bind time.

### Default behavior

`DEFAULT_BEHAVIOR` contains configurable behavior values:

- `slideshow_delay`
- `max_load_dim`

### Validation helpers

- `_VALID_THEME_KEYS`
- `_HEX_COLOR_RE`
- `_MOD_ALIASES` — maps Ctrl/Control, Shift, Alt, Meta/Super/Cmd, etc.
- `_KEY_ALIASES` — maps human key names to Tk keysyms.

### Key-spec parsing

- `_split_key_spec(spec)` — splits `Ctrl+Shift+W` into parts, handling `Ctrl++`.
- `_parse_key_spec(spec)` — converts a human spec to a Tk sequence like `<Control-Shift-w>`.
- `_to_direct_key(tk_seq)` — converts a search-bar binding to a direct-key binding by stripping Ctrl/Alt/Meta and uppercasing Shifted letters.

### Config parsing

- `_validate_color(s)` — checks `#RRGGBB`.
- `_parse_config_text(text)` — parses INI-like config. Raises `ValueError` on any problem.
- `_get_config()` — loads config once, caches it, and returns empty defaults on error.

Config sections:

- `[keys]` — override or add bindings for known actions.
- `[theme]` — override theme colors.
- `[behavior]` — override `slideshow_delay` and `max_load_dim`.

---

## 6. Helper functions

### File and directory helpers

- `file_is_image(path)` — checks whether the extension is in `IMAGE_EXTS`.
- `collect_dir(d, recursive, include_hidden, sort_time=False)` — recursively or non-recursively collects image files from a directory, optionally sorting by modification time.

### pyvips conversion helpers

- `_vips_to_pil(vimg)` — converts a pyvips image to a Pillow image.
- `_vips_load_frames(path, max_dim=None)` — loads frames from an image using pyvips, including animated/multi-page images.
- `_pil_load_frames(path)` — Pillow fallback for loading frames.

### Unified image loaders

- `load_frames(path, max_dim=MAX_LOAD_DIM)` — tries pyvips first, then Pillow.
- `load_gallery_thumb(path, max_w, max_h)` — loads a gallery thumbnail, using pyvips if available.
- `_get_orig_size(path)` — returns image dimensions without fully decoding pixels if possible.
- `_disk_cache_path(path, w, h)` — computes a cache path for a thumbnail based on path, mtime, size, and requested dimensions.
- `_decode_thumb(path, max_w, max_h)` — decodes a thumbnail with optional disk cache. This helper is defined for thumbnail caching; in the current class flow, gallery thumbnails mainly use `load_gallery_thumb`.

---

## 7. Command-line interface

### Shared UI options

`_add_shared_ui_options(p, mode)` adds options shared by viewer and selector:

- `-g`, `-t`, `--gallery`, `--thumbnail`
- `-T`, `--gallery-tile-size`, `--thumb-size`
- `--gallery-rows`
- `--gallery-cols`
- `--gallery-aspect`
- `--lazy`
- `-r`, `--recursive`
- `-H`, `--hidden`
- `--time`
- `--sort`
- `-R`, `--sort-reverse`
- `-n`, `--start-at`, `--pass-idx`
- `--name`, `--custom-title`
- `--idx-write-path`
- `--pre-select`
- `--pre-select-file`
- `--no-searchbar`, `--no-search`, `--direct-keys`
- `-q`, `--quiet`
- `-v`, `--version`
- `-h`, `--help`

### Viewer parser

`build_viewer_parser()` adds viewer-specific options:

- animation, framerate
- assume files
- no bar / bar
- floating window
- clean cache
- embed
- fullscreen
- gamma
- geometry
- stdin
- legacy name
- class
- stdout
- private mode
- slideshow delay
- scale mode
- zoom
- zoom 100
- null separator
- anti-alias
- alpha layer
- cache allow/deny/update
- files

### Selector parser

`build_selector_parser()` adds selector-specific options:

- `--dmenu-mode`
- `--list-file`
- `--list-entries`
- `--image-file`
- `--image-entries`
- `--return-label`
- shared UI options
- `paths`

### Pre-select helper

`_read_pre_select(args)` reads pre-selected labels from `--pre-select` or `--pre-select-file`.

---

## 8. `FileEntry` class

A lightweight class representing one file/entry.

Slots:

- `name`
- `path`
- `flags`
- `label`

Constructor:

- `__init__(path, label=None)` — sets path, name, flags to 0, and label to basename by default.

---

## 9. `TkivApp` class

The main application class. It handles both viewer and selector modes.

### 9.1 `__init__`

Initializes the whole app:

- Stores `purpose`, `root`, `opts`, `no_searchbar`.
- Loads config and applies key bindings, behavior, theme.
- Copies file list.
- Sets initial index, mode, marks, alternate index.
- Initializes timeout tracking, mtimes, resize state, quit state.
- Initializes lazy scan state.
- Initializes filtering state.
- Creates image and thumbnail thread pools.
- Creates main-thread queue and load tokens.
- Initializes image state:
  - frames
  - delays
  - selected frame
  - animation flag
  - dimensions
  - zoom
  - scale mode
  - pan position
  - gamma, brightness, contrast
  - anti-alias, alpha layer
- Initializes sorting state.
- Initializes slideshow state.
- Initializes gallery state:
  - thumbnails
  - in-flight thumbnails
  - tile dimensions
  - aspect ratio cache
  - scroll state
- Initializes list state.
- Applies pre-selection.
- Calls `_setup_ui()`, `_setup_bindings()`, optional sort, index persistence, and schedules initial load, autoreload polling, and main queue polling.

### 9.2 Pre-select

- `_apply_pre_select(labels)` — marks files whose labels match the given labels.

### 9.3 UI setup

- `_setup_ui()` — creates:
  - root window geometry, title, background
  - special behavior for selector/floating window
  - fonts and bar dimensions
  - content frame
  - image canvas
  - gallery frame/canvas/scrollbar
  - list frame, listbox, preview label, filename label
  - status bar
  - search entry
  - initial layout and content display
  - initial window size and image reference

- `_relayout_bars()` — packs/unpacks content, status bar, and search bar depending on `show_bar` and `no_searchbar`.

- `_show_content()` — shows the correct content widget for image, gallery, or list mode.

### 9.4 Bindings

- `_mk_break(fn)` — wraps a callback so it returns `"break"` and reports exceptions.
- `_setup_bindings()` — calls static and configurable binding setup.
- `_setup_static_bindings()` — binds mouse buttons, configure events, and window close.
- `_action_fns()` — maps action names from config to zero-argument callables.
- `_setup_key_bindings()` — clears old bindings and binds:
  - navigation keys
  - mode/accept/cancel keys
  - configurable actions
  - Ctrl+Enter mark toggle in search-bar mode
  - root key forwarding to search entry
- `_on_root_key(event)` — if search bar is enabled and not focused, focuses it and forwards printable characters.
- `act_toggle_searchbar()` — toggles between search-bar mode and direct-key mode.

### 9.5 Filtering

- `_on_search_change(*args)` — updates filter text, rebuilds visible indices, and schedules UI update.
- `_apply_filter_ui()` — ensures current index is visible and redraws gallery/list/image info.
- `_rebuild_visible()` — computes `_visible_indices` based on filter terms.
- `_initial_load()` — loads image, gallery, or list depending on initial mode.

### 9.6 Lazy scan

- `start_lazy_scan(paths, recursive=False, sort_time=False)` — starts a background thread that scans paths and queues file batches.
- `_queue_lazy_files(paths)` — appends files to pending lazy list and schedules commit.
- `_commit_lazy_batch()` — merges pending files into `self.files`, updates thumbnails, visible indices, aspect cache, and redraws.
- `_schedule_lazy_redraw()` — schedules a redraw after idle.
- `_do_lazy_redraw()` — redraws current mode after lazy files arrive.
- `_lazy_scan_finished()` — finalizes lazy scan, applies sort if needed, and redraws.

### 9.7 Main-thread queue

- `_post(fn)` — puts a callback into the main queue.
- `_poll_main_queue()` — processes queued callbacks on the Tk main thread.

### 9.8 Timeouts

- `set_timeout(name, delay_ms, callback, overwrite=False)` — schedules or replaces a named timeout.
- `_run_timeout(name, cb)` — runs a timeout callback.
- `reset_timeout(name)` — cancels a named timeout.

### 9.9 Sorting

- `_sort_keyfunc(mode)` — returns a sort key function for name, mtime, or size.
- `_apply_sort(mode=None, reverse=None, refresh=True)` — sorts files and thumbnails, keeps current file selected, invalidates caches, rebuilds visible indices, and refreshes.
- `_sort_label()` — returns a short sort indicator for the status bar.
- `act_sort_cycle()` — cycles through sort modes and directions.
- `act_sort_reverse()` — reverses sort direction.

### 9.10 File removal

- `remove_file(n, manual)` — removes a file from the list, adjusts indices, invalidates caches, rebuilds visible indices, and persists index.

### 9.11 Image loading

- `_set_current(n)` — changes current index and remembers previous index.
- `_persist_index()` — writes current index to `--idx-write-path`.
- `_install_image(n, frames, delays)` — installs loaded frames into app state.
- `load_image(n)` — synchronous image load, with fallback removal on failure.
- `load_image_async(n)` — asynchronous image load with token checking and prefetch cache.
- `_apply_async_result(token, n, frames, delays, err)` — installs async image result if still current.
- `_request_decode(n, callback)` — submits decode job to image executor, coalescing duplicate requests.
- `_prefetch_neighbors(n)` — prefetches previous/next visible images.
- `_submit_prefetch(n)` — submits prefetch decode if not already cached.
- `_schedule_animate()` — schedules next animation frame.
- `animate()` — advances animation frame and redraws.

### 9.12 Render dispatch

- `redraw()` — dispatches to `render_image`, `render_gallery`, or `render_list`, then updates info.

### 9.13 Image rendering

- `_steps_to_range(d, mx, offset)` — maps adjustment steps to a numeric range.
- `_prepare_crop(im)` — flattens RGBA, applies brightness/contrast/gamma.
- `_fit()` — computes zoom based on scale mode and window size.
- `_check_pan()` — clamps pan offsets.
- `render_image()` — crops, adjusts, resizes, and draws the current image frame on the canvas.

### 9.14 Gallery aspect detection

- `_get_gallery_aspect()` — returns tile aspect ratio. Uses CLI option or samples first images off-thread.
- `_finish_aspect(ratios, gen)` — completes aspect detection, invalidates thumbnails if aspect changed, and redraws.

### 9.15 Gallery rendering

- `_compute_tile_metrics()` — computes tile width, height, caption height, and padding.
- `_update_tile_metrics()` — updates metrics if changed.
- `_compute_gallery_cols()` — computes number of columns.
- `_fit_caption(label, max_w, max_h)` — wraps/truncates captions.
- `_submit_gallery_tile(i)` — requests a thumbnail decode.
- `_on_gallery_tile_ready(i, gen, pil)` — installs decoded thumbnail and schedules redraw.
- `_schedule_gallery_redraw()` — schedules gallery redraw.
- `_do_gallery_redraw()` — redraws gallery if still in gallery mode.
- `_apply_gallery_scroll(index)` — scrolls gallery to make an index visible.
- `render_gallery()` — draws visible gallery tiles, borders, marks, and captions.
- `_gallery_hit(event_x, event_y)` — maps mouse coordinates to a file index.
- `_gallery_scroll_by(dy)` — scrolls gallery vertically.
- `_gallery_zoom(d)` — changes gallery tile size.
- `_on_gallery_configure(event=None)` — handles gallery resize.
- `_on_gallery_mousewheel(event=None)` — handles mouse wheel scrolling.

### 9.16 List rendering

- `_populate_listbox()` — fills listbox with visible labels and highlights marks.
- `_on_listbox_select(event=None)` — handles listbox selection.
- `render_list()` — updates list preview and filename, and requests preview decode.
- `_apply_list_preview(idx, frames)` — installs decoded list preview.

### 9.17 Status info

- `update_info()` — builds and sets the status bar text, including marks, position, sort, zoom, gamma, brightness, contrast, animation frame, etc.

### 9.18 Quit and output

- `_emit_output(use_labels)` — prints marked files, or current file if none marked, to stdout.
- `quit(status=0)` — emits output if appropriate, shuts down executors, destroys root, and exits.

### 9.19 Navigation

- `_navigate(n)` — navigates to an absolute file index.
- `_nav_visible(delta)` — navigates by delta within visible indices.
- `_key_next()` — next visible file.
- `_key_prev()` — previous visible file.
- `_key_nav(direction)` — arrow-key navigation, mode-dependent.
- `_key_page(direction)` — PageUp/PageDown navigation.
- `_key_return()` — accepts in selector or switches mode in viewer.
- `_key_escape()` — clears filter or quits.
- `_key_delete()` — removes current/marked files.
- `_key_zoom_100()` — sets 100% zoom.
- `_cycle_mode(direction)` — cycles image → gallery → list.
- `_enter_image_mode()` — switches to image mode.
- `_enter_gallery_mode()` — switches to gallery mode.
- `_enter_list_mode()` — switches to list mode.

### 9.20 Actions

- `act_first()` / `act_last()` — go to first/last visible file.
- `act_toggle_fullscreen()` — toggles fullscreen.
- `act_toggle_bar()` — toggles status bar.
- `_refresh_size()` — refreshes cached window size and redraws.
- `act_reload()` — reloads current image or thumbnail.
- `act_remove()` — removes marked files, or current file.
- `_mark(n, on)` — marks/unmarks a file.
- `act_toggle_mark()` — toggles mark on current file.
- `act_unmark_all()` — clears all marks.
- `act_gamma(d)` / `act_brightness(d)` / `act_contrast(d)` — adjust image color settings.
- `_zoom_to(z)` — zooms to a specific factor around the center.
- `act_zoom(d)` — zooms in/out, or changes gallery tile size.
- `_pan(dx, dy)` — pans image.
- `act_scroll(direction, screen=False)` — scrolls image.
- `act_scroll_center()` — centers image.
- `act_fit(mode)` — sets scale mode.
- `act_rotate(degree)` — rotates image frames.
- `act_flip(direction)` — flips image frames.
- `act_toggle_antialias()` — toggles interpolation.
- `act_toggle_alpha()` — toggles alpha layer.
- `act_slideshow()` — toggles slideshow.
- `_schedule_slideshow()` — schedules next slideshow step.
- `slideshow_next()` — advances slideshow.
- `act_toggle_animation()` — toggles animation.
- `act_navigate(d)` — navigates by delta in image mode.

### 9.21 Mouse handling

- `on_button(event, button)` — handles mouse clicks in image, gallery, and list modes:
  - Image: left/right zones navigate, right click enters gallery, wheel zooms.
  - Gallery: left selects, Ctrl+left marks in selector, right marks, wheel scrolls.
  - List: left selects, right marks.

### 9.22 Window resize and autoreload

- `on_configure(event)` — updates window size and schedules resize handling.
- `_do_resize()` — refreshes size and redraws.
- `_poll_autoreload()` — periodically checks whether the current file changed on disk and reloads it if so.

---

## 10. Entry points

### `run_viewer()`

- Parses viewer arguments.
- Handles `--help` and `--version`.
- Applies legacy name/class behavior.
- Warns if pyvips is unavailable.
- Reads file list from stdin if requested.
- Collects files from arguments or directories.
- Handles lazy scan paths.
- Creates `Tk` root and `TkivApp` in `view` mode.
- Starts lazy scan if needed.
- Runs the Tk main loop.

### `run_selector()`

- Parses selector arguments.
- Handles `--help` and `--version`.
- Warns if pyvips is unavailable.
- Handles dmenu mode:
  - reads list entries and image entries
  - validates equal lengths
  - creates `FileEntry` objects with labels and paths
- Otherwise collects image paths from directories/files.
- Creates `Tk` root and `TkivApp` in `select` mode.
- Starts lazy scan if needed.
- Runs the Tk main loop.

### `main()`

- Dispatches based on first argument:
  - `img`, `view`, `viewer`, `pysxiv` → `run_viewer()`
  - `select`, `sel`, `selector`, `sel_img` → `run_selector()`
- Prints usage for unknown/missing mode.

### `if __name__ == '__main__'`

Runs `main()` and exits with its return code.

---

## 11. Keybinding summary

Default configurable actions include:

| Action | Default binding |
|---|---|
| quit | Ctrl+Q |
| toggle_bar | Ctrl+B |
| remove | Ctrl+D |
| fit_width | Ctrl+E |
| fullscreen | Ctrl+F |
| first | Ctrl+G |
| pan_left | Ctrl+H |
| toggle_antialias | Ctrl+I |
| pan_down | Ctrl+J |
| pan_up | Ctrl+K |
| pan_right | Ctrl+L |
| toggle_mark | Ctrl+M |
| next | Ctrl+N |
| prev | Ctrl+P |
| reload | Ctrl+R |
| slideshow | Ctrl+S |
| unmark_all | Ctrl+U |
| fit_down | Ctrl+W |
| sort_cycle | Ctrl+Y |
| center | Ctrl+Z |
| animate | Ctrl+Space |
| zoom_100 | Ctrl+0 |
| zoom_in | Ctrl+Plus |
| zoom_out | Ctrl+Minus |
| nav_10_forward | Ctrl+BracketRight |
| nav_10_back | Ctrl+BracketLeft |
| gamma_down | Ctrl+BraceLeft |
| gamma_up | Ctrl+BraceRight |
| contrast_down | Ctrl+ParenLeft |
| contrast_up | Ctrl+ParenRight |
| rotate_left | Ctrl+Less |
| rotate_right | Ctrl+Greater |
| rotate_180 | Ctrl+Question |
| flip_h | Ctrl+Bar |
| flip_v | Ctrl+Underscore |
| fit | Ctrl+Shift+W |
| fill | Ctrl+Shift+F |
| fit_height | Ctrl+Shift+E |
| toggle_alpha | Ctrl+Shift+I |
| sort_reverse | Ctrl+Shift+Y |
| toggle_searchbar | F2 |

Navigation keys such as arrows, Tab, Shift+Tab, Return, Escape, Delete, PageUp, PageDown, Home, and End are bound directly and are not configurable.

---

## 12. Config file example

```ini
[keys]
next = Ctrl+N
next = Space
prev = Ctrl+P

[theme]
bg_primary = #2e3440
accent = #88c0d0

[behavior]
slideshow_delay = 5
max_load_dim = 4096
```

Any invalid section, action, key sequence, theme key, color, or behavior value causes the whole config to be ignored and defaults used.

---

## 13. Summary

`tkiv.py` is organized into:

1. Shared constants and theme.
2. Config parsing and keybinding translation.
3. Image loading helpers with optional pyvips acceleration.
4. CLI parsers for viewer and selector modes.
5. A unified `TkivApp` class that handles:
   - UI construction
   - image, gallery, and list rendering
   - asynchronous loading and prefetching
   - filtering, sorting, marking, and navigation
   - slideshow and animation
   - color adjustments, zoom, pan, rotate, and flip
   - lazy directory scanning
   - selector output
6. Entry-point functions and a mode dispatcher.

The design keeps all UI work on the Tk main thread while image decoding and directory scanning run in background threads. Callbacks are returned to the main thread through a queue, and load tokens/generations prevent stale async results from being applied.
