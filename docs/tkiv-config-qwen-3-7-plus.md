# `tkiv` Configuration Guide

This document details all the configuration options available for `tkiv`. 

## Configuration File Location & Format

By default, `tkiv` looks for its configuration file at:
* `~/.config/tkiv.py/config`
* `$XDG_CONFIG_HOME/tkiv.py/config` (if `$XDG_CONFIG_HOME` is set)

**Format:** The file uses an INI-like format with three optional sections: `[keys]`, `[theme]`, and `[behavior]`. 
* Lines starting with `#` are treated as comments.
* **Strict Parsing:** If there is *any* syntax error in the configuration file (e.g., invalid hex color, unknown action name, missing `=`), the **entire configuration is discarded**, and `tkiv` will fall back to its built-in defaults.

---

## 1. `[keys]` Section: Keybindings

This section allows you to remap keyboard shortcuts to specific actions. You can assign multiple keybindings to a single action by repeating the action name.

### Key Syntax
Bindings use a human-friendly syntax: `Modifier+Key` or just `Key`.
* **Modifiers:** `Ctrl`, `Shift`, `Alt`, `Meta` (also accepts `Cmd`, `Super`, `Command`).
* **Special Keys:** `Space`, `Plus`, `Minus`, `Return`, `Escape`, `Tab`, `Delete`, `Home`, `End`, `Up`, `Down`, `Left`, `Right`, `F1` through `F12`.
* **Symbols:** You can use the symbol itself or its name (e.g., `[` or `BracketLeft`, `]` or `BracketRight`, `<` or `Less`).

### Available Actions & Defaults
Below is the complete list of configurable actions and their default bindings:

| Action | Default Binding | Description |
| :--- | :--- | :--- |
| `quit` | `Ctrl+Q` | Quit the application |
| `toggle_bar` | `Ctrl+B` | Toggle the status bar |
| `toggle_searchbar` | `F2` | Toggle search bar / direct-key mode |
| `remove` | `Ctrl+D` | Remove current file (or all marked files) |
| `fullscreen` | `Ctrl+F` | Toggle fullscreen mode |
| `reload` | `Ctrl+R` | Reload the current image |
| `next` | `Ctrl+N` | Next image (respects filter) |
| `prev` | `Ctrl+P` | Previous image (respects filter) |
| `first` | `Ctrl+G` | Go to the first image |
| `nav_10_forward` | `Ctrl+]` | Skip forward 10 files |
| `nav_10_back` | `Ctrl+[` | Skip backward 10 files |
| `toggle_mark` | `Ctrl+M` | Toggle mark on current image |
| `unmark_all` | `Ctrl+U` | Remove marks from all images |
| `fit` | `Ctrl+Shift+W` | Fit image to window |
| `fit_down` | `Ctrl+W` | Fit down (shrink to fit) |
| `fill` | `Ctrl+Shift+F` | Fill window (crop to fit) |
| `fit_width` | `Ctrl+E` | Fit to width |
| `fit_height` | `Ctrl+Shift+E` | Fit to height |
| `zoom_in` | `Ctrl++` | Zoom in |
| `zoom_out` | `Ctrl+-` | Zoom out |
| `zoom_100` | `Ctrl+0` | Reset to 100% zoom |
| `center` | `Ctrl+Z` | Center the image |
| `pan_left` | `Ctrl+H` | Pan left |
| `pan_down` | `Ctrl+J` | Pan down |
| `pan_up` | `Ctrl+K` | Pan up |
| `pan_right` | `Ctrl+L` | Pan right |
| `animate` | `Ctrl+Space` | Toggle GIF/animation playback |
| `slideshow` | `Ctrl+S` | Toggle slideshow mode |
| `rotate_left` | `Ctrl+<` | Rotate 90° counter-clockwise |
| `rotate_right` | `Ctrl+>` | Rotate 90° clockwise |
| `rotate_180` | `Ctrl+?` | Rotate 180° |
| `flip_h` | `Ctrl+\|` | Flip horizontally |
| `flip_v` | `Ctrl+_` | Flip vertically |
| `toggle_antialias`| `Ctrl+I` | Toggle anti-aliasing |
| `toggle_alpha` | `Ctrl+Shift+I` | Toggle alpha checkerboard background |
| `contrast_down` | `Ctrl+(` | Decrease contrast |
| `contrast_up` | `Ctrl+)` | Increase contrast |
| `gamma_down` | `Ctrl+{` | Decrease gamma |
| `gamma_up` | `Ctrl+}` | Increase gamma |
| `sort_cycle` | `Ctrl+Y` | Cycle sort order (name/date/size) |
| `sort_reverse` | `Ctrl+Shift+Y` | Reverse current sort direction |

### Examples
```ini
[keys]
# Use 'Space' to go to the next image
next = Space

# Bind multiple keys to the same action
next = Ctrl+N
next = Right

# Use Vim-style keys for panning (requires direct-key mode or Ctrl)
pan_left = Ctrl+H
pan_down = Ctrl+J
pan_up = Ctrl+K
pan_right = Ctrl+L

# Custom quit key
quit = Escape
```

---

## 2. `[theme]` Section: Colors

This section allows you to customize the UI colors. All colors **must** be valid 6-digit hexadecimal codes (e.g., `#RRGGBB`). 3-digit hex codes or named colors (like `red`) will cause a syntax error.

### Available Theme Keys & Defaults
`tkiv` uses a Nord-inspired dark theme by default.

| Key | Default Hex | Description |
| :--- | :--- | :--- |
| `bg_primary` | `#2e3440` | Main background color (Image canvas, UI base) |
| `bg_secondary` | `#3b4252` | Secondary background (Status bar, Listbox, Scrollbars) |
| `bg_input` | `#4c566a` | Search bar input background |
| `fg_text` | `#d8dee9` | Primary text color (Status bar, Listbox text, Captions) |
| `fg_bright` | `#eceff4` | Bright text color (Listbox filenames) |
| `accent` | `#88c0d0` | Accent color (Selected gallery border, Marks, Search highlight) |
| `accent_fg` | `#2e3440` | Text color when placed on top of the accent color |
| `selected_bg` | `#5e81ac` | Background color for selected items (Listbox, Marked files) |
| `selected_fg` | `#eceff4` | Text color for selected items |
| `hover_border` | `#4c566a` | Border color for unselected gallery thumbnails |

### Examples
```ini
[theme]
# A custom "Light Mode" theme
bg_primary    = #ffffff
bg_secondary  = #f0f0f0
bg_input      = #e0e0e0
fg_text       = #333333
fg_bright     = #000000
accent        = #0066cc
accent_fg     = #ffffff
selected_bg   = #cce5ff
selected_fg   = #000000
hover_border  = #cccccc
```

---

## 3. `[behavior]` Section: Application Logic

This section controls internal application behaviors. Values must be **positive integers**.

### Available Behavior Keys & Defaults

| Key | Default | Description |
| :--- | :--- | :--- |
| `slideshow_delay` | `5` | Time in seconds between slides during a slideshow. |
| `max_load_dim` | `4096` | Maximum dimension (width or height in pixels) for full image decoding. Images larger than this will be downscaled upon loading to save memory. |

### Examples
```ini
[behavior]
# Set slideshow to advance every 3 seconds
slideshow_delay = 3

# Allow loading massive images up to 8K resolution (8192px)
max_load_dim = 8192
```

---

## Complete Example Configuration

Here is a full, valid configuration file combining all sections. You can copy and paste this into `~/.config/tkiv.py/config`:

```ini
# tkiv configuration file

[keys]
# Add Space as an alternative for Next
next = Space
# Use 'q' to quit in direct-key mode (F2)
quit = q
# Custom sorting shortcut
sort_cycle = Ctrl+Shift+S

[theme]
# Nord Aurora inspired theme
bg_primary    = #2e3440
bg_secondary  = #3b4252
bg_input      = #434c5e
fg_text       = #d8dee9
fg_bright     = #eceff4
accent        = #b48ead
accent_fg     = #2e3440
selected_bg   = #5e81ac
selected_fg   = #eceff4
hover_border  = #4c566a

[behavior]
slideshow_delay = 4
max_load_dim    = 4096
```
