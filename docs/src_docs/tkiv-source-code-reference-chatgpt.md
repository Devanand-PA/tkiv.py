# tkiv.py --- Source Code Reference

**Source version:** `0.4.0`\
**Source file:** `tkiv(2).py`\
**Purpose:** combined Tkinter image viewer and image
selector/dmenu-style application.

This document explains the source code by subsystem and then gives a
source-order map of the functions and methods. It describes what the
code actually does rather than treating every parsed command-line option
as necessarily functional.

------------------------------------------------------------------------

## 1. Overall architecture

`tkiv.py` is organized as one Python module with four broad layers:

``` text
command line
    │
    ├── img mode ───────┐
    └── select mode ────┤
                        ▼
                  TkivApp
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
    image mode      gallery mode      list mode
        │               │                │
        └───────────────┼────────────────┘
                        ▼
              asynchronous image loading
                        │
                 Pillow / pyvips
                        │
                  Tkinter display
```

The program deliberately shares almost all UI and interaction code
between the viewer and selector. The distinction is carried by:

-   `purpose='view'` or `purpose='select'`
-   the command-line options passed to `TkivApp`
-   selector-specific output behavior
-   a few mouse/Return/marking differences.

There are three visual modes inside the application:

-   **image mode** --- one image at a time
-   **gallery mode** --- tiled thumbnails
-   **list mode** --- filename list plus image preview

The same `TkivApp` instance can switch between these modes.

------------------------------------------------------------------------

# 2. Module header and imports

## 2.1 Shebang and module documentation

The file starts with:

``` python
#!/usr/bin/env python3
```

This permits the script to be executed directly on Unix-like systems
when marked executable.

The module docstring documents:

-   the two command-line entry modes (`img` and `select`)
-   default viewer key bindings
-   direct-key mode
-   configuration-file location
-   configuration sections.

The docstring is therefore also a compact user-facing description of the
program.

## 2.2 Standard-library imports

The module imports:

  Module                 Role
  ---------------------- ----------------------------------------------------------
  `argparse`             command-line parsing
  `hashlib`              thumbnail cache key generation
  `os`                   paths, files, environment variables, filesystem metadata
  `queue`                worker-thread → Tkinter main-thread communication
  `re`                   configuration/color validation
  `stat`                 checking filesystem entry types
  `sys`                  command-line arguments, stdin/stdout/stderr, exit status
  `threading`            background scanning/aspect detection
  `OrderedDict`          bounded-ish in-memory prefetch cache
  `ThreadPoolExecutor`   asynchronous image and thumbnail workers
  `Path`                 filesystem/path handling

Tkinter itself supplies the GUI.

## 2.3 Pillow

The program requires Pillow:

``` python
from PIL import Image, ImageTk, ImageOps, ImageEnhance, ImageFile
```

If Pillow cannot be imported, the program prints an error and exits.

`ImageFile.LOAD_TRUNCATED_IMAGES = True` tells Pillow to tolerate
truncated image files where possible.

## 2.4 Optional pyvips and NumPy

`pyvips` and `numpy` are optional.

If both imports succeed, the source enables accelerated image paths:

``` python
HAVE_VIPS = True
HAS_VIPS = True
HAS_NUMPY = True
```

Otherwise the names are set to `None`/`False` and Pillow is used as
fallback.

The source therefore has this image-processing hierarchy:

``` text
pyvips available
      │
      ├── yes → use pyvips where implemented
      │
      └── no  → Pillow
```

Some thumbnail paths specifically require both pyvips and NumPy before
using the NumPy conversion path.

------------------------------------------------------------------------

# 3. Global theme

`THEME` is a mutable dictionary containing the application's colors.

``` python
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
```

The configuration loader can replace these values before
`TkivApp._setup_ui()` creates widgets.

The important architectural detail is that this is a **global mutable
theme**, rather than a theme object passed into each widget.

------------------------------------------------------------------------

# 4. Constants

The next section defines the application's internal vocabulary.

## 4.1 Program identity

``` python
VERSION = "0.4.0"
PROGNAME = "tkiv"
```

These are used by help/version output and error messages.

## 4.2 Scaling modes

``` text
SCALE_DOWN   = d
SCALE_FIT    = f
SCALE_FILL   = F
SCALE_WIDTH  = w
SCALE_HEIGHT = h
SCALE_ZOOM   = z
```

These describe how an image is fitted to the image canvas.

## 4.3 Zoom levels

`ZOOM_LEVELS` contains the discrete zoom sequence:

``` text
12.5%, 25%, 50%, 75%, 100%, 150%, 200%, 400%, 800%
```

`ZOOM_MIN` and `ZOOM_MAX` are derived from it.

## 4.4 Image-adjustment constants

-   `SLIDESHOW_DELAY` --- default slideshow delay
-   `DEF_ANIM_DELAY` --- fallback animation-frame delay
-   `CC_STEPS` --- number of adjustment steps
-   `GAMMA_MAX` --- gamma upper bound
-   `BRIGHTNESS_MAX` --- brightness upper bound
-   `CONTRAST_MAX` --- contrast upper bound.

## 4.5 Application modes

``` text
MODE_IMAGE   = 'i'
MODE_GALLERY = 'g'
MODE_LIST    = 'l'
```

These are used throughout `TkivApp.mode`.

## 4.6 File flags

``` text
FF_MARK = 1
FF_WARN = 2
```

`FF_MARK` is used to mark files for selection/removal. `FF_WARN` is
defined as another bit flag.

## 4.7 Navigation/transformation constants

The direction constants represent:

-   left
-   right
-   up
-   down.

Rotation constants represent 90°, 180°, and 270°.

Flip constants represent horizontal and vertical flips.

## 4.8 Sorting constants

``` text
SORT_NONE
SORT_NAME
SORT_MTIME
SORT_SIZE
```

These are the internal representation of the sorting modes.

## 4.9 Image extensions

`IMAGE_EXTS` is the extension allow-list. It includes common formats
such as:

-   JPEG/JPG
-   PNG
-   GIF
-   BMP
-   TIFF
-   WebP
-   PPM/PGM/PBM/PNM
-   ICO
-   PCX
-   TGA
-   XPM
-   JPEG 2000
-   AVIF
-   HEIC/HEIF.

This is extension-based filtering; actual decoding is performed later by
Pillow or pyvips.

## 4.10 Threading/performance constants

The source uses separate executors for full images and gallery
thumbnails:

``` text
IMG_WORKERS         = 4
THUMB_WORKERS       = 4
```

Other constants limit asynchronous work:

``` text
PREFETCH_MAX
THUMB_MAX_IN_FLIGHT
QUEUE_POLL_MS
FILTER_DEBOUNCE_MS
```

Lazy scanning has separate batching constants:

``` text
LAZY_BATCH_SIZE
LISTBOX_INSERT_CHUNK
```

These are source-level tuning parameters, not configuration-file
options.

## 4.11 Gallery layout constants

The gallery has source-level defaults for:

-   minimum/maximum tile size
-   target number of visible rows
-   caption height ratio/minimum
-   tile padding
-   size quantization
-   overscan rows
-   keyboard zoom step
-   default aspect ratio
-   allowed aspect-ratio range
-   number of images sampled for automatic aspect detection.

This is why gallery geometry changes automatically when the window is
resized.

## 4.12 Thumbnail cache constants

The selector/gallery thumbnail system also defines:

-   memory cache size
-   number of images to preload
-   decode worker count
-   disk-cache enablement
-   cache directory
-   WebP cache quality.

The disk cache is based on a hash of the file path, modification
timestamp, file size, and requested thumbnail dimensions.

------------------------------------------------------------------------

# 5. Configuration subsystem

Configuration occupies approximately lines 185--486.

## 5.1 Configuration location

The source constructs:

``` text
$XDG_CONFIG_HOME/tkiv.py/config
```

or, when `XDG_CONFIG_HOME` is not set:

``` text
~/.config/tkiv.py/config
```

## 5.2 Default key map

`DEFAULT_KEYS` maps logical action names to human-readable key
specifications.

For example:

``` python
'next': ['Ctrl+N']
```

An action maps to a **list**, so an action can have multiple bindings.

The map includes navigation, display, transformations, sorting,
slideshow, animation, marking, and search-bar actions.

## 5.3 Default behavior map

`DEFAULT_BEHAVIOR` currently exposes two configuration values:

-   `slideshow_delay`
-   `max_load_dim`

Other source constants remain hard-coded.

## 5.4 Modifier aliases

`_MOD_ALIASES` converts user-friendly names into Tk modifier names.

For example:

``` text
Ctrl / Control → Control
Meta / Cmd / Super / Command → Meta
```

Shift and Alt are also recognized.

## 5.5 Key aliases

`_KEY_ALIASES` maps names such as:

``` text
Return / Enter
Escape / Esc
PageUp / PgUp / Prior
PageDown / PgDn / Next
BracketLeft / [
BracketRight / ]
BraceLeft / {
BraceRight / }
```

and keypad/function-key names to Tk keysyms.

This lets the config file use readable names instead of raw Tk syntax.

------------------------------------------------------------------------

# 6. Configuration parsing functions

## `_split_key_spec()` --- lines 311--330

Splits a specification such as:

``` text
Ctrl+Shift+W
```

into components.

It has special handling for `+` as an actual key, allowing forms such as
`Ctrl++`.

It is the lexical stage of key parsing.

## `_parse_key_spec()` --- lines 333--365

Converts the human-readable representation into a Tk event sequence.

Example:

``` text
Ctrl+Shift+W
```

becomes approximately:

``` text
<Control-Shift-w>
```

The function rejects invalid specifications such as:

-   no key
-   more than one non-modifier key
-   unknown multi-character key names.

It returns `None` on invalid input.

## `_to_direct_key()` --- lines 368--387

Converts a normal binding into the equivalent binding used by direct-key
mode.

For example:

``` text
<Control-n>
```

becomes:

``` text
<n>
```

and:

``` text
<Control-Shift-w>
```

becomes:

``` text
<W>
```

Control, Alt, and Meta are removed while Shift is preserved.

## `_validate_color()` --- lines 390--391

Checks whether a theme color is exactly a six-digit hexadecimal color:

``` text
#RRGGBB
```

## `_parse_config_text()` --- lines 394--453

Parses the custom INI-like configuration format.

Recognized sections are exactly:

``` text
[keys]
[theme]
[behavior]
```

It validates:

-   section names
-   action names
-   key specifications
-   theme keys
-   colors
-   behavior names
-   positive integer behavior values.

Multiple entries for the same key action are appended to the action's
binding list.

A malformed line raises `ValueError`.

## `_get_config()` --- lines 459--486

Loads and caches configuration.

Important behavior:

1.  It only reads the configuration once per process.
2.  A missing file means defaults.
3.  A read error means defaults.
4.  A syntax/validation error means **the entire configuration is
    discarded**.
5.  A valid file is stored in `_CONFIG_CACHE`.

This is why one invalid configuration entry can cause otherwise valid
settings to be ignored.

------------------------------------------------------------------------

# 7. Filesystem and image-loading helpers

## `file_is_image()` --- lines 490--491

Tests a path's lowercase extension against `IMAGE_EXTS`.

## `collect_dir()` --- lines 494--524

Scans a directory and returns image files.

Behavior:

-   skips hidden entries unless requested
-   recognizes regular files with supported extensions
-   optionally descends recursively
-   optionally sorts by modification time
-   ignores filesystem errors.

It is used by both viewer and selector startup.

------------------------------------------------------------------------

# 8. Image decoding helpers

## `_vips_to_pil()` --- lines 527--546

Converts a pyvips image to a Pillow image.

It handles:

-   grayscale
-   grayscale + alpha
-   RGB
-   RGBA
-   images with more than four bands.

It also ensures the NumPy array is contiguous before constructing a
Pillow image.

## `_vips_load_frames()` --- lines 549--603

Loads an image using pyvips.

It attempts to handle multi-page/multi-frame images and extracts frame
delays.

For very large images, it can scale the loaded image down so its largest
dimension does not exceed the configured maximum.

## `_pil_load_frames()` --- lines 606--628

Pillow fallback for image loading.

For animated images it:

1.  seeks through each frame
2.  converts frames to RGBA
3.  obtains the frame duration.

For ordinary images it returns one frame.

## `load_frames()` --- lines 631--637

Public decoder wrapper.

It tries pyvips first when available and falls back to Pillow if pyvips
fails.

This isolates the rest of the application from decoder choice.

## `load_gallery_thumb()` --- lines 640--652

Creates a gallery thumbnail.

It prefers pyvips and falls back to Pillow's `thumbnail()` method.

The result is converted to RGBA for consistent Tkinter display.

## `_get_orig_size()` --- lines 655--667

Obtains image dimensions without intentionally decoding the full pixel
data.

It tries pyvips first and Pillow second.

This is important for automatic gallery aspect-ratio detection.

## `_disk_cache_path()` --- lines 670--678

Generates the disk-cache filename.

The cache key incorporates:

``` text
path
modification time
file size
requested width
requested height
```

A SHA-1 digest becomes the filename.

The cache therefore changes when the source file changes.

## `_decode_thumb()` --- lines 681--743

This is the main optimized thumbnail decoder.

Its sequence is:

``` text
get original dimensions
       │
check disk cache
       │
       ├── hit → load cached WebP
       │
       └── miss
             │
             ├── pyvips + NumPy path
             │
             └── Pillow fallback
                    │
                    ▼
              optionally save WebP cache
```

The Pillow path also attempts to reduce decoding work for very large
images.

------------------------------------------------------------------------

# 9. Command-line parser construction

## `_add_shared_ui_options()` --- lines 747--792

Adds options shared by viewer and selector.

These include:

-   gallery startup
-   tile size
-   gallery rows/columns/aspect
-   lazy scanning
-   recursive scanning
-   hidden files
-   time sorting
-   generic sorting
-   reverse sorting
-   starting index
-   window title
-   index debug output
-   pre-selection
-   direct-key mode
-   quiet mode
-   version/help.

This function avoids duplicating the same argument definitions in two
parsers.

## `build_viewer_parser()` --- lines 795--830

Builds the `img` parser.

Viewer-specific options include:

-   animation
-   framerate
-   assume-files
-   status-bar control
-   floating window
-   fullscreen
-   gamma
-   geometry
-   stdin
-   legacy title/class options
-   stdout
-   private mode
-   slideshow delay
-   scale mode
-   zoom
-   null-delimited stdin
-   anti-alias
-   alpha layer
-   cache-related options.

Some of these are parsed for compatibility but are not subsequently used
by the current source.

## `build_selector_parser()` --- lines 833--847

Builds the `select` parser.

Selector-specific options are the dmenu-style inputs:

-   list entries/file
-   image entries/file
-   return-label.

Shared UI options are then added.

## `_read_pre_select()` --- lines 850--863

Loads pre-selected labels either from:

``` text
--pre-select
```

or:

``` text
--pre-select-file
```

It rejects using both simultaneously.

------------------------------------------------------------------------

# 10. `FileEntry`

`FileEntry` is the small data object used throughout the application.

Source lines: **867--873**.

It stores:

  Field     Meaning
  --------- -----------------------------
  `name`    original path/name value
  `path`    image path
  `flags`   bit flags such as `FF_MARK`
  `label`   displayed/searchable label

When no explicit label is provided, the basename of the path is used.

This same object therefore works for both ordinary image files and
dmenu-mode entries where a label and image path are separate.

------------------------------------------------------------------------

# 11. `TkivApp`

`TkivApp` spans approximately **lines 877--3155** and contains nearly
all runtime behavior.

It can be viewed as several cooperating subsystems:

``` text
TkivApp
├── initialization/configuration
├── Tkinter UI
├── keyboard bindings
├── filtering
├── lazy scanning
├── main-thread scheduling
├── sorting
├── image loading/prefetch
├── image rendering
├── gallery rendering
├── list rendering
├── selection/output
├── navigation
├── mode switching
├── image manipulation
├── slideshow/animation
└── mouse/window events
```

------------------------------------------------------------------------

# 12. `TkivApp.__init__()` --- lines 880--1029

The constructor establishes the entire application state.

## Configuration

It:

1.  loads the configuration
2.  starts with `DEFAULT_KEYS`
3.  applies configured key overrides
4.  starts with `DEFAULT_BEHAVIOR`
5.  applies configured behavior overrides
6.  applies theme overrides.

## File state

It stores the initial `FileEntry` list and calculates the starting
index.

## Mode state

The initial mode is:

-   gallery if `thumb_mode` is enabled
-   image otherwise.

## Asynchronous infrastructure

It creates:

-   image executor
-   thumbnail executor
-   main-thread queue
-   load tokens/generation counters
-   image-in-flight tracking
-   prefetch cache.

The use of a queue is important because Tkinter UI operations are kept
on the GUI thread.

## Image state

It initializes:

-   frames
-   animation state
-   dimensions
-   zoom
-   scaling mode
-   position
-   gamma
-   brightness
-   contrast
-   antialiasing
-   alpha-layer display.

## Sorting state

It converts the CLI sort option to one of the internal sort constants.

## Slideshow state

It derives the slideshow delay from either CLI configuration or the
persistent behavior setting.

## Gallery state

It initializes thumbnail arrays, gallery sizing options, tile
dimensions, and aspect-ratio detection state.

## Preselection

If preselected labels were provided, `_apply_pre_select()` marks
matching entries.

Finally it:

1.  creates the UI
2.  installs bindings
3.  applies initial sorting
4.  persists the starting index
5.  schedules initial loading
6.  starts periodic auto-reload polling
7.  starts polling the worker-result queue.

------------------------------------------------------------------------

# 13. UI construction

## `_apply_pre_select()` --- lines 1032--1038

Marks the first matching occurrence of each requested label.

## `_setup_ui()` --- lines 1041--1163

Builds all Tkinter widgets.

The major widgets are:

### Main image canvas

Used by image mode.

### Gallery canvas + scrollbar

Used by gallery mode.

### Listbox

Used by list mode to display the filtered file list.

### List preview

Shows a preview image and filename in list mode.

### Status bar

Displays current state information.

### Search entry

Provides filtering/search input.

The method also establishes:

-   default geometry
-   window title
-   fullscreen/floating behavior
-   colors
-   fonts
-   content layout.

Selector mode and explicit floating-window mode are configured as
topmost/dialog-like windows.

## `_relayout_bars()` --- lines 1165--1175

Re-packs:

-   content
-   status bar
-   search entry.

This is called when the search bar or status bar visibility changes.

## `_show_content()` --- lines 1177--1186

Shows exactly one of:

-   image canvas
-   gallery frame
-   list frame.

------------------------------------------------------------------------

# 14. Keyboard binding system

## `_mk_break()` --- lines 1189--1197

Wraps an action function so Tkinter:

-   catches ordinary action exceptions
-   optionally reports them
-   returns `"break"` to stop further event propagation.

## `_setup_bindings()` --- lines 1199--1201

Simple coordinator for static and configurable bindings.

## `_setup_static_bindings()` --- lines 1203--1213

Installs bindings that are not part of the configurable action map.

These include:

-   mouse buttons
-   resize events
-   window-close handling.

## `_action_fns()` --- lines 1216--1259

Creates the dictionary connecting configuration action names to actual
methods.

For example:

``` text
"next" → _key_next
"reload" → act_reload
"rotate_left" → act_rotate(...)
"fit" → act_fit(...)
```

This is the bridge between the configuration file and application
behavior.

## `_setup_key_bindings()` --- lines 1261--1331

Installs all keyboard bindings.

It distinguishes two cases:

### Search-bar mode

Bindings are attached to the search entry and use the configured
modifiers.

### Direct-key mode

Bindings are converted through `_to_direct_key()` and attached to the
root window.

Non-configurable navigation keys such as arrows, Home/End, Tab, Return,
Escape and Delete are installed separately.

`Ctrl+Enter` is also installed as a mark-toggle shortcut while the
search bar is active.

## `_on_root_key()` --- lines 1333--1341

Keeps the search entry focused in search-bar mode and forwards printable
key presses into it.

------------------------------------------------------------------------

# 15. Search/filter subsystem

## `act_toggle_searchbar()` --- lines 1344--1359

Switches between:

-   search-bar mode
-   direct-key mode.

When entering direct-key mode it clears the active filter.

It then rebuilds bindings and layout.

## `_on_search_change()` --- lines 1362--1368

Triggered whenever the search text changes.

It:

1.  updates `_filter_text`
2.  rebuilds visible indices
3.  schedules debounced UI refresh.

## `_apply_filter_ui()` --- lines 1370--1389

Applies the filtered list to the currently visible mode.

It ensures the current index remains valid and refreshes:

-   image information
-   gallery
-   listbox/list preview.

## `_rebuild_visible()` --- lines 1391--1403

Implements the actual search.

The query is lowercased and split into whitespace-separated terms.

Every term must occur in either:

-   the entry label
-   the entry path.

Thus a query like:

``` text
vacation beach
```

requires both words to match the same entry, in either its label or
path.

## `_initial_load()` --- lines 1405--1415

Performs the first mode-specific display operation after the GUI has
initialized.

------------------------------------------------------------------------

# 16. Lazy scanning

## `start_lazy_scan()` --- lines 1418--1481

Runs filesystem discovery in a background thread.

It can:

-   scan directories
-   recurse
-   sort by modification time
-   stop if quitting/cancelled
-   batch results.

The important design goal is that the Tkinter window appears before a
large directory scan has completed.

## `_queue_lazy_files()` --- lines 1483--1489

Receives a batch from the worker and adds it to the pending lazy-scan
queue.

## `_commit_lazy_batch()` --- lines 1491--1532

Moves pending discovered paths into `self.files`.

It updates:

-   visible indices
-   thumbnail arrays
-   current index
-   sorting state
-   image loading.

## `_schedule_lazy_redraw()` --- lines 1534--1538

Coalesces redraw requests so a large scan does not trigger a GUI redraw
for every individual file.

## `_do_lazy_redraw()` --- lines 1540--1551

Performs the actual coalesced refresh.

## `_lazy_scan_finished()` --- lines 1553--1573

Finalizes the lazy scan, applies final sorting and refreshes the current
mode.

------------------------------------------------------------------------

# 17. Main-thread scheduling

## `_post()` --- lines 1576--1577

Places a callback into the application's queue.

Worker threads use this instead of directly touching Tkinter widgets.

## `_poll_main_queue()` --- lines 1579--1600

Runs queued callbacks from the Tkinter thread.

It also handles pending sorting/redraw work.

This is the central synchronization mechanism between worker threads and
the GUI.

## `set_timeout()` --- lines 1603--1609

Creates/replaces a named Tkinter timer.

Timers are stored by name in `_timeout_ids`.

## `_run_timeout()` --- lines 1611--1613

Executes a stored timer callback.

## `reset_timeout()` --- lines 1615--1618

Cancels a named pending timer.

This timer abstraction is used for:

-   animation
-   slideshow
-   filtering
-   other delayed UI work.

------------------------------------------------------------------------

# 18. Sorting

## `_sort_keyfunc()` --- lines 1621--1638

Produces the key function for:

-   name
-   modification time
-   file size.

## `_apply_sort()` --- lines 1640--1704

Reorders `self.files`.

It preserves the current file where possible and rebuilds visible
indices afterward.

The sort modes are:

``` text
none  → discovery order
name  → filename/entry name
mtime → modification time
size  → file size
```

Reverse sorting is applied separately.

## `_sort_label()` --- lines 1706--1719

Produces the human-readable sorting description used by the status
display.

## `act_sort_cycle()` --- lines 1721--1736

Cycles through sorting modes.

## `act_sort_reverse()` --- lines 1738--1742

Toggles ascending/reverse ordering.

------------------------------------------------------------------------

# 19. File removal and current-index persistence

## `remove_file()` --- lines 1745--1775

Removes one entry from `self.files`.

If called for a manual operation, it handles current-index correction
and may quit when no entries remain.

## `_set_current()` --- lines 1778--1782

Changes the current file index and resets/updates related state.

## `_persist_index()` --- lines 1784--1792

Writes the current index to the optional `--idx-write-path` file.

This is primarily a debugging/integration facility.

------------------------------------------------------------------------

# 20. Image loading and asynchronous prefetch

## `_install_image()` --- lines 1794--1807

Installs decoded frames into the active image state.

It updates:

-   frames
-   delays
-   dimensions
-   selected frame
-   animation state.

## `load_image()` --- lines 1809--1842

Synchronous image-loading path.

It:

1.  validates the index
2.  updates current-file state
3.  decodes frames
4.  installs them
5.  persists the index
6.  handles failures.

## `load_image_async()` --- lines 1844--1863

Preferred non-blocking image-loading path.

It creates a load token and submits decoding to a worker.

The token prevents an old worker result from replacing a newer requested
image.

## `_apply_async_result()` --- lines 1865--1885

Consumes an asynchronous decoder result.

It rejects stale results and then installs valid frames.

After loading it can initiate neighbor prefetching.

## `_request_decode()` --- lines 1887--1905

Submits a decode operation to the image executor.

The callback is posted back to the GUI queue.

## `_prefetch_neighbors()` --- lines 1907--1919

Requests nearby images so next/previous navigation can be faster.

## `_submit_prefetch()` --- lines 1921--1939

Actually submits a neighbor prefetch task if it is not already cached/in
flight.

## `_schedule_animate()` --- lines 1941--1944

Schedules the next animation frame.

## `animate()` --- lines 1946--1951

Advances the selected animation frame and schedules the next one.

------------------------------------------------------------------------

# 21. General redraw

## `redraw()` --- lines 1954--1963

Central rendering dispatcher.

It updates information and then invokes the renderer corresponding to
`self.mode`:

``` text
MODE_IMAGE   → render_image()
MODE_GALLERY → render_gallery()
MODE_LIST    → render_list()
```

This is one of the most important methods in the class.

------------------------------------------------------------------------

# 22. Image fitting, cropping and rendering

## `_steps_to_range()` --- lines 1967--1968

Converts a signed adjustment-step value into a bounded numeric range.

It is used by image adjustment logic.

## `_prepare_crop()` --- lines 1970--1994

Applies image transformations before display.

It handles the configured gamma/brightness/contrast-related display
preparation and keeps the displayed image within the intended adjustment
ranges.

## `_fit()` --- lines 1996--2010

Calculates image scale/position for the current scaling mode.

The modes correspond to:

-   downscale-only
-   fit
-   fill
-   fit width
-   fit height
-   explicit zoom.

## `_check_pan()` --- lines 2012--2026

Keeps image panning within sensible bounds.

It prevents the image from being moved indefinitely outside the visible
canvas.

## `render_image()` --- lines 2028--2075

Renders the current image frame.

The broad sequence is:

``` text
select current frame
      ↓
calculate scale
      ↓
check pan position
      ↓
crop visible source region
      ↓
resize using antialias/nearest-neighbor
      ↓
create ImageTk.PhotoImage
      ↓
draw on Tkinter Canvas
```

When the image is zoomed, the method avoids unnecessarily resizing the
entire source image and instead computes the visible crop.

------------------------------------------------------------------------

# 23. Gallery aspect ratio and tile geometry

## `_get_gallery_aspect()` --- lines 2078--2117

Determines gallery tile aspect ratio.

If `--gallery-aspect` is supplied, it uses that value.

Otherwise it samples up to the configured number of images, obtains
their dimensions in a worker thread, calculates aspect ratios and
eventually uses the median.

The result is clamped to the allowed range.

A provisional default is used while the background calculation is
pending.

## `_finish_aspect()` --- lines 2119--2138

Receives the sampled aspect ratios and updates the cached gallery
aspect.

When the aspect changes, thumbnails are invalidated so they can be
decoded for the new geometry.

## `_compute_tile_metrics()` --- lines 2141--2186

Calculates:

-   tile width
-   tile height
-   caption height
-   padding
-   thumbnail bounds.

It uses the current window dimensions and gallery options.

## `_update_tile_metrics()` --- lines 2188--2198

Updates the stored tile geometry and invalidates/rebuilds dependent
gallery state as necessary.

## `_compute_gallery_cols()` --- lines 2200--2202

Calculates how many columns fit in the current gallery width.

------------------------------------------------------------------------

# 24. Gallery captions and thumbnails

## `_fit_caption()` --- lines 2204--2264

Fits an entry label into the available caption area.

It accounts for:

-   maximum width
-   maximum height
-   text measurement
-   line wrapping/truncation.

## `_submit_gallery_tile()` --- lines 2266--2287

Requests a thumbnail for one gallery entry.

It prevents duplicate in-flight work and uses the thumbnail executor.

## `_on_gallery_tile_ready()` --- lines 2289--2305

Receives a decoded gallery thumbnail and stores it.

The result is associated with a generation value so stale thumbnails can
be rejected.

## `_schedule_gallery_redraw()` --- lines 2307--2311

Coalesces gallery redraw requests.

## `_do_gallery_redraw()` --- lines 2313--2318

Performs the actual deferred gallery redraw.

------------------------------------------------------------------------

# 25. Gallery scrolling/rendering

## `_apply_gallery_scroll()` --- lines 2320--2351

Positions the gallery so the current item is visible.

This is particularly important after:

-   changing the current file
-   changing the filter
-   entering gallery mode.

## `render_gallery()` --- lines 2353--2437

Draws the entire visible gallery region.

For each visible entry it handles:

-   selection/current-item border
-   thumbnail placement
-   mark indicator
-   caption
-   thumbnail submission if not yet decoded.

The gallery uses overscan so nearby tiles can be prepared before they
become visible.

## `_gallery_hit()` --- lines 2439--2454

Maps mouse coordinates to a file index.

It converts canvas coordinates into:

``` text
column
row
row * columns + column
```

and validates the resulting index.

## `_gallery_scroll_by()` --- lines 2456--2469

Moves the gallery canvas vertically by a pixel amount while clamping to
the scrollable region.

## `_gallery_zoom()` --- lines 2471--2484

Changes gallery tile size rather than image zoom.

This is why the same zoom key can have different effects in image and
gallery modes.

## `_on_gallery_configure()` --- lines 2486--2487

Responds to gallery-window resizing.

## `_on_gallery_mousewheel()` --- lines 2489--2493

Converts mouse-wheel events into gallery scrolling.

------------------------------------------------------------------------

# 26. List mode

## `_populate_listbox()` --- lines 2496--2520

Rebuilds the Tkinter listbox from `_visible_indices`.

It also displays mark state alongside entries.

The implementation uses chunked insertion for large lists.

## `_on_listbox_select()` --- lines 2522--2538

Handles a listbox selection.

It updates the current file, persists the index, renders the preview and
refreshes status information.

## `render_list()` --- lines 2540--2576

Loads/renders the preview corresponding to the selected list entry.

Preview decoding is asynchronous where appropriate.

## `_apply_list_preview()` --- lines 2578--2591

Installs the decoded preview into the list-mode label.

------------------------------------------------------------------------

# 27. Status and selector output

## `update_info()` --- lines 2594--2637

Builds the status-bar information.

It combines information such as:

-   current position
-   total number of files
-   filename
-   marks
-   filter/sort state
-   image-related state.

The exact displayed text depends on the current mode and state.

## `_emit_output()` --- lines 2640--2650

Selector output routine.

Depending on `use_labels`, it prints either:

-   the image path
-   the entry label.

If entries have been marked, the marked entries are emitted rather than
only the current entry.

## `quit()` --- lines 2652--2683

Shuts down the application.

For selector mode it can emit the selected result before closing.

It also cancels/terminates application activity and destroys the Tkinter
window.

------------------------------------------------------------------------

# 28. Navigation

## `_navigate()` --- lines 2686--2698

Moves to an absolute file index.

It updates the current item and asynchronously loads the image when
necessary.

## `_nav_visible()` --- lines 2700--2711

Moves relative to the filtered/visible list rather than the complete
unfiltered list.

This is what makes `next`/`previous` respect the search filter.

## `_key_next()` --- lines 2713--2714

Convenience wrapper for moving forward one visible entry.

## `_key_prev()` --- lines 2716--2717

Convenience wrapper for moving backward one visible entry.

## `_key_nav()` --- lines 2719--2739

Interprets directional key presses.

In image mode arrows pan the image.

In gallery/list contexts, navigation changes the selected item.

## `_key_page()` --- lines 2741--2749

Handles PageUp/PageDown-style navigation.

## `_key_return()` --- lines 2751--2760

Return has context-dependent behavior:

-   selector mode can accept the selection
-   image/gallery mode can switch display modes
-   list mode can return to image mode.

## `_key_escape()` --- lines 2762--2766

Escape clears an active search filter first; otherwise it quits.

## `_key_delete()` --- lines 2768--2769

Maps Delete to file removal.

## `_key_zoom_100()` --- lines 2771--2774

Sets explicit 100% zoom.

------------------------------------------------------------------------

# 29. Mode switching

## `_cycle_mode()` --- lines 2776--2789

Cycles:

``` text
image → gallery → list → image
```

or backwards when requested.

## `_enter_image_mode()` --- lines 2791--2801

Switches to image mode, resets incompatible timers/state, changes
visible widgets and loads the current image.

## `_enter_gallery_mode()` --- lines 2803--2817

Switches to gallery mode and requests a redraw around the current item.

## `_enter_list_mode()` --- lines 2819--2833

Switches to list mode, populates the listbox and renders its preview.

------------------------------------------------------------------------

# 30. Basic actions

## `act_first()` --- lines 2836--2838

Moves to the first visible file.

## `act_last()` --- lines 2840--2842

Moves to the last visible file.

## `act_toggle_fullscreen()` --- lines 2844--2847

Toggles the Tkinter fullscreen window attribute.

## `act_toggle_bar()` --- lines 2849--2852

Toggles the status bar and relays out the UI.

## `_refresh_size()` --- lines 2854--2862

Recomputes display dimensions after window resizing and redraws.

## `act_reload()` --- lines 2864--2872

Reloads the current image.

This is useful both for explicit user reloads and for refreshing a file
after it changes on disk.

## `act_remove()` --- lines 2874--2896

Removes the current file, or the marked files where appropriate.

After removal it chooses an appropriate new current index and refreshes
the current mode.

------------------------------------------------------------------------

# 31. Marking

## `_mark()` --- lines 2898--2905

Sets or clears the `FF_MARK` flag for one entry.

## `act_toggle_mark()` --- lines 2907--2914

Toggles the current entry's mark.

## `act_unmark_all()` --- lines 2916--2921

Clears marks from all entries.

Marking is especially important in selector mode because multiple marked
entries can be emitted together.

------------------------------------------------------------------------

# 32. Image adjustments

## `act_gamma()` --- lines 2923--2927

Changes gamma in bounded steps and redraws.

## `act_brightness()` --- lines 2929--2933

Changes brightness in bounded steps and redraws.

This method exists internally even though it does not have a default
configurable key binding in `DEFAULT_KEYS`.

## `act_contrast()` --- lines 2935--2939

Changes contrast in bounded steps and redraws.

These methods alter the state used by `_prepare_crop()`/image rendering
rather than changing the source file.

------------------------------------------------------------------------

# 33. Zoom and panning

## `_zoom_to()` --- lines 2941--2947

Changes the zoom while attempting to preserve the point currently under
the cursor/center.

It also switches the scaling mode to explicit zoom.

## `act_zoom()` --- lines 2949--2963

In image mode, moves through the discrete `ZOOM_LEVELS`.

In gallery mode it delegates to `_gallery_zoom()`.

List mode ignores the action.

## `_pan()` --- lines 2965--2968

Changes image position and then clamps it with `_check_pan()`.

## `act_scroll()` --- lines 2970--2985

Pans by either:

-   a fraction of the window
-   a whole screen.

Direction determines which axis is changed.

## `act_scroll_center()` --- lines 2987--2993

Centers the image in the available canvas.

## `act_fit()` --- lines 2995--2998

Changes the active scaling mode and redraws image mode.

------------------------------------------------------------------------

# 34. Transformations and display toggles

## `act_rotate()` --- lines 3000--3007

Rotates every currently loaded animation frame.

This is an in-memory transformation; it does not overwrite the source
file.

## `act_flip()` --- lines 3009--3018

Horizontally or vertically flips every loaded frame.

## `act_toggle_antialias()` --- lines 3020--3022

Switches between antialiased and nearest-neighbor resizing.

## `act_toggle_alpha()` --- lines 3024--3026

Toggles alpha-layer display state.

------------------------------------------------------------------------

# 35. Slideshow and animation

## `act_slideshow()` --- lines 3028--3035

Starts/stops slideshow mode.

The slideshow timer is independent from animated-image frame timing.

## `_schedule_slideshow()` --- lines 3037--3043

Schedules the next slideshow transition.

If an animated image is currently being played, it ensures the slideshow
delay does not interrupt it too aggressively.

## `slideshow_next()` --- lines 3045--3055

Moves to the next visible image and schedules another transition.

## `act_toggle_animation()` --- lines 3057--3063

Enables/disables animated-image playback.

## `act_navigate()` --- lines 3065--3068

Image-mode navigation wrapper around `_nav_visible()`.

------------------------------------------------------------------------

# 36. Mouse and window events

## `on_button()` --- lines 3071--3126

Handles mouse buttons according to the current mode.

### Image mode

-   left click on the left/right third navigates
-   right click enters gallery mode
-   wheel changes zoom.

### Gallery mode

-   left click selects an item
-   Ctrl+left click can mark in selector mode
-   right click toggles marking
-   wheel scrolls.

### List mode

-   left click selects the list item
-   right click toggles its mark.

Thus mouse behavior is intentionally mode-sensitive.

## `on_configure()` --- lines 3128--3133

Receives window resize events and schedules a delayed resize
calculation.

The delay prevents a continuous stream of resize events from causing
expensive redraws for every intermediate window size.

## `_do_resize()` --- lines 3135--3137

Calls `_refresh_size()` after the resize debounce.

## `_poll_autoreload()` --- lines 3139--3155

Runs every 500 ms.

When an image is displayed, it checks its modification time. If the file
changed, it invalidates the corresponding prefetch entry and reloads the
image asynchronously.

This provides automatic external-file-change detection.

------------------------------------------------------------------------

# 37. Viewer entry point

## `run_viewer()` --- lines 3159--3276

This is the implementation of:

``` text
tkiv img ...
```

Its sequence is:

``` text
build parser
   ↓
parse arguments
   ↓
handle --help / --version
   ↓
normalize legacy title/class options
   ↓
warn if pyvips unavailable
   ↓
obtain input paths
   ↓
expand directories
   ↓
create FileEntry objects
   ↓
create Tk root
   ↓
create TkivApp
   ↓
start lazy scan if requested
   ↓
root.mainloop()
```

## Input sources

The viewer accepts:

-   ordinary command-line paths
-   directory paths
-   stdin
-   NUL-separated stdin when `--null` is used
-   lazy directory scanning.

`--assume-files` is parsed by the viewer parser but the current
`run_viewer()` path does not use it to bypass image/path handling in the
same way a traditional sxiv/nsxiv implementation might.

## Help/version

The function prints custom help text rather than relying on argparse's
automatic `-h` behavior because the parser was constructed with
`add_help=False`.

------------------------------------------------------------------------

# 38. Selector entry point

## `run_selector()` --- lines 3279--3399

This implements:

``` text
tkiv select ...
```

It has two input styles.

## Normal selector mode

Paths/directories are discovered just like viewer mode.

## dmenu mode

`--dmenu-mode` expects:

``` text
list entries
image entries
```

The two lists can come from files or newline-separated command-line
values.

The source requires:

``` text
number of labels == number of image paths
```

Each pair becomes:

``` python
FileEntry(path, label)
```

This lets the selector display arbitrary labels while returning
corresponding image paths.

## Return behavior

The selector can return:

-   image paths
-   labels when `--return-label` is used.

Marked entries are emitted together when selection is accepted.

------------------------------------------------------------------------

# 39. Top-level dispatcher

## `main()` --- lines 3403--3425

`main()` is the command dispatcher.

It expects a subcommand after the program name.

Accepted viewer aliases:

``` text
img
view
viewer
pysxiv
```

Accepted selector aliases:

``` text
select
sel
selector
sel_img
```

It rewrites `sys.argv` so the selected sub-parser receives only its own
arguments.

Unknown modes produce an error.

This structure is effectively a hand-written two-subcommand CLI rather
than an argparse subparser hierarchy.

------------------------------------------------------------------------

# 40. `if __name__ == '__main__'`

The final block:

``` python
if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
```

ensures that:

-   importing the module does not automatically launch the program
-   executing it directly invokes `main()`
-   normal `SystemExit` behavior is preserved.

------------------------------------------------------------------------

# 41. Runtime data flow

A normal viewer invocation can be summarized as:

``` text
CLI arguments
     │
     ▼
run_viewer()
     │
     ▼
filesystem discovery
     │
     ▼
FileEntry objects
     │
     ▼
TkivApp.__init__()
     │
     ├── configuration
     ├── UI construction
     ├── key bindings
     ├── sorting
     └── timers/workers
     │
     ▼
Tk mainloop
     │
     ├── user input
     │
     ├── filter changes
     │
     ├── mode changes
     │
     ├── image decode workers
     │
     ├── thumbnail workers
     │
     └── filesystem polling
     │
     ▼
redraw()
     │
     ├── render_image()
     ├── render_gallery()
     └── render_list()
```

------------------------------------------------------------------------

# 42. Threading model

The program has three important execution contexts.

## Tkinter GUI thread

This owns:

-   widgets
-   canvas operations
-   focus
-   event handlers
-   visible application state.

## Image worker pool

`_img_executor` handles full-image decoding.

## Thumbnail worker pool

`_thumb_executor` handles gallery thumbnail decoding.

Additional background threads are used for:

-   lazy directory scanning
-   gallery aspect-ratio sampling.

Workers do not directly update Tkinter widgets. Instead they call
`_post()`, which puts callbacks into `_main_queue`.

The GUI periodically calls `_poll_main_queue()`.

This is the core thread-safety pattern:

``` text
worker
  │
  ├── do filesystem/image work
  │
  └── queue callback
           │
           ▼
      Tk main thread
           │
           └── update widgets
```

------------------------------------------------------------------------

# 43. Generation/token mechanism

Several asynchronous systems can have stale results.

The source therefore uses generation/token values such as:

-   `_load_token`
-   `_files_gen`
-   `_aspect_gen`

Conceptually:

``` text
request A starts
request B starts
request A finishes later
```

Without a token, A could overwrite B.

The source checks the relevant token/generation before applying
asynchronous results.

This is especially important for:

-   rapidly changing current images
-   gallery aspect detection
-   thumbnail generation
-   lazy-scan updates.

------------------------------------------------------------------------

# 44. Caching model

There are two levels of thumbnail caching.

## In-memory prefetch cache

`_prefetch_cache` stores recently decoded neighboring images.

It is an `OrderedDict`, allowing entries to be removed as the cache
grows.

## Disk thumbnail cache

`_decode_thumb()` can store thumbnails as WebP files.

The cache key depends on:

``` text
absolute/path identity as represented by the source
+ mtime
+ file size
+ requested dimensions
```

This means a changed source file naturally produces a different cache
key.

------------------------------------------------------------------------

# 45. Search and selection model

The source separates:

``` text
self.files
```

from:

``` text
self._visible_indices
```

`self.files` is the complete ordered dataset.

`_visible_indices` contains indices into that dataset after filtering.

This is a useful design choice because filtering does not physically
remove files from the master list.

For example:

``` text
files:
0 a.jpg
1 beach.png
2 beach2.jpg
3 cat.jpg

query: beach

visible_indices:
[1, 2]
```

Navigation then operates on `[1, 2]` while marks remain attached to the
original `FileEntry` objects.

------------------------------------------------------------------------

# 46. Mode separation

Although all modes use one class, their responsibilities are separated
by renderer methods.

  Mode      Main renderer        Supporting UI
  --------- -------------------- ----------------------------
  Image     `render_image()`     image canvas
  Gallery   `render_gallery()`   gallery canvas + scrollbar
  List      `render_list()`      listbox + preview

`redraw()` is the common dispatch point.

Mode switching is performed by:

``` text
_enter_image_mode()
_enter_gallery_mode()
_enter_list_mode()
_cycle_mode()
```

------------------------------------------------------------------------

# 47. Viewer vs selector behavior

The source does not implement two separate application classes.

Instead:

``` python
TkivApp(..., purpose='view')
```

or:

``` python
TkivApp(..., purpose='select')
```

changes behavior in selected places.

Examples include:

-   selector window is topmost/dialog-like
-   Return can accept a selector choice
-   marked entries are emitted
-   Ctrl+click in gallery can mark entries
-   selector output uses `_emit_output()`.

This keeps image viewing and image selection behavior on the same UI
foundation.

------------------------------------------------------------------------

# 48. Options parsed but not meaningfully consumed

The source defines several command-line options that are not wired into
substantial runtime behavior in the current version.

The important distinction is:

> **An option existing in `argparse` does not necessarily mean that the
> current implementation implements the feature behind it.**

The source currently parses options including:

-   `--framerate`
-   `--clean-cache`
-   `--embed`
-   `--private`
-   `--cache-allow`
-   `--cache-deny`
-   `--update-cache`

Some other parsed values are used only for compatibility or
normalization, such as the legacy `--class`/`--legacy-name` handling.

This document therefore treats the parser and the actual runtime
separately.

------------------------------------------------------------------------

# 49. Source-order function index

The following index gives every top-level function and class method in
the source, with its approximate source range and role.

## Top-level functions

  -----------------------------------------------------------------------------
                         Lines Function                   Role
  ---------------------------- -------------------------- ---------------------
                      311--330 `_split_key_spec`          Split human key
                                                          specification

                      333--365 `_parse_key_spec`          Convert key
                                                          specification to Tk
                                                          sequence

                      368--387 `_to_direct_key`           Remove modifiers for
                                                          direct-key mode

                      390--391 `_validate_color`          Validate `#RRGGBB`

                      394--453 `_parse_config_text`       Parse configuration

                      459--486 `_get_config`              Load/cache
                                                          configuration

                      490--491 `file_is_image`            Test supported
                                                          extension

                      494--524 `collect_dir`              Discover image files
                                                          in directories

                      527--546 `_vips_to_pil`             Convert pyvips image
                                                          to Pillow

                      549--603 `_vips_load_frames`        Decode frames with
                                                          pyvips

                      606--628 `_pil_load_frames`         Decode frames with
                                                          Pillow

                      631--637 `load_frames`              Decoder abstraction

                      640--652 `load_gallery_thumb`       Decode gallery
                                                          thumbnail

                      655--667 `_get_orig_size`           Read image dimensions

                      670--678 `_disk_cache_path`         Build thumbnail cache
                                                          path

                      681--743 `_decode_thumb`            Optimized thumbnail
                                                          decode/cache

                      747--792 `_add_shared_ui_options`   Shared CLI options

                      795--830 `build_viewer_parser`      Build viewer CLI
                                                          parser

                      833--847 `build_selector_parser`    Build selector CLI
                                                          parser

                      850--863 `_read_pre_select`         Read initial marks

                    3159--3276 `run_viewer`               Run viewer mode

                    3279--3399 `run_selector`             Run selector mode

                    3403--3425 `main`                     Dispatch subcommand
  -----------------------------------------------------------------------------

## `FileEntry`

       Lines Method       Role
  ---------- ------------ -----------------------------
    869--873 `__init__`   Store path, label and flags

## `TkivApp` initialization/UI/input

         Lines Method                     Role
  ------------ -------------------------- ----------------------------------
     880--1029 `__init__`                 Initialize complete application
    1032--1038 `_apply_pre_select`        Apply initial marks
    1041--1163 `_setup_ui`                Construct Tkinter interface
    1165--1175 `_relayout_bars`           Repack status/search bars
    1177--1186 `_show_content`            Show active mode widget
    1189--1197 `_mk_break`                Wrap Tk actions
    1199--1201 `_setup_bindings`          Install bindings
    1203--1213 `_setup_static_bindings`   Mouse/close/resize bindings
    1216--1259 `_action_fns`              Action-name → callable map
    1261--1331 `_setup_key_bindings`      Install configurable/static keys
    1333--1341 `_on_root_key`             Keep search entry focused

## Search/lazy scanning

         Lines Method                    Role
  ------------ ------------------------- ----------------------------
    1344--1359 `act_toggle_searchbar`    Toggle direct/search mode
    1362--1368 `_on_search_change`       Process query changes
    1370--1389 `_apply_filter_ui`        Refresh UI after filtering
    1391--1403 `_rebuild_visible`        Build filtered index list
    1405--1415 `_initial_load`           Initial mode rendering
    1418--1481 `start_lazy_scan`         Background filesystem scan
    1483--1489 `_queue_lazy_files`       Queue scan batch
    1491--1532 `_commit_lazy_batch`      Commit discovered files
    1534--1538 `_schedule_lazy_redraw`   Coalesce scan redraws
    1540--1551 `_do_lazy_redraw`         Execute scan redraw
    1553--1573 `_lazy_scan_finished`     Finish lazy scan

## Scheduling/sorting

         Lines Method               Role
  ------------ -------------------- -----------------------
    1576--1577 `_post`              Queue GUI callback
    1579--1600 `_poll_main_queue`   Run queued callbacks
    1603--1609 `set_timeout`        Create named timer
    1611--1613 `_run_timeout`       Execute timer
    1615--1618 `reset_timeout`      Cancel timer
    1621--1638 `_sort_keyfunc`      Build sort key
    1640--1704 `_apply_sort`        Apply ordering
    1706--1719 `_sort_label`        Describe current sort
    1721--1736 `act_sort_cycle`     Cycle sorting
    1738--1742 `act_sort_reverse`   Reverse sorting

## File/image state

         Lines Method                  Role
  ------------ ----------------------- -------------------------------
    1745--1775 `remove_file`           Delete entry from active list
    1778--1782 `_set_current`          Change current index
    1784--1792 `_persist_index`        Write current index
    1794--1807 `_install_image`        Install decoded frames
    1809--1842 `load_image`            Synchronous image load
    1844--1863 `load_image_async`      Asynchronous image load
    1865--1885 `_apply_async_result`   Apply worker result
    1887--1905 `_request_decode`       Submit image decode
    1907--1919 `_prefetch_neighbors`   Request neighboring images
    1921--1939 `_submit_prefetch`      Submit prefetch job
    1941--1944 `_schedule_animate`     Schedule animation
    1946--1951 `animate`               Advance animation
    1954--1963 `redraw`                Dispatch rendering

## Image renderer

         Lines Method              Role
  ------------ ------------------- --------------------------------
    1967--1968 `_steps_to_range`   Bound adjustment step
    1970--1994 `_prepare_crop`     Prepare transformed image crop
    1996--2010 `_fit`              Calculate image fit/scale
    2012--2026 `_check_pan`        Clamp image position
    2028--2075 `render_image`      Render current image

## Gallery

         Lines Method                       Role
  ------------ ---------------------------- --------------------------------
    2078--2117 `_get_gallery_aspect`        Determine tile aspect
    2119--2138 `_finish_aspect`             Apply detected aspect
    2141--2186 `_compute_tile_metrics`      Calculate tile geometry
    2188--2198 `_update_tile_metrics`       Update gallery geometry
    2200--2202 `_compute_gallery_cols`      Calculate columns
    2204--2264 `_fit_caption`               Fit tile caption
    2266--2287 `_submit_gallery_tile`       Submit thumbnail job
    2289--2305 `_on_gallery_tile_ready`     Store thumbnail
    2307--2311 `_schedule_gallery_redraw`   Coalesce redraw
    2313--2318 `_do_gallery_redraw`         Execute redraw
    2320--2351 `_apply_gallery_scroll`      Scroll to current item
    2353--2437 `render_gallery`             Render visible tiles
    2439--2454 `_gallery_hit`               Convert mouse position to item
    2456--2469 `_gallery_scroll_by`         Scroll gallery
    2471--2484 `_gallery_zoom`              Change tile size
    2486--2487 `_on_gallery_configure`      Handle gallery resize
    2489--2493 `_on_gallery_mousewheel`     Handle wheel scrolling

## List mode/output/navigation

         Lines Method                  Role
  ------------ ----------------------- -----------------------------
    2496--2520 `_populate_listbox`     Fill listbox
    2522--2538 `_on_listbox_select`    Handle list selection
    2540--2576 `render_list`           Render list preview
    2578--2591 `_apply_list_preview`   Install preview
    2594--2637 `update_info`           Update status text
    2640--2650 `_emit_output`          Print selector result
    2652--2683 `quit`                  Shut down application
    2686--2698 `_navigate`             Move to absolute item
    2700--2711 `_nav_visible`          Move through filtered items
    2713--2714 `_key_next`             Next wrapper
    2716--2717 `_key_prev`             Previous wrapper
    2719--2739 `_key_nav`              Arrow navigation
    2741--2749 `_key_page`             Page navigation
    2751--2760 `_key_return`           Return/accept/mode switch
    2762--2766 `_key_escape`           Escape handling
    2768--2769 `_key_delete`           Delete action
    2771--2774 `_key_zoom_100`         100% zoom
    2776--2789 `_cycle_mode`           Cycle visual modes
    2791--2801 `_enter_image_mode`     Enter image mode
    2803--2817 `_enter_gallery_mode`   Enter gallery mode
    2819--2833 `_enter_list_mode`      Enter list mode

## Actions/transforms/events

         Lines Method                    Role
  ------------ ------------------------- ------------------------------
    2836--2838 `act_first`               First visible entry
    2840--2842 `act_last`                Last visible entry
    2844--2847 `act_toggle_fullscreen`   Toggle fullscreen
    2849--2852 `act_toggle_bar`          Toggle status bar
    2854--2862 `_refresh_size`           Refresh layout dimensions
    2864--2872 `act_reload`              Reload current image
    2874--2896 `act_remove`              Remove current/marked files
    2898--2905 `_mark`                   Set/clear mark flag
    2907--2914 `act_toggle_mark`         Toggle current mark
    2916--2921 `act_unmark_all`          Clear all marks
    2923--2927 `act_gamma`               Adjust gamma
    2929--2933 `act_brightness`          Adjust brightness
    2935--2939 `act_contrast`            Adjust contrast
    2941--2947 `_zoom_to`                Set explicit zoom
    2949--2963 `act_zoom`                Change image/gallery zoom
    2965--2968 `_pan`                    Move image
    2970--2985 `act_scroll`              Directional panning
    2987--2993 `act_scroll_center`       Center image
    2995--2998 `act_fit`                 Select fit mode
    3000--3007 `act_rotate`              Rotate loaded frames
    3009--3018 `act_flip`                Flip loaded frames
    3020--3022 `act_toggle_antialias`    Toggle resampling mode
    3024--3026 `act_toggle_alpha`        Toggle alpha display
    3028--3035 `act_slideshow`           Toggle slideshow
    3037--3043 `_schedule_slideshow`     Schedule slideshow
    3045--3055 `slideshow_next`          Advance slideshow
    3057--3063 `act_toggle_animation`    Toggle animated playback
    3065--3068 `act_navigate`            Image navigation action
    3071--3126 `on_button`               Mouse event dispatcher
    3128--3133 `on_configure`            Window resize handler
    3135--3137 `_do_resize`              Execute resize refresh
    3139--3155 `_poll_autoreload`        Detect external file changes

------------------------------------------------------------------------

# 50. Important implementation relationships

Several parts of the source are easier to understand as pairs or
pipelines.

## Configuration → key bindings

``` text
config text
   ↓
_parse_config_text()
   ↓
self._key_bindings
   ↓
_action_fns()
   ↓
_setup_key_bindings()
   ↓
Tkinter event
   ↓
act_* / _key_* method
```

## Search → navigation

``` text
search_entry
   ↓
_on_search_change()
   ↓
_rebuild_visible()
   ↓
_visible_indices
   ↓
_nav_visible()
```

## Image loading → rendering

``` text
load_image_async()
   ↓
_request_decode()
   ↓
load_frames()
   ↓
_apply_async_result()
   ↓
_install_image()
   ↓
redraw()
   ↓
render_image()
```

## Gallery thumbnail loading

``` text
render_gallery()
   ↓
_submit_gallery_tile()
   ↓
_decode_thumb()
   ↓
_on_gallery_tile_ready()
   ↓
_schedule_gallery_redraw()
   ↓
render_gallery()
```

## Selector acceptance

``` text
mark entries
    ↓
Return
    ↓
_key_return()
    ↓
quit()
    ↓
_emit_output()
    ↓
stdout
```

------------------------------------------------------------------------

# 51. What the source is responsible for vs. what Tkinter/Pillow provide

`tkiv.py` implements the application logic, but it relies heavily on
external libraries.

### Tkinter provides

-   window
-   widgets
-   canvas
-   event bindings
-   timers
-   listbox
-   text entry
-   Tk image objects.

### Pillow provides

-   image decoding fallback
-   image conversion
-   resizing
-   rotation
-   flipping
-   enhancement/transformation operations
-   `ImageTk.PhotoImage`.

### pyvips provides

-   faster/lower-memory image access for supported paths
-   thumbnail generation
-   image dimensions
-   multi-page loading.

### NumPy provides

-   conversion of pyvips pixel buffers to Pillow arrays in the optimized
    thumbnail path.

The application ties these components together rather than implementing
an image codec or GUI toolkit itself.

------------------------------------------------------------------------

# 52. The main design idea

The most important design feature of the source is that **viewer,
gallery, list selector, filtering, and asynchronous decoding are not
separate programs**.

They are layers around one shared state object:

``` text
                         TkivApp
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
     dataset            current state        UI mode
        │                   │                   │
    FileEntry[]       index/zoom/marks      image/gallery/list
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                       redraw()
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        render_image  render_gallery  render_list
```

The asynchronous workers are deliberately kept outside the Tkinter
rendering path. Their job is to produce data; the GUI thread decides
when and how that data becomes visible.

That separation is what allows the program to remain responsive while
scanning directories, decoding large images, prefetching neighbors, and
building large galleries.

------------------------------------------------------------------------

# 53. Source map at a glance

``` text
1–~180       imports, theme, constants
~180–486     persistent configuration and key parsing
490–743      filesystem/image/thumbnail helpers
747–863      CLI parsers and pre-selection
867–873      FileEntry
877–3155     TkivApp
  880–1029     initialization
  1041–1186    UI construction
  1189–1341    keyboard bindings
  1344–1415    search/filter
  1418–1573    lazy scanning
  1576–1742    queues/timers/sorting
  1745–1951    files/images/prefetch/animation
  1954–2075    image rendering
  2078–2489    gallery
  2496–2591    list mode
  2594–2683    status/output/shutdown
  2686–2833    navigation/mode switching
  2836–3068    user actions/image manipulation
  3071–3155    mouse/resize/auto-reload
3159–3276     viewer entry point
3279–3399     selector entry point
3403–3425     dispatcher
3428–3432     __main__ wrapper
```

This is the source's logical organization: setup and helpers first, one
unified application class in the middle, and the three-level
command-line entry point at the end.
