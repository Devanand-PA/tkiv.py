# `tkiv.py` Source Code Documentation

This document provides a comprehensive breakdown of the `tkiv.py` source code. `tkiv` is a unified, high-performance image viewer and selector written in Python. It combines the functionality of an image viewer (similar to `nsxiv`) and an interactive selector (similar to `dmenu` or `fzf`) into a single application using `tkinter`, `Pillow`, and optionally `pyvips`.

---

## 1. Header & Docstring
The file begins with a detailed docstring explaining:
*   **Usage Modes**: `tkiv.py img` (viewer) and `tkiv.py select` (selector).
*   **Keybindings**: A comprehensive list of default shortcuts (e.g., `Ctrl+Q` to quit, `Tab` to cycle modes).
*   **Direct-Key Mode**: Explains the `F2` toggle that hides the search bar and maps `Ctrl+<key>` actions to plain `<key>` presses.
*   **Configuration**: Details the INI-like config file located at `~/.config/tkiv.py/config`.

## 2. Imports & Dependencies
*   **Standard Library**: Uses `argparse`, `os`, `sys`, `threading`, `queue`, `concurrent.futures`, `pathlib`, `hashlib`, etc., for CLI parsing, file I/O, and multithreading.
*   **Image Processing**: 
    *   **Pillow (`PIL`)**: The required fallback for image decoding and manipulation.
    *   **`pyvips` & `numpy`**: Optional dependencies. If installed, they provide significantly faster image loading, thumbnail generation, and memory efficiency.
*   **GUI**: Imports `tkinter` and its submodules (`Canvas`, `Listbox`, `Frame`, etc.) for the graphical interface.

## 3. Theme & Constants
*   **`THEME`**: A dictionary defining a Nord-inspired color palette (backgrounds, foregrounds, accents, selection colors).
*   **Constants**: Defines operational limits and defaults:
    *   Zoom levels, animation delays, and color correction steps.
    *   Supported image extensions (`IMAGE_EXTS`).
    *   Threading limits (`IMG_WORKERS`, `THUMB_WORKERS`).
    *   Gallery layout parameters (tile sizes, aspect ratios, padding).
    *   Disk cache settings for thumbnails.

## 4. Configuration System
Handles parsing the user's `~/.config/tkiv.py/config` file.
*   **`DEFAULT_KEYS` & `DEFAULT_BEHAVIOR`**: Dictionaries holding the fallback keybindings and behavioral settings.
*   **Key Parsing (`_parse_key_spec`, `_to_direct_key`)**: Translates human-readable key specs (e.g., `Ctrl+Shift+W`) into Tkinter event sequences (e.g., `<Control-Shift-w>`). It also handles the logic to strip modifiers for "Direct-Key Mode".
*   **`_parse_config_text`**: A custom INI parser that validates sections (`[keys]`, `[theme]`, `[behavior]`), hex colors, and key sequences. If any syntax error occurs, the entire config is safely discarded in favor of defaults.

## 5. Helper Functions & Image Loading
Utilities for file discovery and image decoding.
*   **File Discovery**: `file_is_image`, `collect_dir` (handles recursive scanning and sorting).
*   **Image Decoding**:
    *   `_vips_load_frames` / `_pil_load_frames`: Extracts frames and delays for animated images (GIFs, WebPs).
    *   `load_frames`: The main dispatcher that attempts `pyvips` first, then falls back to `Pillow`.
*   **Thumbnails & Caching**:
    *   `load_gallery_thumb`: Generates resized thumbnails.
    *   `_decode_thumb`: Implements a disk-caching mechanism using WebP to store decoded thumbnails in `~/.cache/tkiv_thumbs`, drastically speeding up subsequent gallery loads.

## 6. CLI Argument Parsing
*   **`_add_shared_ui_options`**: Adds arguments common to both modes (e.g., `--gallery`, `--recursive`, `--sort`, `--no-searchbar`).
*   **`build_viewer_parser`**: Adds viewer-specific flags (e.g., `--fullscreen`, `--animate`, `--scale-mode`, `--zoom`).
*   **`build_selector_parser`**: Adds selector-specific flags (e.g., `--dmenu-mode`, `--list-file`, `--return-label`).

## 7. Core Application Class (`TkivApp`)
The heart of the application. It manages the state, UI, threading, and rendering for both the viewer and selector modes.

### A. Initialization & State
*   **`__init__`**: Sets up the application state, loads the config, initializes `ThreadPoolExecutor` for background image decoding, and sets up the main event queue.
*   **State Variables**: Tracks current file index, zoom level, pan offsets, animation state, sorting mode, and filter text.

### B. UI Layout & Widgets
*   **`_setup_ui`**: Constructs the Tkinter window. It creates:
    *   `canvas`: For single-image viewing.
    *   `gallery_canvas`: For the thumbnail grid.
    *   `list_frame`: Contains a `Listbox` and a preview `Label` for list mode.
    *   `status`: The bottom status bar.
    *   `search_entry`: The filter/search bar.
*   **`_relayout_bars` / `_show_content`**: Dynamically packs/unpacks widgets based on the current mode (Image, Gallery, or List) and whether the search bar is visible.

### C. Keybindings & Input Handling
*   **`_setup_bindings`**: Maps Tkinter events to internal methods.
*   **`_action_fns`**: A dictionary mapping string action names (e.g., `'zoom_in'`) to callable methods.
*   **Direct-Key Mode Logic**: If `--no-searchbar` is active or `F2` is pressed, the app intercepts keys globally and strips `Ctrl` modifiers, allowing vim-like navigation without holding modifiers.

### D. Search, Filtering & Lazy Scanning
*   **Filtering**: `_on_search_change` and `_rebuild_visible` filter the file list in real-time based on the search bar input.
*   **Lazy Scanning**: `start_lazy_scan` runs a background thread to recursively scan directories. It yields batches of files to the main thread via `_queue_lazy_files` so the UI remains responsive even when scanning millions of files.

### E. Threading & Async Queue
*   **`_main_queue` & `_poll_main_queue`**: A thread-safe queue. Background threads (decoding images, scanning files) push callbacks to this queue. The main Tkinter thread polls it every 20ms (`QUEUE_POLL_MS`) to safely update the UI without race conditions.

### F. Sorting & File Management
*   **`_apply_sort`**: Sorts the file list by name, mtime, or size while preserving the current file index and aspect ratio caches.
*   **`remove_file`**: Removes a file from the internal list (useful for culling bad images) and updates indices.

### G. Image Rendering (Viewer Mode)
*   **`render_image`**: The core rendering loop for single images.
    *   Calculates zoom and pan boundaries (`_fit`, `_check_pan`).
    *   **Cropping**: Calculates the exact visible pixel region of the source image to avoid decoding/resizing the entire massive image in memory.
    *   **Color Adjustments**: `_prepare_crop` applies brightness, contrast, and gamma corrections using `PIL.ImageEnhance` and LUTs.
    *   Draws the cropped, resized, and adjusted image to the Tkinter `Canvas`.

### H. Gallery Rendering
*   **`_get_gallery_aspect`**: Auto-detects the median aspect ratio of the first N images in a background thread to ensure uniform grid tiles.
*   **`render_gallery`**: Calculates the grid layout (rows/cols based on window size and tile metrics). It only renders thumbnails currently visible on the screen (plus a small overscan buffer) to maintain 60fps scrolling.
*   **`_submit_gallery_tile`**: Pushes thumbnail decoding tasks to the `THUMB_WORKERS` thread pool.

### I. List Rendering
*   **`_populate_listbox`**: Efficiently inserts items into the Tkinter `Listbox` in chunks to prevent UI freezing.
*   **`render_list`**: Handles the side-by-side view: a list of filenames on the left, and a preview image on the right.

### J. Navigation & Actions
*   **Navigation**: `_navigate`, `_key_next`, `_key_prev`, `_key_nav` handle moving through the filtered/visible file list.
*   **Mode Cycling**: `_cycle_mode` switches between Image, Gallery, and List modes via `Tab`.
*   **Actions**: Methods like `act_zoom`, `act_rotate`, `act_flip`, `act_slideshow`, `act_toggle_mark` modify the state and trigger a `redraw()`.

### K. Mouse Events & Window Management
*   **`on_button`**: Handles mouse clicks. Left-click navigates or selects; Right-click marks files or opens the gallery; Scroll wheel zooms (image mode) or pans (gallery mode).
*   **`on_configure` / `_do_resize`**: Debounced window resize handler to recalculate layouts.
*   **`_poll_autoreload`**: Checks file modification times (`mtime`) every 500ms to automatically reload images if they are edited externally (e.g., in GIMP/Photoshop).

### L. Quit & Output
*   **`quit`**: Shuts down thread pools, destroys the Tkinter window, and handles the exit code.
*   **`_emit_output`**: In `select` mode, prints the marked files (or the current file) to `stdout`, allowing `tkiv` to be used in shell scripts and pipelines.

---

## 8. Entry Points & Execution
*   **`run_viewer`**: Parses `img` arguments, initializes the Tkinter `root`, creates the `TkivApp` instance, triggers lazy scanning if directories are passed, and starts `root.mainloop()`.
*   **`run_selector`**: Parses `select` arguments. Supports a special `--dmenu-mode` where it pairs text labels with image paths. Initializes the app as a floating, top-most dialog window.
*   **`main`**: The dispatcher. Reads `sys.argv[1]` to determine whether to launch `run_viewer()` or `run_selector()`.

---

## Summary of Architecture
`tkiv.py` is designed around **asynchronous responsiveness**. By offloading heavy I/O (disk scanning, image decoding, thumbnail generation) to `ThreadPoolExecutor` workers and communicating with the Tkinter main loop via a custom `queue.Queue`, it ensures the UI never freezes, even when handling massive directories or high-resolution images. Its dual-mode nature allows it to serve both as a daily-driver image viewer and a powerful tool for shell-scripting workflows.
