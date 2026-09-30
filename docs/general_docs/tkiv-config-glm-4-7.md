# Configuration Guide for `tkiv`

`tkiv` allows for extensive customization through a configuration file. This includes remapping keybindings, changing the UI theme, and adjusting specific behavioral parameters.

---

## 📁 Configuration File Location

The configuration file is loaded from:
`~/.config/tkiv.py/config`

You can override this location by setting the `$XDG_CONFIG_HOME` environment variable:
`$XDG_CONFIG_HOME/tkiv.py/config`

If the file does not exist, `tkiv` uses built-in defaults. If any syntax error is found in the file, **the entire configuration file is discarded** and defaults are used.

---

## 📝 File Format

The configuration file uses an INI-like format. It can contain up to three optional sections:
- `[keys]` - For remapping actions to key sequences.
- `[theme]` - For customizing UI colors.
- `[behavior]` - For tweaking program logic and limits.

Comments are supported using `#` at the beginning of a line.

---

## 🎹 Section: `[keys]`

This section allows you to remap actions to specific key sequences. 
You can assign multiple keybindings to a single action by specifying it on multiple lines.

### Key Syntax
Bindings use a human-friendly syntax: `Modifier+Key`.
- **Modifiers:** `Ctrl` (or `Control`), `Shift`, `Alt`, `Meta` (or `Cmd`, `Super`, `Command`). Combine multiple modifiers with `+` (e.g., `Ctrl+Shift+W`).
- **Letters/Digits:** Single characters (e.g., `Q`, `1`). Letters are case-insensitive in combination with modifiers.
- **Special Keys:** `Space`, `Plus` (or `+`), `Minus` (or `-`), `Equal` (or `=`), `BracketLeft` (`[`), `BracketRight` (`]`), `BraceLeft` (`{`), `BraceRight` (`}`), `ParenLeft` (`(`), `ParenRight` (`)`), `Less` (`<`), `Greater` (`>`), `Question` (`?`), `Bar` (`|`), `Underscore` (`_`).
- **Navigation Keys:** `Return` (or `Enter`), `Escape` (or `Esc`), `Tab`, `BackSpace` (or `Bs`), `Delete` (or `Del`), `Home`, `End`, `PageUp` (or `PgUp`), `PageDown` (or `PgDn`), `Up`, `Down`, `Left`, `Right`, `Insert` (or `Ins`).
- **Function Keys:** `F1` through `F12`.

*Note: You define bindings for the default "search bar" mode. If you launch with `--no-searchbar` (or press F2 to toggle direct-key mode), `tkiv` will automatically strip the Ctrl/Alt/Meta modifiers and apply Shift as uppercase for you.*

### Configurable Actions & Defaults

| Action | Default Binding | Description |
| :--- | :--- | :--- |
| `quit` | `Ctrl+Q` | Quit the program. |
| `toggle_bar` | `Ctrl+B` | Toggle the status bar. |
| `remove` | `Ctrl+D` | Remove current file (or all marked files). |
| `fit_width` | `Ctrl+E` | Fit image to width. |
| `fullscreen` | `Ctrl+F` | Toggle fullscreen. |
| `first` | `Ctrl+G` | Jump to the first file. |
| `pan_left` | `Ctrl+H` | Pan image left. |
| `toggle_antialias` | `Ctrl+I` | Toggle antialiasing. |
| `pan_down` | `Ctrl+J` | Pan image down. |
| `pan_up` | `Ctrl+K` | Pan image up. |
| `pan_right` | `Ctrl+L` | Pan image right. |
| `toggle_mark` | `Ctrl+M` | Toggle mark on current file. |
| `next` | `Ctrl+N` | Next file (respects filter). |
| `prev` | `Ctrl+P` | Previous file (respects filter). |
| `reload` | `Ctrl+R` | Reload current image/file list. |
| `slideshow` | `Ctrl+S` | Toggle slideshow mode. |
| `unmark_all` | `Ctrl+U` | Unmark all files. |
| `fit_down` | `Ctrl+W` | Fit down (scale 100% max). |
| `sort_cycle` | `Ctrl+Y` | Cycle sort mode (name/date/size). |
| `center` | `Ctrl+Z` | Center image in the viewport. |
| `animate` | `Ctrl+Space` | Toggle animation for multi-frame images. |
| `zoom_100` | `Ctrl+0` | Zoom to 100%. |
| `zoom_in` | `Ctrl+Plus` | Zoom in. |
| `zoom_out` | `Ctrl+Minus` | Zoom out. |
| `nav_10_forward` | `Ctrl+BracketRight` | Jump +10 files. |
| `nav_10_back` | `Ctrl+BracketLeft` | Jump -10 files. |
| `gamma_down` | `Ctrl+BraceLeft` | Decrease gamma. |
| `gamma_up` | `Ctrl+BraceRight` | Increase gamma. |
| `contrast_down` | `Ctrl+ParenLeft` | Decrease contrast. |
| `contrast_up` | `Ctrl+ParenRight` | Increase contrast. |
| `rotate_left` | `Ctrl+Less` | Rotate 90° left. |
| `rotate_right` | `Ctrl+Greater` | Rotate 90° right. |
| `rotate_180` | `Ctrl+Question` | Rotate 180°. |
| `flip_h` | `Ctrl+Bar` | Flip horizontally. |
| `flip_v` | `Ctrl+Underscore` | Flip vertically. |
| `fit` | `Ctrl+Shift+W` | Fit to window. |
| `fill` | `Ctrl+Shift+F` | Fill window (scale to cover). |
| `fit_height` | `Ctrl+Shift+E` | Fit to height. |
| `toggle_alpha` | `Ctrl+Shift+I` | Toggle alpha/transparency layer. |
| `sort_reverse` | `Ctrl+Shift+Y` | Reverse sort direction. |
| `toggle_searchbar` | `F2` | Toggle search bar / direct-key mode. |

### Example `[keys]`
```ini
[keys]
# Quit using Escape instead of Ctrl+Q
quit = Escape

# Bind next/prev to Vim-style keys
next = Ctrl+J
prev = Ctrl+K

# Bind next/prev to Ctrl+N / Ctrl+P AND Alt+Down / Alt+Up 
# (Demonstrates multiple bindings for a single action)
next = Ctrl+N
next = Alt+Down
prev = Ctrl+P
prev = Alt+Up
```

---

## 🎨 Section: `[theme]`

This section customizes the UI colors. Colors must be provided in 6-digit hex format (`#RRGGBB`).

### Configurable Colors & Defaults

| Color Key | Default | Description |
| :--- | :--- | :--- |
| `bg_primary` | `#2e3440` | Main background (canvas, window). |
| `bg_secondary` | `#3b4252` | Secondary background (listbox, scrollbars). |
| `bg_input` | `#4c566a` | Search bar input background. |
| `fg_text` | `#d8dee9` | Primary text color (status bar, captions). |
| `fg_bright` | `#eceff4` | Bright text color (list filename header). |
| `accent` | `#88c0d0` | Accent color (mark indicator, search highlight). |
| `accent_fg` | `#2e3440` | Text color drawn on top of the accent color. |
| `selected_bg` | `#5e81ac` | Background color for selected list items. |
| `selected_fg` | `#eceff4` | Text color for selected list items. |
| `hover_border` | `#4c566a` | Border color for gallery tiles on hover. |

### Example `[theme]`
```ini
[theme]
# A light theme configuration
bg_primary = #f0f0f0
bg_secondary = #e0e0e0
bg_input = #ffffff
fg_text = #333333
fg_bright = #000000
accent = #005577
accent_fg = #ffffff
selected_bg = #007acc
selected_fg = #ffffff
hover_border = #cccccc
```

---

## ⚙️ Section: `[behavior]`

This section adjusts underlying application limits and timings. Values must be positive integers.

### Configurable Behaviors & Defaults

| Setting | Default | Description |
| :--- | :--- | :--- |
| `slideshow_delay` | `5` | Seconds between frames when slideshow mode is active. |
| `max_load_dim` | `4096` | Maximum dimension (width or height) for full image decoding. Images larger than this will be downscaled upon loading to save memory. |

### Example `[behavior]`
```ini
[behavior]
# Speed up the slideshow
slideshow_delay = 2

# Allow loading extremely large 8K images (might use a lot of RAM!)
max_load_dim = 8192
```

---

## 📄 Full Example Config File

Here is a complete example demonstrating all sections, which you can save as `~/.config/tkiv.py/config`:

```ini
# tkiv configuration file

[behavior]
# Decrease slideshow delay to 2 seconds
slideshow_delay = 2

[theme]
# Nord-inspired dark theme (these are the defaults, shown for reference)
bg_primary   = #2e3440
bg_secondary = #3b4252
bg_input     = #4c566a
fg_text      = #d8dee9
fg_bright    = #eceff4
accent       = #88c0d0
accent_fg    = #2e3440
selected_bg  = #5e81ac
selected_fg  = #eceff4
hover_border = #4c566a

[keys]
# Remap quit to Ctrl+C (in addition to default Ctrl+Q)
quit = Ctrl+C

# Add Escape as a secondary quit option
quit = Escape

# Make rotation use R and Shift+R (which maps to Ctrl+R and Ctrl+Shift+R in searchbar mode)
rotate_left = Ctrl+R
rotate_right = Ctrl+Shift+R

# Use Ctrl+D for delete/remove (overwriting default 'remove' binding just to show how)
remove = Ctrl+D

# Rebind zooming to bracket keys
zoom_in = Ctrl+BracketRight
zoom_out = Ctrl+BracketLeft
```
