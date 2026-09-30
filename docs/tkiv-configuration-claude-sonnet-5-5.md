# tkiv Configuration Reference (v0.4.0)

`tkiv` is a single program with two modes:

| Mode | Command | Purpose |
|------|---------|---------|
| Viewer | `tkiv.py img [OPTIONS] FILES...` | nsxiv-like image viewer |
| Selector | `tkiv.py select [OPTIONS] PATHS...` | dmenu-like image picker |

Mode aliases: `img` = `view` = `viewer` = `pysxiv`; `select` = `sel` = `selector` = `sel_img`.

Configuration comes from three places:

1. [Command-line options](#1-command-line-options)
2. [The config file](#2-config-file) (`[keys]`, `[theme]`, `[behavior]`)
3. [Runtime toggles](#3-runtime-toggles-and-direct-key-mode) (key bindings, F2)

**Requirements:** Python 3, Tk, and `Pillow` (required). `pyvips` and `numpy` are optional but give faster decoding and thumbnails; without them tkiv warns (unless `-q`) and falls back to Pillow.

---

## 1. Command-line options

### 1.1 Options shared by `img` and `select`

| Option | Aliases | Argument | Default | Description |
|--------|---------|----------|---------|-------------|
| `-g` | `-t`, `--gallery`, `--thumbnail` | – | off | Start in gallery (thumbnail) mode |
| `-T N` | `--gallery-tile-size`, `--thumb-size` | int (px) | auto | Fixed gallery tile size |
| `--gallery-rows N` | | float | `3.5` | Target number of visible gallery rows |
| `--gallery-cols N` | | int | auto | Target number of visible gallery columns |
| `--gallery-aspect R` | | float | auto-detect | Tile width/height ratio (e.g. `1.777` for 16:9) |
| `--lazy` | | – | off | Show UI immediately and fill in files as they're found |
| `-r` | `--recursive` | – | off | Recurse into directories |
| `-H` | `--hidden` | – | off | Include hidden files/directories (names starting with `.`) |
| `--time` | | – | off | Sort scanned files by modification time, newest first |
| `--sort MODE` | | `none` `name` `mtime` `size` | `none` | Initial sort order (see below) |
| `-R` | `--sort-reverse` | – | off | Reverse the sort direction |
| `-n N` | `--start-at`, `--pass-idx` | int (1-based) | `1` | Start at file number N |
| `--name TITLE` | `--custom-title` | string | `tkiv` | Window title |
| `--idx-write-path FILE` | | path | – | Write the current (1-based) index to this file whenever it changes |
| `--pre-select LABELS` | | newline-separated string | – | Mark files whose label matches, at launch |
| `--pre-select-file FILE` | | path | – | Same as above, labels read from a file (one per line) |
| `--no-searchbar` | `--no-search`, `--direct-keys` | – | off | Start in direct-key mode (see [section 3](#3-runtime-toggles-and-direct-key-mode)) |
| `-q` | `--quiet` | – | off | Suppress warnings and error messages |
| `-v` | `--version` | – | – | Print version and exit |
| `-h` | `--help` | – | – | Print help and exit |

Notes:

- `--pre-select` and `--pre-select-file` are mutually exclusive (error if both given).
- `--sort` meanings: `none` = discovery order, `name` = A–Z, `mtime` = newest first, `size` = largest first. `-R` flips any of these.
- `--time` only affects how directories are scanned; `--sort mtime` is the interactive sort mode. They can be combined but `--sort` takes over once applied.
- `--lazy` with directories starts the scan in the background; non-directory arguments are added immediately.
- Abbreviated long options are **not** accepted (`allow_abbrev=False`): write `--gallery-rows`, not `--gallery-r`.

### 1.2 Viewer-only options (`img`)

| Option | Aliases | Argument | Default | Description |
|--------|---------|----------|---------|-------------|
| `-a` | `--animate` | – | off | Play animated images (GIF etc.) automatically |
| `-b` | `--no-bar` | – | off | Hide the status bar |
| `--bar` | | – | off | Force the status bar on (wins over `-b`) |
| `-f` | `--fullscreen` | – | off | Start fullscreen |
| `-G N` | `--gamma` | int | `0` | Initial gamma step |
| `--geometry GEOM` | | Tk geometry string | `900x700` | Window size/position, e.g. `1200x800+100+50`. Invalid values fall back to `900x700` |
| `-s MODE` | `--scale-mode` | `d` `f` `F` `w` `h` `z` | `d` | Initial scale mode (table below) |
| `-z N` | `--zoom` | int (percent) | `0` | Start at N% zoom (only if > 0) |
| `-Z` | `--zoom-100` | – | off | Start at 100% zoom (wins over `-z`) |
| `-S SEC` | `--ss-delay` | float (seconds) | `0` | Start a slideshow with this delay between images |
| `--anti-alias[=yes\|no]` | | optional value | `yes` | `--anti-alias=no` disables antialiasing |
| `--alpha-layer[=yes\|no]` | | optional value | off | Only `--alpha-layer=yes` enables the alpha layer (see note) |
| `-i` | `--stdin` | – | off | Read file names from stdin (also implied by a single `-` argument) |
| `-0` | `--null` | – | off | Use NUL instead of newline as the separator for stdin input and stdout output |
| `-o` | `--stdout` | – | off | On quit, print marked files (or the current file) to stdout |
| `--floating-window` | | – | off | Always-on-top dialog-style window, sized to screen minus 100px |
| `--assume-files` | | – | off | Treat all inputs as valid images; on decode failure show nothing instead of removing the file |
| `-N NAME` | `--legacy-name` | string | – | Legacy alias for `--name` |
| `--class NAME` | | string | – | **Deprecated**; prints a warning and is used as `--name` |

**Scale modes (`-s`):**

| Value | Meaning |
|-------|---------|
| `d` | Fit down: shrink to fit the window, never enlarge (default) |
| `f` | Fit: scale up or down to fit the window |
| `F` | Fill: scale so the image covers the window |
| `w` | Fit width |
| `h` | Fit height |
| `z` | Fixed zoom (use with `-z` / `-Z`) |

The value is not validated; an unrecognised mode behaves like `f`.

**Accepted but currently inert.** These options parse without error but nothing in the program reads them: `-A/--framerate`, `-e/--embed`, `-p/--private`, `-c/--clean-cache`, `--cache-allow`, `--cache-deny`, `--update-cache`. They exist for nsxiv command-line compatibility.

**Alpha-layer note:** because a bare `--alpha-layer` is stored as `no`, it doesn't enable anything. Use `--alpha-layer=yes`.

### 1.3 Selector-only options (`select`)

| Option | Argument | Description |
|--------|----------|-------------|
| `--dmenu-mode` | – | dmenu-style input: supply a list of labels and a matching list of image paths |
| `--list-file FILE` | path | File containing labels, one per line (dmenu mode) |
| `--list-entries TEXT` | newline-separated string | Labels given inline (dmenu mode) |
| `--image-file FILE` | path | File containing image paths, one per line (dmenu mode) |
| `--image-entries TEXT` | newline-separated string | Image paths given inline (dmenu mode) |
| `--return-label` | – | Print the label instead of the image path on accept |
| `PATHS...` | files/dirs | Images or directories to pick from (default: `.`) |

Rules for dmenu mode:

- You must give **exactly one** of `--list-file`/`--list-entries`, and **exactly one** of `--image-file`/`--image-entries`.
- The number of labels and image paths must match (they are paired line by line).
- Unreadable images are kept in the list (as with `--assume-files`).

Selector behaviour:

- **Return** accepts and prints results (exit status 0); **Esc** (with an empty filter) or closing the window cancels (exit status 1).
- If any file is marked, **all marked files** are printed, one per line. Otherwise the current file is printed.
- The window is always-on-top, dialog-style, and sized to the screen minus 100px.
- Selector mode takes the shared options (`-g`, `-T`, `--sort`, `--pre-select`, etc.). Viewer-only options such as `-s`, `-a`, `-o`, `-i` and `-0` are **not** recognised by `select` (argparse rejects them), so selector output is always newline-separated.

### 1.4 Command-line examples

```bash
# View all images in a directory, recursively, including hidden ones
tkiv.py img -rH ~/Pictures

# Open in gallery mode with 200px tiles
tkiv.py img -g -T 200 ~/Pictures

# Gallery with about 4 columns and 16:9 tiles
tkiv.py img -g --gallery-cols 4 --gallery-aspect 1.777 ~/Pictures

# Start at the 10th image, sorted newest first, fullscreen
tkiv.py img -f -n 10 --sort mtime ~/Pictures

# Oldest first
tkiv.py img --sort mtime -R ~/Pictures

# Fill mode at 100% zoom, no status bar
tkiv.py img -s z -Z -b photo.png

# Start a slideshow with 3 second delay
tkiv.py img -S 3 ~/Pictures

# Play animation automatically and set window geometry and title
tkiv.py img -a --geometry 1000x700+50+50 --name "Memes" gifs/*.gif

# Read names from stdin (newline-separated)
find . -name '*.jpg' | tkiv.py img -i

# Read names from stdin (NUL-separated, safe for odd file names)
find . -name '*.jpg' -print0 | tkiv.py img -i -0

# Print the files you marked when you quit
tkiv.py img -o ~/Pictures > chosen.txt

# Huge directory: show the UI immediately and scan in the background
tkiv.py img --lazy -r /mnt/photos

# Pre-mark some files by label (basename)
tkiv.py select --pre-select $'a.png\nb.png' ~/Pictures

# Pre-mark labels from a file
tkiv.py select --pre-select-file marked.txt ~/Pictures

# Start in direct-key mode (no Ctrl needed)
tkiv.py img --no-searchbar ~/Pictures

# Keep the current index in a file (useful for scripts)
tkiv.py img --idx-write-path /tmp/tkiv-idx ~/Pictures

# Pick a wallpaper with the selector, in gallery mode
wall=$(tkiv.py select -g -r ~/Pictures/wallpapers)

# Pick several files (Ctrl+M to mark, Return to accept)
tkiv.py select -g ~/Pictures | xargs -d '\n' -r cp -t ~/out/

# dmenu mode: labels paired with images, inline
tkiv.py select --dmenu-mode -g \
  --list-entries $'Sunset\nForest' \
  --image-entries $'/img/sunset.jpg\n/img/forest.jpg' \
  --return-label

# dmenu mode: labels and images from files
tkiv.py select --dmenu-mode -g --list-file labels.txt --image-file paths.txt
```

---

## 2. Config file

### 2.1 Location

```
$XDG_CONFIG_HOME/tkiv.py/config
~/.config/tkiv.py/config          # if XDG_CONFIG_HOME is unset/empty
```

The file is read once at startup and is shared by `img` and `select`. If it doesn't exist, defaults apply.

### 2.2 Format rules

- INI-like, with three optional sections: `[keys]`, `[theme]`, `[behavior]` (section names are case-insensitive).
- Entries are `name = value`.
- Blank lines and lines beginning with `#` are ignored.
- **Comments must be on their own line.** There is no inline-comment support: `next = Space  # comment` makes the value `Space  # comment`, which is invalid.
- A key before any section header is an error.
- **Any error discards the entire config** and tkiv runs with defaults. It prints `tkiv: config error: line N: ...; using defaults` to stderr. There is no partial loading.

### 2.3 `[keys]`: key bindings

Format: `action = Key Spec`

- Repeat a line with the same action to add **multiple bindings** for it.
- If an action appears in the config, its list **replaces** the default binding(s) for that action entirely. To keep the default and add another, list both.
- Actions you don't mention keep their defaults.

#### Key spec syntax

`Modifier+Modifier+Key`, joined by `+`.

**Modifiers** (case-insensitive): `Ctrl`/`Control`, `Shift`, `Alt`, `Meta`/`Cmd`/`Super`/`Command`.

**Keys:**

| Kind | Accepted names |
|------|----------------|
| Letters and digits | `a`–`z`, `0`–`9` (letters are case-insensitive) |
| Function keys | `F1`–`F12` |
| Whitespace/editing | `Space`, `Return`/`Enter`, `Escape`/`Esc`, `Tab`, `BackSpace`/`BS`, `Delete`/`Del`, `Insert`/`Ins` |
| Navigation | `Home`, `End`, `PageUp`/`PgUp`/`Prior`, `PageDown`/`PgDn`/`Next`, `Up`, `Down`, `Left`, `Right` |
| Misc | `Pause`, `Print` |
| Punctuation (name or symbol) | `Plus` or `+`, `Minus` or `-`, `Equal` or `=`, `BracketLeft` or `[`, `BracketRight` or `]`, `BraceLeft` or `{`, `BraceRight` or `}`, `ParenLeft` or `(`, `ParenRight` or `)`, `Less` or `<`, `Greater` or `>`, `Question` or `?`, `Bar` or `\|`, `Underscore` or `_` |
| Keypad | `KP_Add`, `KP_Subtract`, `KP_Enter`, `KP_Multiply`, `KP_Divide`, `KP_Decimal`, `KP_0`–`KP_9` |

Exactly one non-modifier key is allowed per spec. `Ctrl++` works (Ctrl and the plus key). Unknown multi-character names are errors.

#### All actions and their defaults

| Action | Default | What it does |
|--------|---------|--------------|
| `quit` | `Ctrl+Q` | Quit (selector: cancel, status 0 in this binding; see note below) |
| `toggle_bar` | `Ctrl+B` | Toggle the status bar |
| `toggle_searchbar` | `F2` | Toggle search bar / direct-key mode |
| `fullscreen` | `Ctrl+F` | Toggle fullscreen |
| `reload` | `Ctrl+R` | Reload the current image |
| `remove` | `Ctrl+D` | Remove current file from the list (or all marked files) |
| `next` | `Ctrl+N` | Next file (respects the filter) |
| `prev` | `Ctrl+P` | Previous file |
| `nav_10_forward` | `Ctrl+BracketRight` | Jump +10 files |
| `nav_10_back` | `Ctrl+BracketLeft` | Jump −10 files |
| `first` | `Ctrl+G` | First file (`Home` key is always bound too) |
| `toggle_mark` | `Ctrl+M` | Mark/unmark the current file |
| `unmark_all` | `Ctrl+U` | Clear all marks |
| `fit_down` | `Ctrl+W` | Scale mode: fit down (shrink only) |
| `fit` | `Ctrl+Shift+W` | Scale mode: fit |
| `fill` | `Ctrl+Shift+F` | Scale mode: fill |
| `fit_width` | `Ctrl+E` | Scale mode: fit width |
| `fit_height` | `Ctrl+Shift+E` | Scale mode: fit height |
| `zoom_in` | `Ctrl+Plus` | Zoom in (image) / larger tiles (gallery) |
| `zoom_out` | `Ctrl+Minus` | Zoom out / smaller tiles |
| `zoom_100` | `Ctrl+0` | 100% zoom |
| `center` | `Ctrl+Z` | Center the image |
| `pan_left` | `Ctrl+H` | Pan left |
| `pan_down` | `Ctrl+J` | Pan down |
| `pan_up` | `Ctrl+K` | Pan up |
| `pan_right` | `Ctrl+L` | Pan right |
| `animate` | `Ctrl+Space` | Toggle animation |
| `slideshow` | `Ctrl+S` | Toggle slideshow |
| `rotate_left` | `Ctrl+Less` | Rotate 90° counter-clockwise |
| `rotate_right` | `Ctrl+Greater` | Rotate 90° clockwise |
| `rotate_180` | `Ctrl+Question` | Rotate 180° |
| `flip_h` | `Ctrl+Bar` | Flip horizontally |
| `flip_v` | `Ctrl+Underscore` | Flip vertically |
| `toggle_antialias` | `Ctrl+I` | Toggle antialiasing |
| `toggle_alpha` | `Ctrl+Shift+I` | Toggle alpha layer |
| `contrast_down` | `Ctrl+ParenLeft` | Decrease contrast |
| `contrast_up` | `Ctrl+ParenRight` | Increase contrast |
| `gamma_down` | `Ctrl+BraceLeft` | Decrease gamma |
| `gamma_up` | `Ctrl+BraceRight` | Increase gamma |
| `sort_cycle` | `Ctrl+Y` | Cycle sort: name↑, name↓, mtime↑, mtime↓, size↑, size↓ |
| `sort_reverse` | `Ctrl+Shift+Y` | Reverse the current sort direction |

Note on `quit`: the `quit` action calls the quit routine with status 0, so in selector mode it **prints the selection** like Return does. To cancel without output use Esc or close the window.

#### Fixed (non-configurable) keys

| Key | Action |
|-----|--------|
| Arrow keys | Pan (image) / move selection (gallery, list) |
| `PageUp` / `PageDown` | Page up / down |
| `Home` / `End` | First / last file |
| `Tab` / `Shift+Tab` | Cycle mode: image → gallery → list (reverse with Shift) |
| `Return` / `KP_Enter` | Image ↔ gallery; list → image. In selector: accept |
| `Esc` | Clear the filter if any; otherwise quit (selector: cancel, exit status 1) |
| `Delete` | Remove current/marked file(s) |
| `Ctrl+Return` | Toggle mark (search-bar mode only) |

Mouse: in image mode, left click on the left/right third goes previous/next, right click opens gallery, wheel zooms. In gallery mode, left click selects a tile (Ctrl+left click marks in selector mode), right click marks, wheel scrolls.

#### `[keys]` examples

```ini
[keys]
# Add a second binding for "next" (keep Ctrl+N too)
next = Ctrl+N
next = Space

prev = Ctrl+P
prev = BackSpace

# Replace the default quit key
quit = Ctrl+W
# (this also frees Ctrl+Q; note fit_down still defaults to Ctrl+W,
#  so rebind it as well to avoid a conflict)
fit_down = Ctrl+Shift+D

# Function and keypad keys
fullscreen = F11
zoom_in = KP_Add
zoom_out = KP_Subtract

# Symbols can be written literally
rotate_right = Ctrl+>
rotate_left  = Ctrl+<

# Vim-ish panning with Alt
pan_left  = Alt+H
pan_down  = Alt+J
pan_up    = Alt+K
pan_right = Alt+L
```

### 2.4 `[theme]`: colors

Format: `key = #RRGGBB` (exactly six hex digits, with the `#`; 3-digit or named colors are errors).

| Key | Default (Nord palette) | Used for |
|-----|------------------------|----------|
| `bg_primary` | `#2e3440` | Main background, canvas, gallery and scrollbar trough |
| `bg_secondary` | `#3b4252` | Panels, list box, status/scrollbar surfaces, gallery borders |
| `bg_input` | `#4c566a` | Search entry background |
| `fg_text` | `#d8dee9` | Normal text, captions |
| `fg_bright` | `#eceff4` | Emphasised text (e.g. filename in list view) |
| `accent` | `#88c0d0` | Marks, selection border, search-entry focus highlight |
| `accent_fg` | `#2e3440` | Text drawn on accent-colored areas |
| `selected_bg` | `#5e81ac` | Selected row/tile background |
| `selected_fg` | `#eceff4` | Selected row/tile text |
| `hover_border` | `#4c566a` | Border of unselected gallery tiles |

```ini
[theme]
# Gruvbox dark
bg_primary   = #282828
bg_secondary = #3c3836
bg_input     = #504945
fg_text      = #ebdbb2
fg_bright    = #fbf1c7
accent       = #fabd2f
accent_fg    = #282828
selected_bg  = #458588
selected_fg  = #fbf1c7
hover_border = #504945
```

You may set just the keys you want to change; the rest keep their defaults.

### 2.5 `[behavior]`: tunables

Both values must be positive integers.

| Key | Default | Description |
|-----|---------|-------------|
| `slideshow_delay` | `5` | Seconds between slideshow frames (used when `-S` isn't given) |
| `max_load_dim` | `4096` | Largest width/height, in pixels, that an image is decoded at. Larger images are downscaled on load (requires pyvips). Raise it for zooming into big images; lower it to save memory |

```ini
[behavior]
slideshow_delay = 10
max_load_dim = 8192
```

### 2.6 Complete example config

```ini
# ~/.config/tkiv.py/config

[keys]
next = Ctrl+N
next = Space
prev = Ctrl+P
prev = BackSpace
fullscreen = F11
zoom_in = KP_Add
zoom_out = KP_Subtract

[theme]
bg_primary   = #1e1e2e
bg_secondary = #313244
accent       = #f5c2e7
selected_bg  = #585b70

[behavior]
slideshow_delay = 8
max_load_dim = 6144
```

### 2.7 Common config errors

| Message | Cause |
|---------|-------|
| `unknown section [foo]` | Only `keys`, `theme`, `behavior` are valid |
| `key outside of any section` | An entry appears before the first `[section]` |
| `expected 'key = value'` | A line without `=` (and not a comment/section) |
| `unknown action 'xyz'` | Action name not in the table above (names are case-sensitive) |
| `invalid key sequence '...'` | Bad key name, two non-modifier keys, or a trailing inline comment |
| `unknown theme key` / `invalid color` | Misspelled key, or color not in `#RRGGBB` form |
| `unknown behavior` / `must be an integer` / `must be positive` | Bad `[behavior]` entry |

---

## 3. Runtime toggles and direct-key mode

By default the **search bar is always focused** at the bottom of the window. Typing filters files by label/path (all space-separated terms must match, case-insensitive), and every action uses `Ctrl+`.

**Direct-key mode** hides the search bar and rebinds each configurable action to its plain key:

- `Ctrl+<letter>` → `<letter>` (e.g. `Ctrl+N` → `n`)
- `Ctrl+Shift+<letter>` → `Shift+<letter>` (e.g. `Ctrl+Shift+W` → `W`)
- `Ctrl+Plus` → `plus`, `Ctrl+0` → `0`, `Ctrl+Space` → `space`, and so on
- Function keys (`F2`) stay as they are
- Fixed navigation keys behave the same
- Filtering is unavailable and any active filter is cleared

Enable it with `--no-searchbar` at launch or press **F2** at any time (F2 again switches back). The key bound to `toggle_searchbar` can be changed in `[keys]`.

Since the direct-key mapping is derived from your `[keys]` entries, a custom binding like `next = Alt+J` becomes plain `j` in direct-key mode.

---

## 4. Files, environment and cache

| Item | Location / variable |
|------|---------------------|
| Config file | `$XDG_CONFIG_HOME/tkiv.py/config` (fallback `~/.config/tkiv.py/config`) |
| Thumbnail cache (WebP, quality 82) | `$XDG_CACHE_HOME/tkiv_thumbs` (fallback `~/.cache/tkiv_thumbs`) |
| Supported extensions | `.jpg .jpeg .jpe .jfif .png .gif .bmp .tiff .tif .webp .ppm .pgm .pbm .pnm .ico .pcx .tga .xpm .jp2 .j2k .avif .heic .heif` |

The thumbnail cache is keyed on path, modification time, size and tile dimensions, so edited files are regenerated automatically. It can be cleared by deleting the directory. `--clean-cache`/`--update-cache` don't do anything in this version.

Hard-coded values that are *not* configurable (source constants): zoom steps `12.5% … 800%`, gallery tile limits 96–512 px, 4 decode workers and 4 thumbnail workers, prefetch of 3 images.

---

## 5. Exit status

| Situation | Status |
|-----------|--------|
| Viewer quit normally | `0` |
| Selector accepted (Return / `quit` action) | `0` |
| Selector cancelled (Esc, window closed) | `1` |
| No valid images / cannot open display / bad dmenu arguments | `1` |
