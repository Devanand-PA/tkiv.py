# Tkiv.py Image Viewer and Image Selector

A slightly bloated image viewer and dmenu alternative written in python.

<https://github.com/user-attachments/assets/812fb912-bd25-425a-804d-cdbec0fe7d8b>



**Version documented:** `0.4.0`

`tkiv.py` is a single Python/Tkinter program that combines an image viewer
with an interactive image selector. It has three visual
modes---**image**, **gallery**, and **list**---and can operate either as
a normal viewer or as a dmenu-like selector whose result is printed to
stdout.

This document is based on the complete `tkiv.py` source, including
its CLI parsers, event bindings, configuration parser, rendering code,
selector entry point, and dispatcher.

------------------------------------------------------------------------

## 1. Synopsis

``` text
tkiv img    [OPTIONS] FILES...
tkiv select [OPTIONS] PATHS...
```

The dispatcher also accepts aliases:

``` text
tkiv view
tkiv viewer
tkiv pysxiv

tkiv sel
tkiv selector
tkiv sel_img
```

The canonical forms are `img` and `select`.

Running the program without a mode prints the top-level usage message.
`-h`/`--help` at the top level also shows the two modes.

------------------------------------------------------------------------

## 2. Dependencies

The program requires:

-   Python 3
-   Tkinter
-   Pillow

Pillow is mandatory. If it cannot be imported, the program exits with:

``` text
Error: Pillow is required. Install with: pip install Pillow
```

`pyvips` and `numpy` are optional. When both are available, they are
used for image loading and thumbnail generation in several paths.
Without `pyvips`, `tkiv` falls back to Pillow and prints a warning
unless `--quiet` is used.

A typical setup is therefore:

``` bash
pip install Pillow
```

and optionally:

``` bash
pip install pyvips numpy
```

The program also requires an available graphical display because it
creates a Tk window.

------------------------------------------------------------------------

# 3. Viewer mode

## 3.1 Basic usage

Open one image:

``` bash
tkiv img image.jpg
```

Open several images:

``` bash
tkiv img image1.jpg image2.jpg image3.jpg
```

Open every supported image directly inside a directory:

``` bash
tkiv img ~/Pictures
```

Search directories recursively:

``` bash
tkiv img -r ~/Pictures
```

Include hidden files:

``` bash
tkiv img -r -H ~/Pictures
```

Start in gallery mode:

``` bash
tkiv img -g ~/Pictures
```

Start in list mode:

``` bash
tkiv img -l ~/Pictures
```

Start fullscreen:

``` bash
tkiv img -f image.jpg
```

Use a custom window title:

``` bash
tkiv img --name "Reference Images" ~/Pictures
```

------------------------------------------------------------------------

# 4. Image formats

Directory scanning recognizes files whose extensions are:

``` text
.jpg
.jpeg
.png
.gif
.bmp
.tiff
.tif
.webp
.ppm
.pgm
.pbm
.pnm
.ico
.jpe
.jfif
.pcx
.tga
.xpm
.jp2
.j2k
.avif
.heic
.heif
```

The extension test is case-insensitive.

When explicit files are supplied, the viewer does not require one of
these extensions; it attempts to load the supplied path.

------------------------------------------------------------------------

# 5. Viewer command-line options

## 5.1 Animation

### `-a`, `--animate`

Start animated images with animation enabled.

``` bash
tkiv img --animate animation.gif
```

Animation can subsequently be toggled with `Ctrl+Space`.

### `-A FRAMERATE`, `--framerate FRAMERATE`

This option is accepted by the CLI, but the current source does not use
the supplied value when scheduling animation. Animation timing comes
from the image's frame durations, with a fallback of 75 ms.

Therefore:

``` bash
tkiv img -A 30 animation.gif
```

is accepted, but `30` does not currently override the actual animation
timing.

------------------------------------------------------------------------

## 5.2 Status bar

### `-b`, `--no-bar`

Start with the status bar hidden.

``` bash
tkiv img -b image.jpg
```

### `--bar`

Explicitly request the status bar.

If both `--no-bar` and `--bar` are supplied, `--bar` wins because the
initial value is effectively:

``` text
show_bar = (not no_bar) or bar
```

The status bar can always be toggled at runtime with `Ctrl+B`.

------------------------------------------------------------------------

## 5.3 Window behavior

### `-f`, `--fullscreen`

Start fullscreen.

``` bash
tkiv img -f image.jpg
```

Runtime toggle:

``` text
Ctrl+F
```

### `--floating-window`

Makes the window topmost and attempts to set the X11 window type to
`dialog`. The window is also positioned near the screen edges and given
a minimum size.

This is primarily useful when launching the viewer as a floating
utility.

``` bash
tkiv img --floating-window image.jpg
```

### `--geometry GEOMETRY`

Passes the supplied Tk geometry directly to the window.

Example:

``` bash
tkiv img --geometry 1200x800+100+50 image.jpg
```

If Tk rejects the geometry, the program falls back to `900x700`.

### `--name NAME`, `--custom-title NAME`

Set the window title.

``` bash
tkiv img --name "Wallpapers" ~/Pictures/Wallpapers
```

### `-N NAME`, `--legacy-name NAME`

Legacy spelling for the window title.

### `--class CLASS`

Deprecated. The source prints a warning recommending `--name`.

If `--name` was not also supplied, the class value is used as the window
title.

------------------------------------------------------------------------

## 5.4 Full-image loading

### `--assume-files`

Treat supplied files as trusted. If an image cannot be decoded, the
viewer does not automatically remove the failing entry from the file
list.

This is particularly useful for selector-generated lists where the paths
have already been validated.

``` bash
tkiv img --assume-files image1.jpg image2.jpg
```

------------------------------------------------------------------------

## 5.5 Cache-related options

The CLI accepts:

``` text
-c, --clean-cache
--cache-allow VALUE
--cache-deny VALUE
--update-cache
```

However, the current source does not consume these parsed options after
argument parsing. They therefore do not currently implement the cache
controls their names suggest.

The actual thumbnail cache is described in [Thumbnail
caching](#thumbnail-caching).

------------------------------------------------------------------------

## 5.6 Embedded-window option

### `-e WID`, `--embed WID`

The argument is parsed and stored, but the current implementation does
not use it to embed the Tk window into another window.

It should therefore be regarded as an accepted-but-currently-unused
compatibility option.

------------------------------------------------------------------------

## 5.7 Initial gamma

### `-G GAMMA`, `--gamma GAMMA`

Set the initial gamma adjustment step.

``` bash
tkiv img --gamma 4 image.jpg
```

The internal gamma state is clamped to ±32 when changed interactively.
The rendering maps the internal value onto a gamma range whose maximum
is 10.

The runtime bindings are:

``` text
Ctrl+{    decrease gamma
Ctrl+}    increase gamma
```

------------------------------------------------------------------------

## 5.8 Input from stdin

### `-i`, `--stdin`

Read image paths from standard input.

``` bash
printf '%s\n' ~/Pictures/a.jpg ~/Pictures/b.jpg |
    tkiv img --stdin
```

Newline is the default separator.

The same behavior is automatically enabled when the only positional
argument is `-`:

``` bash
printf '%s\n' image1.jpg image2.jpg | tkiv img -
```

### `-0`, `--null`

Use NUL characters instead of newlines when reading from stdin.

``` bash
find ~/Pictures -type f -print0 |
    tkiv img --stdin --null
```

This is also used for stdout output when `--stdout` is enabled.

------------------------------------------------------------------------

## 5.9 Standard output

### `-o`, `--stdout`

On successful exit, output the currently marked files, or the current
file if nothing is marked.

``` bash
tkiv img --stdout ~/Pictures
```

The output is one path per line unless `--null` is also supplied.

For example:

``` bash
selected=$(tkiv img --stdout ~/Pictures)
```

or for NUL-safe processing:

``` bash
tkiv img --stdout --null ~/Pictures |
    xargs -0 -n1 echo
```

The program does **not** write the output continuously. It writes it
when the viewer exits successfully.

------------------------------------------------------------------------

## 5.10 `--private`

### `-p`, `--private`

The option is accepted and stored as `private_mode`, but the current
source does not use it elsewhere.

It has no observable effect in this version.

------------------------------------------------------------------------

## 5.11 Slideshow

### `-S DELAY`, `--ss-delay DELAY`

Enable slideshow mode at startup with the specified delay in seconds.

``` bash
tkiv img --ss-delay 3 ~/Pictures
```

A fractional value is accepted:

``` bash
tkiv img --ss-delay 1.5 ~/Pictures
```

Runtime toggle:

``` text
Ctrl+S
```

The configured delay is shown in the status bar while slideshow mode is
active.

Animated images and slideshow mode cooperate: if animation is enabled,
the slideshow waits at least long enough for the current multi-frame
animation to complete.

------------------------------------------------------------------------

## 5.12 Scaling

### `-s MODE`, `--scale-mode MODE`

Set the initial scaling mode.

The source defines these modes:

  Value   Meaning
  ------- --------------------
  `d`     Fit down
  `f`     Fit
  `F`     Fill
  `w`     Fit width
  `h`     Fit height
  `z`     Explicit zoom mode

The default is `d`.

Examples:

``` bash
tkiv img -s d image.jpg
tkiv img -s f image.jpg
tkiv img -s F image.jpg
tkiv img -s w image.jpg
tkiv img -s h image.jpg
```

Important implementation detail: the CLI does not restrict `MODE` to
these values. Unknown values fall through to the normal fit-down
behavior during rendering.

The runtime bindings are:

``` text
Ctrl+W          fit down
Ctrl+Shift+W    fit
Ctrl+Shift+F    fill
Ctrl+E          fit width
Ctrl+Shift+E    fit height
```

------------------------------------------------------------------------

## 5.13 Initial zoom

### `-z N`, `--zoom N`

Start at approximately `N` percent zoom.

``` bash
tkiv img --zoom 200 image.jpg
```

`100` means 1:1:

``` bash
tkiv img --zoom 100 image.jpg
```

The source converts the value to `N / 100.0`.

### `-Z`, `--zoom-100`

Explicitly start at 100% zoom.

``` bash
tkiv img -Z image.jpg
```

If both `-z` and `-Z` are supplied, `-Z` takes precedence because it is
checked first during initialization.

Interactive zoom levels are:

``` text
12.5%
25%
50%
75%
100%
150%
200%
400%
800%
```

`Ctrl++` and `Ctrl+-` move through these levels.

------------------------------------------------------------------------

## 5.14 Anti-aliasing

### `--anti-alias [VALUE]`

Controls image resampling.

The default is `yes`.

Examples:

``` bash
tkiv img --anti-alias image.jpg
tkiv img --anti-alias yes image.jpg
tkiv img --anti-alias no image.jpg
```

With anti-aliasing enabled, resized images use Pillow's `BICUBIC`
resampling. With it disabled, `NEAREST` is used.

Runtime:

``` text
Ctrl+I
```

toggles the setting.

------------------------------------------------------------------------

## 5.15 Alpha handling

### `--alpha-layer [VALUE]`

The argument is optional.

The source sets `alpha_layer` to true only when the explicitly supplied
value is `yes`:

``` bash
tkiv img --alpha-layer yes image.png
```

The bare form:

``` bash
tkiv img --alpha-layer
```

sets the parsed value to `no`, so it does **not** enable the feature.

Runtime:

``` text
Ctrl+Shift+I
```

toggles the internal alpha-layer state.

The image renderer nevertheless flattens RGBA images against the
configured background before applying brightness/contrast/gamma
processing. Therefore this option should not be interpreted as an
independent transparent-background rendering mode.

------------------------------------------------------------------------

# 6. Shared file-selection options

These options are available in both `img` and `select`.

## `-g`, `-t`, `--gallery`, `--thumbnail`

Start in gallery mode.

``` bash
tkiv img -g ~/Pictures
```

`-g` and `-t` are aliases.

## `-l`, `--list-mode`

Start in list mode.

``` bash
tkiv img -l ~/Pictures
```

## `-T N`, `--gallery-tile-size N`, `--thumb-size N`

Set the gallery tile's base size in pixels.

``` bash
tkiv img -g -T 300 ~/Pictures
```

The value is clamped internally to a gallery tile long-side range of
96--512 pixels.

`Ctrl++` and `Ctrl+-` can change the gallery tile size interactively.

## `--gallery-rows N`

Request a target number of visible gallery rows.

The default target is 3.5 rows.

``` bash
tkiv img -g --gallery-rows 4 ~/Pictures
```

A fractional value is accepted:

``` bash
tkiv img -g --gallery-rows 2.5 ~/Pictures
```

## `--gallery-cols N`

Request a target number of visible gallery columns.

``` bash
tkiv img -g --gallery-cols 5 ~/Pictures
```

If both rows and columns are supplied, the computed tile width is
constrained by both.

## `--gallery-aspect N`

Specify gallery tile width/height ratio.

``` bash
tkiv img -g --gallery-aspect 1.777 ~/Pictures
```

The value is clamped internally to:

``` text
0.4 <= aspect <= 3.0
```

If it is omitted, the program samples up to the first 20 files and uses
their median image aspect ratio. Before that calculation completes, it
temporarily uses a default aspect ratio of 16:9.

## `--lazy`

Show the UI immediately and populate the file list while directory
scanning happens in a background thread.

``` bash
tkiv img --lazy ~/Pictures
```

This is particularly useful for very large directories.

## `-r`, `--recursive`

Recursively search directories for supported image files.

``` bash
tkiv img -r ~/Pictures
```

## `-H`, `--hidden`

Include hidden files/directories during directory collection.

``` bash
tkiv img -r -H ~/Pictures
```

## `--time`

When scanning directories, order discovered files by modification time,
newest first.

``` bash
tkiv img --time ~/Pictures
```

With `--lazy`, the background scan likewise performs modification-time
ordering.

## `--sort MODE`

Initial interactive sort mode:

``` text
none
name
mtime
size
```

Examples:

``` bash
tkiv img --sort name ~/Pictures
tkiv img --sort mtime ~/Pictures
tkiv img --sort size ~/Pictures
```

Meaning:

-   `none`: retain discovery order.
-   `name`: label, case-insensitive.
-   `mtime`: modification time.
-   `size`: file size.

The default direction is:

-   name: ascending
-   mtime: newest first
-   size: largest first

## `-R`, `--sort-reverse`

Reverse the initial sort direction.

``` bash
tkiv img --sort name --sort-reverse ~/Pictures
```

This gives reverse alphabetical order.

For mtime and size, the implementation treats the normal direction as
descending and the reverse state as ascending.

## `-n N`, `--start-at N`, `--pass-idx N`

Start at a 1-based file index.

``` bash
tkiv img -n 25 ~/Pictures
```

The index is clamped to the available range.

## `--idx-write-path FILE`

Write the current 0-based internal index plus one to a file whenever the
current image changes.

``` bash
tkiv img --idx-write-path /tmp/tkiv-index ~/Pictures
```

The resulting file contains values such as:

``` text
17
```

The option is primarily intended for debugging/integration.

## `--pre-select TEXT`

Provide newline-separated labels that should initially be marked.

``` bash
tkiv select --pre-select $'one.jpg\ntwo.jpg' ~/Pictures
```

Matching is performed against the entry's **label**, not its full path.

## `--pre-select-file FILE`

Read initial selection labels from a file, one label per line.

``` bash
tkiv select --pre-select-file selected.txt ~/Pictures
```

`--pre-select` and `--pre-select-file` are mutually exclusive.

## `--no-searchbar`, `--no-search`, `--direct-keys`

Start in direct-key mode:

``` bash
tkiv img --no-searchbar ~/Pictures
```

In normal mode the search field has keyboard focus and configurable
actions normally use their `Ctrl+...` bindings.

In direct-key mode:

-   the search bar is hidden;
-   `Ctrl`/`Alt`/`Meta` are stripped from configurable bindings;
-   Shift is retained where applicable;
-   navigation keys remain unchanged.

`F2` switches between the two modes at runtime.

## `-q`, `--quiet`

Suppresses most diagnostic/error messages emitted by the application.

``` bash
tkiv img -q ~/Pictures
```

It does not suppress Tk or Python errors originating outside the
program's own guarded diagnostics.

## `-v`, `--version`

Print the mode-specific version.

``` bash
tkiv img --version
tkiv select --version
```

Current version:

``` text
0.4.0
```

## `-h`, `--help`

Print mode-specific help.

``` bash
tkiv img --help
tkiv select --help
```

The source's help output is shorter than this document; this document
includes options that the implementation parses but does not currently
expose prominently in the printed help.

------------------------------------------------------------------------

# 7. Search and filtering

The search bar is active by default and has keyboard focus.

Typing:

``` text
cat winter
```

filters the entries using whitespace-separated terms.

A file remains visible only if **every** search term occurs in either:

-   its label, or
-   its full path.

Matching is case-insensitive.

Thus:

``` text
cat winter
```

behaves like an AND query, not an OR query.

The filter is applied after a 60 ms debounce.

`Esc` clears a non-empty filter. If the filter is already empty, `Esc`
quits the application.

When the search bar is hidden, filtering is disabled and the full file
list is visible.

------------------------------------------------------------------------

# 8. Modes

`tkiv` has three modes:

``` text
image -> gallery -> list -> image
```

## Image mode

Displays one image at a time.

``` text
Tab
```

moves to gallery mode.

## Gallery mode

Displays thumbnails in a scrollable grid.

Each tile can contain:

-   thumbnail;
-   filename/label;
-   selection border;
-   mark indicator.

`Ctrl++` and `Ctrl+-` change the gallery tile size.

Mouse wheel scrolling is supported.

## List mode

Displays:

-   a scrollable list of labels on the left;
-   a preview of the current image on the right.

------------------------------------------------------------------------

# 9. Mode switching

  Key           Action
  ------------- ---------------------------------------
  `Tab`         Image → gallery → list → image
  `Shift+Tab`   Reverse cycle
  `Return`      Image → gallery; gallery/list → image
  `Esc`         Clear search, otherwise quit
  `F2`          Search-bar/direct-key toggle

In selector mode, `Return` has a different meaning: it accepts the
selection and exits instead of switching visual modes.

------------------------------------------------------------------------

# 10. Complete default key bindings

The configurable bindings are defined as action names internally. The
defaults are:

  Action               Default binding       Function
  -------------------- --------------------- -----------------------------------
  `quit`               `Ctrl+Q`              Quit
  `toggle_bar`         `Ctrl+B`              Toggle status bar
  `remove`             `Ctrl+D`              Remove current/marked entries
  `fit_width`          `Ctrl+E`              Fit image width
  `fullscreen`         `Ctrl+F`              Toggle fullscreen
  `first`              `Ctrl+G`              First visible item
  `pan_left`           `Ctrl+H`              Pan left
  `toggle_antialias`   `Ctrl+I`              Toggle anti-aliasing
  `pan_down`           `Ctrl+J`              Pan down
  `pan_up`             `Ctrl+K`              Pan up
  `pan_right`          `Ctrl+L`              Pan right
  `toggle_mark`        `Ctrl+M`              Toggle current mark
  `next`               `Ctrl+N`              Next visible item
  `prev`               `Ctrl+P`              Previous visible item
  `reload`             `Ctrl+R`              Reload current image/thumbnail
  `slideshow`          `Ctrl+S`              Toggle slideshow
  `unmark_all`         `Ctrl+U`              Clear all marks
  `fit_down`           `Ctrl+W`              Fit down
  `sort_cycle`         `Ctrl+Y`              Cycle sort mode/direction
  `center`             `Ctrl+Z`              Center image
  `animate`            `Ctrl+Space`          Toggle animation
  `zoom_100`           `Ctrl+0`              Set 100% zoom
  `zoom_in`            `Ctrl+Plus`           Zoom in / enlarge gallery tiles
  `zoom_out`           `Ctrl+Minus`          Zoom out / shrink gallery tiles
  `nav_10_forward`     `Ctrl+BracketRight`   Move 10 items forward
  `nav_10_back`        `Ctrl+BracketLeft`    Move 10 items backward
  `gamma_down`         `Ctrl+BraceLeft`      Lower gamma
  `gamma_up`           `Ctrl+BraceRight`     Raise gamma
  `contrast_down`      `Ctrl+ParenLeft`      Lower contrast
  `contrast_up`        `Ctrl+ParenRight`     Raise contrast
  `rotate_left`        `Ctrl+Less`           Rotate 90° counter-clockwise
  `rotate_right`       `Ctrl+Greater`        Rotate 90° clockwise
  `rotate_180`         `Ctrl+Question`       Rotate 180°
  `flip_h`             `Ctrl+Bar`            Flip horizontally
  `flip_v`             `Ctrl+Underscore`     Flip vertically
  `fit`                `Ctrl+Shift+W`        Fit
  `fill`               `Ctrl+Shift+F`        Fill
  `fit_height`         `Ctrl+Shift+E`        Fit image height
  `toggle_alpha`       `Ctrl+Shift+I`        Toggle alpha state
  `sort_reverse`       `Ctrl+Shift+Y`        Reverse current sorting
  `toggle_searchbar`   `F2`                  Toggle search bar/direct-key mode

There is also a hard-coded:

``` text
Ctrl+Enter
```

binding for toggling the current mark while the search bar is visible.

------------------------------------------------------------------------

# 11. Non-configurable keyboard bindings

These bindings are installed separately from the configurable action
table:

  Key           Behavior
  ------------- --------------------------------------
  `Up`          Context-dependent navigation/pan
  `Down`        Context-dependent navigation/pan
  `Left`        Context-dependent navigation/pan
  `Right`       Context-dependent navigation/pan
  `PageUp`      Page backward
  `PageDown`    Page forward
  `Home`        First visible item
  `End`         Last visible item
  `Tab`         Next mode
  `Shift+Tab`   Previous mode
  `Return`      Accept/switch mode depending on mode
  `KP_Enter`    Same as Return
  `Escape`      Clear filter or quit
  `Delete`      Remove current/marked files

These are not entries in `[keys]` and cannot be remapped through the
configuration file.

------------------------------------------------------------------------

# 12. Navigation behavior by mode

## Image mode

Arrow keys pan the image.

``` text
Left / Right / Up / Down
```

move the image by roughly one fifth of the viewport.

`Ctrl+H/J/K/L` invoke the same directional navigation.

`Ctrl+[` / `Ctrl+]` move ten visible entries backward/forward.

`PageUp` and `PageDown` also move by ten images in image mode.

## Gallery mode

Arrow keys move through the grid.

-   Left/right: one item.
-   Up/down: one gallery row.

PageUp/PageDown move approximately one screenful of rows.

## List mode

Up/down moves one item.

PageUp/PageDown move approximately twenty visible entries.

------------------------------------------------------------------------

# 13. Image manipulation

## Zoom

The interactive zoom sequence is:

``` text
12.5% → 25% → 50% → 75% → 100% → 150% → 200% → 400% → 800%
```

Controls:

``` text
Ctrl++
Ctrl+-
Ctrl+0
```

At image sizes smaller than the viewport, the image is kept centered.

## Panning

``` text
Ctrl+H    left
Ctrl+L    right
Ctrl+K    up
Ctrl+J    down
```

The image is constrained so that it cannot be panned completely away
from the viewport.

## Centering

``` text
Ctrl+Z
```

Centers the current image at its current zoom.

## Fit modes

``` text
Ctrl+W          fit down
Ctrl+Shift+W    fit
Ctrl+Shift+F    fill
Ctrl+E          fit width
Ctrl+Shift+E    fit height
```

The distinction between fit-down and fit is important:

-   **fit down** never enlarges an image beyond 100%;
-   **fit** may enlarge a small image to fill the available viewport;
-   **fill** chooses the larger width/height scale and therefore may
    crop the image;
-   width/height modes constrain only the corresponding dimension.

## Rotation

``` text
Ctrl+<       90° counter-clockwise
Ctrl+>       90° clockwise
Ctrl+?       180°
```

The transformations are applied to the currently loaded frame(s) in
memory.

They do not overwrite the source file.

## Flipping

``` text
Ctrl+|       horizontal flip
Ctrl+_       vertical flip
```

Again, this changes the displayed in-memory frames only.

## Anti-aliasing

``` text
Ctrl+I
```

toggles between:

``` text
BICUBIC
NEAREST
```

resampling.

## Alpha state

``` text
Ctrl+Shift+I
```

toggles the internal alpha state.

------------------------------------------------------------------------

# 14. Brightness, contrast and gamma

The source maintains three adjustment values:

``` text
brightness
contrast
gamma
```

The current configurable keyboard system exposes gamma and contrast, but
**does not bind brightness to a default key**.

## Gamma

``` text
Ctrl+{
Ctrl+}
```

decrease/increase gamma.

The internal value ranges from `-32` to `+32`.

## Contrast

``` text
Ctrl+(
Ctrl+)
```

decrease/increase contrast.

The internal value also ranges from `-32` to `+32`.

## Brightness

There is an implementation method for brightness adjustment, but no
default keyboard binding and no CLI option for changing it
interactively.

It is therefore not user-accessible through the program's documented
controls in this version.

------------------------------------------------------------------------

# 15. Marking files

Marks are independent of the current position.

``` text
Ctrl+M
```

toggles the current file's mark.

In search-bar mode:

``` text
Ctrl+Enter
```

does the same thing.

``` text
Ctrl+U
```

clears all marks.

Marked files are shown with a mark indicator in the status
bar/gallery/list.

## Removing files

``` text
Ctrl+D
```

removes the current file from the viewer's in-memory file list.

If one or more files are marked, **all marked files are removed**
instead.

This does **not** delete the files from disk.

The same operation is available through:

``` text
Delete
```

The removal only affects the current `tkiv` session.

------------------------------------------------------------------------

# 16. Mouse controls

## Image mode

  Mouse action                  Function
  ----------------------------- --------------------
  Left click near left third    Previous image
  Left click near right third   Next image
  Right click                   Enter gallery mode
  Wheel up                      Zoom in
  Wheel down                    Zoom out

The center portion of the image does not use left-click navigation.

## Gallery mode

  Mouse action   Function
  -------------- -----------------
  Left click     Select image
  Right click    Toggle mark
  Wheel up       Scroll upward
  Wheel down     Scroll downward

In selector mode, holding Ctrl while left-clicking a gallery tile
toggles its mark instead of simply moving to it.

## List mode

  Mouse action   Function
  -------------- -------------
  Left click     Select item
  Right click    Toggle mark

------------------------------------------------------------------------

# 17. Slideshow

Start or stop slideshow:

``` text
Ctrl+S
```

The initial delay can be set with:

``` bash
tkiv img --ss-delay 5 ~/Pictures
```

The default delay is 5 seconds.

Slideshow follows the currently visible/filter-matched entries and wraps
around from the last entry to the first.

------------------------------------------------------------------------

# 18. Sorting

There are three interactive sort fields:

``` text
name
date
size
```

`Ctrl+Y` cycles through six states:

``` text
name ascending
name descending
mtime newest first
mtime oldest first
size largest first
size smallest first
```

`Ctrl+Shift+Y` reverses the current sorting direction.

If no sort is active, `Ctrl+Shift+Y` starts with name ascending.

Sorting attempts to preserve the currently displayed path as the current
item rather than merely preserving its numeric index.

------------------------------------------------------------------------

# 19. Gallery sizing

Gallery tiles are computed from:

1.  window size;
2.  requested row count;
3.  optional column count;
4.  image aspect ratio;
5.  optional explicit tile size.

Default constants in the source include:

``` text
target rows:       3.5
tile aspect:       auto-detected
minimum tile size: 96 px
maximum tile size: 512 px
size quantum:      8 px
caption ratio:     16% of tile height
minimum caption:   22 px
minimum padding:   6 px
```

If `--gallery-aspect` is not specified, up to 20 images are sampled and
their median width/height ratio is used.

------------------------------------------------------------------------

# 20. Selector mode

Selector mode turns `tkiv` into an interactive image chooser:

``` bash
tkiv select ~/Pictures
```

Press:

``` text
Return
```

to accept.

Press:

``` text
Esc
```

to cancel.

On successful acceptance, the selected path(s) are printed to stdout.

If no files are marked, the current file is printed.

If files are marked, all marked files are printed.

------------------------------------------------------------------------

# 21. Selector examples

Select one image:

``` bash
image=$(tkiv select ~/Pictures)
```

Open the selected image:

``` bash
tkiv select ~/Pictures | xargs -r tkiv img
```

Use it as a wallpaper selection:

``` bash
wallpaper=$(tkiv select ~/Pictures/Wallpapers)
[ -n "$wallpaper" ] && swww img "$wallpaper"
```

Select multiple images:

``` bash
tkiv select ~/Pictures \
    --pre-select-file initial-selection.txt
```

Inside the selector, mark multiple entries with:

``` text
Ctrl+M
```

and press Return.

------------------------------------------------------------------------

# 22. Selector-specific options

## `--return-label`

Output the entry's label instead of its image path.

``` bash
tkiv select --return-label ...
```

This matters primarily in dmenu mode, where labels and image paths can
be different.

## `--dmenu-mode`

Enable paired-label/image-entry mode.

``` bash
tkiv select \
    --dmenu-mode \
    --list-entries $'Forest\nMountain\nCity' \
    --image-entries $'/pics/forest.jpg\n/pics/mountain.jpg\n/pics/city.jpg'
```

The number of labels and image paths must be identical.

------------------------------------------------------------------------

# 23. dmenu mode

dmenu mode explicitly separates:

``` text
display label
image path
```

Each line in the label list corresponds to the image path at the same
line number.

For example:

``` text
labels:
Forest
Mountain
City
```

and:

``` text
images:
/home/user/pictures/forest.jpg
/home/user/pictures/mountain.jpg
/home/user/pictures/city.jpg
```

produce three selectable entries.

## `--list-file`

Read labels from a file:

``` bash
tkiv select \
    --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

## `--list-entries`

Supply newline-separated labels directly:

``` bash
tkiv select \
    --dmenu-mode \
    --list-entries $'Forest\nMountain\nCity' \
    --image-file images.txt
```

## `--image-file`

Read image paths from a file:

``` bash
tkiv select \
    --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

## `--image-entries`

Supply newline-separated paths directly:

``` bash
tkiv select \
    --dmenu-mode \
    --list-entries $'Forest\nMountain' \
    --image-entries $'/a/forest.jpg\n/a/mountain.jpg'
```

The following pairs are mutually exclusive:

``` text
--list-file      vs --list-entries
--image-file     vs --image-entries
```

Both sides are required in dmenu mode.

------------------------------------------------------------------------

# 24. Practical dmenu-style scripts

## 24.1 Wallpaper chooser

``` bash
#!/usr/bin/env bash

wallpaper=$(
    tkiv select \
        --dmenu-mode \
        --list-file <(
            find "$HOME/Pictures/Wallpapers" \
                -type f \
                -print |
                sed 's#.*/##'
        ) \
        --image-file <(
            find "$HOME/Pictures/Wallpapers" \
                -type f \
                -print
        )
)

[ -n "$wallpaper" ] || exit 0

swww img "$wallpaper"
```

The label list and image list must remain in exactly the same order.

For filenames containing newlines, this particular line-oriented
interface is not suitable.

------------------------------------------------------------------------

## 24.2 Choose an image and open it

``` bash
#!/usr/bin/env bash

file=$(tkiv select "$HOME/Pictures") || exit

[ -n "$file" ] && tkiv img "$file"
```

------------------------------------------------------------------------

## 24.3 Choose a wallpaper by human-readable label

``` bash
#!/usr/bin/env bash

dir="$HOME/Pictures/Wallpapers"

mapfile -t images < <(
    find "$dir" -type f -print | sort
)

labels=()

for image in "${images[@]}"; do
    labels+=("$(basename "$image")")
done

selection=$(
    tkiv select \
        --dmenu-mode \
        --list-entries "$(printf '%s\n' "${labels[@]}")" \
        --image-entries "$(printf '%s\n' "${images[@]}")" \
        --return-label
)

printf '%s\n' "$selection"
```

This demonstrates the important distinction between:

``` text
label
```

and:

``` text
path
```

------------------------------------------------------------------------

# 25. Using `--stdout` as a viewer selection interface

Viewer mode can also emit selected files:

``` bash
files=$(
    tkiv img \
        --stdout \
        --gallery \
        ~/Pictures
)
```

Mark files with `Ctrl+M`, then quit normally.

If nothing is marked, the current file is emitted.

This is useful when you want the viewer UI but do not need selector
mode's semantics.

------------------------------------------------------------------------

# 26. NUL-delimited workflows

For robust shell pipelines involving arbitrary filenames, use `--null`.

Input:

``` bash
find "$HOME/Pictures" -type f -print0 |
    tkiv img --stdin --null
```

Output:

``` bash
tkiv img --stdout --null "$HOME/Pictures" |
    while IFS= read -r -d '' file; do
        printf 'selected: %s\n' "$file"
    done
```

The NUL behavior is implemented directly in the viewer's stdin/stdout
paths.

------------------------------------------------------------------------

# 27. Pre-selection

Pre-selection is label-based.

Suppose the files are:

``` text
/home/me/Pictures/a.jpg
/home/me/Pictures/b.jpg
/home/me/Pictures/c.jpg
```

Their default labels are:

``` text
a.jpg
b.jpg
c.jpg
```

Then:

``` bash
tkiv select \
    --pre-select $'a.jpg\nc.jpg' \
    ~/Pictures
```

starts with `a.jpg` and `c.jpg` marked.

With dmenu mode, the labels are the explicit list entries:

``` bash
tkiv select \
    --dmenu-mode \
    --list-entries $'First\nSecond\nThird' \
    --image-entries $'/a.jpg\n/b.jpg\n/c.jpg' \
    --pre-select $'First\nThird'
```

------------------------------------------------------------------------

# 28. Configuration file

The configuration file is:

``` text
~/.config/tkiv.py/config
```

or, when `XDG_CONFIG_HOME` is set:

``` text
$XDG_CONFIG_HOME/tkiv.py/config
```

The parser supports exactly three sections:

``` ini
[keys]

[theme]

[behavior]
```

The file is loaded once at program startup.

------------------------------------------------------------------------

# 29. Configuration syntax

Basic syntax:

``` ini
[section]
key = value
```

Blank lines are ignored.

Lines beginning with `#` are ignored.

Important: comments are only recognized when `#` is the first
non-whitespace character. Inline comments such as:

``` ini
next = Ctrl+N # next image
```

are not treated specially and can cause the configuration to be
rejected.

Any syntax error causes the **entire configuration file** to be
discarded and defaults to be used.

------------------------------------------------------------------------

# 30. Key customization

The `[keys]` section can replace bindings.

For example:

``` ini
[keys]
next = Ctrl+N
prev = Ctrl+P
```

More importantly, supplying an action in the config replaces that
action's default binding list.

Thus:

``` ini
[keys]
next = Space
```

does **not** mean:

``` text
Ctrl+N + Space
```

It means the default `Ctrl+N` binding is replaced by `Space`.

To assign multiple bindings to the same action, repeat the key:

``` ini
[keys]
next = Ctrl+N
next = Space
```

Now both bindings invoke the `next` action.

------------------------------------------------------------------------

# 31. Configurable action names

The following action names are valid under `[keys]`:

``` text
quit
toggle_bar
remove
fit_width
fullscreen
first
pan_left
toggle_antialias
pan_down
pan_up
pan_right
toggle_mark
next
prev
reload
slideshow
unmark_all
fit_down
sort_cycle
center
animate
zoom_100
zoom_in
zoom_out
nav_10_forward
nav_10_back
gamma_down
gamma_up
contrast_down
contrast_up
rotate_left
rotate_right
rotate_180
flip_h
flip_v
fit
fill
fit_height
toggle_alpha
sort_reverse
toggle_searchbar
```

Brightness is deliberately absent from this list because the source does
not expose its brightness method through the configurable action map.

The following are also not configurable:

``` text
arrows
PageUp
PageDown
Home
End
Tab
Shift+Tab
Return
KP_Enter
Escape
Delete
```

------------------------------------------------------------------------

# 32. Key-spec syntax

The configuration parser accepts human-readable forms such as:

``` text
Ctrl+N
Ctrl+Shift+W
Alt+X
Meta+Q
F2
Space
Return
Escape
Tab
Home
End
PageUp
PageDown
Up
Down
Left
Right
```

Modifier aliases include:

``` text
Ctrl
Control

Shift

Alt

Meta
Cmd
Super
Command
```

Special key aliases include:

``` text
space
plus
minus
equal
bracketleft
bracketright
braceleft
braceright
parenleft
parenright
less
greater
question
bar
underscore
return
enter
escape
esc
tab
backspace
bs
delete
del
home
end
pageup
pgup
prior
pagedown
pgdn
next
up
down
left
right
insert
ins
pause
print
```

Keypad aliases such as:

``` text
KP_Add
KP_Subtract
KP_Enter
KP_Multiply
KP_Divide
KP_Decimal
KP_0
...
KP_9
```

are also supported.

`F1` through `F12` are supported.

------------------------------------------------------------------------

# 33. Direct-key mode and custom bindings

Suppose the configuration contains:

``` ini
[keys]
next = Ctrl+N
prev = Ctrl+P
```

Normally these mean:

``` text
Ctrl+N
Ctrl+P
```

In direct-key mode they become:

``` text
N
P
```

Likewise:

``` ini
[keys]
fit = Ctrl+Shift+W
```

becomes:

``` text
Shift+W
```

The direct-key conversion strips Ctrl, Alt and Meta, while retaining
Shift.

------------------------------------------------------------------------

# 34. Example key configuration

A keyboard layout optimized around WASD:

``` ini
[keys]
next = L
prev = H
pan_up = K
pan_down = J
pan_left = H
pan_right = L
toggle_mark = Space
quit = Q
fullscreen = F
```

For direct-key mode, use:

``` bash
tkiv img --direct-keys ~/Pictures
```

The same config then uses the plain letters.

Note that assigning `H` to both `prev` and `pan_left` intentionally
gives the same key two bindings; which action effectively receives a
particular Tk event can depend on the binding registrations and should
therefore be avoided when actions conflict.

------------------------------------------------------------------------

# 35. Theme customization

The `[theme]` section accepts these exact keys:

``` text
bg_primary
bg_secondary
bg_input
fg_text
fg_bright
accent
accent_fg
selected_bg
selected_fg
hover_border
```

Every value must be a six-digit hexadecimal RGB color:

``` text
#RRGGBB
```

Examples:

``` ini
[theme]
bg_primary = #111111
bg_secondary = #222222
bg_input = #333333
fg_text = #dddddd
fg_bright = #ffffff
accent = #88c0d0
accent_fg = #111111
selected_bg = #444444
selected_fg = #ffffff
hover_border = #555555
```

Three-digit CSS colors such as:

``` text
#fff
```

are rejected.

------------------------------------------------------------------------

# 36. Theme keys explained

  Key              Used for
  ---------------- --------------------------------------------
  `bg_primary`     Main window/image background
  `bg_secondary`   Secondary panels, list background, borders
  `bg_input`       Search entry background
  `fg_text`        Normal text
  `fg_bright`      More prominent filename text
  `accent`         Current selection/mark accent
  `accent_fg`      Accent foreground color
  `selected_bg`    Selected list/marked-entry background
  `selected_fg`    Selected/marked-entry foreground
  `hover_border`   Non-current gallery tile border

The source defines a Nord-like default palette.

------------------------------------------------------------------------

# 37. Behavior customization

The `[behavior]` section currently exposes exactly two values:

``` text
slideshow_delay
max_load_dim
```

Example:

``` ini
[behavior]
slideshow_delay = 10
max_load_dim = 8192
```

Both values must be positive integers.

------------------------------------------------------------------------

# 38. `slideshow_delay`

Default:

``` text
5
```

Unit:

``` text
seconds
```

Example:

``` ini
[behavior]
slideshow_delay = 2
```

This changes the default used when slideshow is enabled interactively
with `Ctrl+S`.

An explicit CLI `--ss-delay` overrides this default for that invocation.

------------------------------------------------------------------------

# 39. `max_load_dim`

Default:

``` text
4096
```

This limits the maximum decoded full-image dimension in the pyvips
loading path.

For example:

``` ini
[behavior]
max_load_dim = 2048
```

can reduce the decoded dimensions of very large images.

The value affects full-image loading, not merely the gallery thumbnail
dimensions.

------------------------------------------------------------------------

# 40. Complete example configuration

``` ini
# ~/.config/tkiv.py/config

[keys]
quit = Ctrl+Q

next = Ctrl+N
next = Space

prev = Ctrl+P

toggle_mark = Ctrl+M
toggle_mark = Ctrl+Return

fullscreen = Ctrl+F

fit = Ctrl+Shift+W
fit_down = Ctrl+W
fill = Ctrl+Shift+F
fit_width = Ctrl+E
fit_height = Ctrl+Shift+E

zoom_in = Ctrl+Plus
zoom_out = Ctrl+Minus
zoom_100 = Ctrl+0

rotate_left = Ctrl+Less
rotate_right = Ctrl+Greater

sort_cycle = Ctrl+Y
sort_reverse = Ctrl+Shift+Y

[theme]
bg_primary = #1e1e1e
bg_secondary = #2a2a2a
bg_input = #333333
fg_text = #dddddd
fg_bright = #ffffff
accent = #88c0d0
accent_fg = #1e1e1e
selected_bg = #444444
selected_fg = #ffffff
hover_border = #555555

[behavior]
slideshow_delay = 5
max_load_dim = 4096
```

------------------------------------------------------------------------

# 41. Configuration failure behavior

The parser rejects:

-   unknown sections;
-   keys outside a section;
-   malformed `key = value` lines;
-   unknown action names;
-   invalid key sequences;
-   unknown theme keys;
-   invalid colors;
-   unknown behavior keys;
-   non-integer behavior values;
-   non-positive behavior values.

If **any** such error occurs, the complete config is discarded.

The program prints an error similar to:

``` text
tkiv: config error: ...; using defaults
```

unless the diagnostic is otherwise suppressed by the application's
output behavior.

There is no partial application of a malformed configuration.

------------------------------------------------------------------------

# 42. Image loading architecture

The program uses asynchronous loading.

Full-image decoding uses a thread pool with up to 20 workers.

Gallery thumbnail generation uses another thread pool with up to 20
workers.

The viewer also prefetches neighboring images while in image mode.

The default prefetch cache can hold up to 20 decoded image entries.

This means moving to the next image can often use a decoded image that
has already been loaded in the background.

------------------------------------------------------------------------

# 43. Thumbnail caching

The selector/gallery thumbnail path has a disk cache enabled by default.

The cache directory is:

``` text
$XDG_CACHE_HOME/tkiv_thumbs
```

or, if `XDG_CACHE_HOME` is not set:

``` text
~/.cache/tkiv_thumbs
```

Cached thumbnails are stored as WebP with quality:

``` text
82
```

The cache key incorporates:

-   file path;
-   modification timestamp in nanoseconds;
-   file size;
-   requested thumbnail dimensions.

This means modifying a file or changing the requested thumbnail
dimensions naturally produces a different cache key.

------------------------------------------------------------------------

# 44. Image decoding

When pyvips is available, the program prefers it for:

-   full image loading;
-   multi-frame loading;
-   gallery thumbnail generation;
-   image-size probing.

Pillow is the fallback.

Animated/multi-page files can contain multiple frames. The program
stores each frame and its delay.

A fallback animation delay of:

``` text
75 ms
```

is used when no usable frame duration is available.

------------------------------------------------------------------------

# 45. Automatic reload

While displaying an image, the program periodically checks its
modification time.

The check occurs approximately every 500 ms.

If the current image's modification time changes, it is reloaded
automatically.

This is useful for images generated or edited by another program.

`Ctrl+R` forces a reload manually.

------------------------------------------------------------------------

# 46. Output semantics

The common output rule is:

1.  Collect all marked entries.
2.  If none are marked, use the current entry.
3.  Print labels or paths depending on selector mode.
4.  Use newline or NUL separators depending on `--null`.

In viewer mode:

``` text
--stdout
```

prints paths.

In selector mode:

``` text
--return-label
```

changes the selector output from image path to label.

------------------------------------------------------------------------

# 47. Exit behavior

## Viewer

Normal successful exit uses status 0.

`Esc` when the search field is empty quits.

The window manager close button also exits normally in viewer mode.

## Selector

`Return` accepts and exits with status 0.

`Esc` cancels and exits with status 1.

Closing the window likewise produces selector status 1.

This makes selector mode suitable for shell conditionals:

``` bash
if image=$(tkiv select ~/Pictures); then
    printf 'Selected: %s\n' "$image"
else
    printf 'Selection cancelled\n' >&2
fi
```

------------------------------------------------------------------------

# 48. Useful shell integration examples

## Open the newest image

``` bash
image=$(
    find ~/Pictures -type f \
        \( -iname '*.jpg' -o -iname '*.png' -o -iname '*.webp' \) \
        -printf '%T@ %p\n' |
    sort -nr |
    head -n1 |
    cut -d' ' -f2-
)

tkiv img "$image"
```

## Select from a recursive directory tree

``` bash
file=$(tkiv select --recursive ~/Pictures)
```

## Start in gallery mode and fullscreen

``` bash
tkiv img \
    --gallery \
    --fullscreen \
    ~/Pictures/Wallpapers
```

## Large gallery with explicit aspect ratio

``` bash
tkiv img \
    --gallery \
    --gallery-cols 5 \
    --gallery-aspect 16/9 \
    ~/Pictures
```

For the actual CLI, use a numeric expression rather than shell
arithmetic embedded in the option:

``` bash
tkiv img \
    --gallery \
    --gallery-cols 5 \
    --gallery-aspect 1.7778 \
    ~/Pictures
```

## Lazy recursive scan

``` bash
tkiv img \
    --lazy \
    --recursive \
    ~/Pictures
```

## Newest images first

``` bash
tkiv img \
    --recursive \
    --sort mtime \
    ~/Pictures
```

## Largest images first

``` bash
tkiv img \
    --recursive \
    --sort size \
    ~/Pictures
```

## Start at image 100

``` bash
tkiv img \
    --start-at 100 \
    ~/Pictures
```

## Record the current index

``` bash
tkiv img \
    --idx-write-path /tmp/tkiv-index \
    ~/Pictures
```

------------------------------------------------------------------------

# 49. Example wallpaper picker script

``` bash
#!/usr/bin/env bash
set -euo pipefail

wallpaper_dir="${1:-$HOME/Pictures/Wallpapers}"

wallpaper="$(
    tkiv select \
        --gallery \
        --recursive \
        --sort name \
        "$wallpaper_dir"
)"

if [[ -n "$wallpaper" ]]; then
    swww img "$wallpaper"
fi
```

The selector exits with status 1 when cancelled, so a stricter version
can use:

``` bash
#!/usr/bin/env bash

if wallpaper=$(
    tkiv select \
        --gallery \
        --recursive \
        "$HOME/Pictures/Wallpapers"
); then
    swww img "$wallpaper"
fi
```

------------------------------------------------------------------------

# 50. Example multi-selection script

``` bash
#!/usr/bin/env bash

selected="$(
    tkiv select \
        --gallery \
        --recursive \
        "$HOME/Pictures"
)"

printf '%s\n' "$selected"
```

Because selector output can contain multiple marked paths, use NUL mode
for robust shell processing:

``` bash
#!/usr/bin/env bash

tkiv select \
    --gallery \
    --recursive \
    --null \
    "$HOME/Pictures" |
while IFS= read -r -d '' file; do
    printf 'selected: %s\n' "$file"
done
```

------------------------------------------------------------------------

# 51. Example custom key setup

For a configuration centered around Vim-like navigation:

``` ini
[keys]
next = Ctrl+J
prev = Ctrl+K
pan_left = Ctrl+H
pan_right = Ctrl+L
pan_up = Ctrl+K
pan_down = Ctrl+J
toggle_mark = Ctrl+Space
center = Ctrl+C
quit = Ctrl+Q
```

Be careful with conflicting bindings: here `Ctrl+J`/`Ctrl+K` are
deliberately assigned to both navigation and panning, so the
configuration is ambiguous from a user-interface perspective.

A safer image-viewer setup is:

``` ini
[keys]
next = Ctrl+N
prev = Ctrl+P
pan_left = Ctrl+H
pan_right = Ctrl+L
pan_up = Ctrl+K
pan_down = Ctrl+J
toggle_mark = Ctrl+Space
center = Ctrl+C
quit = Ctrl+Q
```

------------------------------------------------------------------------

# 52. Example direct-key setup

A minimalist direct-key configuration:

``` ini
[keys]
next = N
prev = P
toggle_mark = Space
quit = Q
fullscreen = F
```

Run:

``` bash
tkiv img --direct-keys ~/Pictures
```

Then:

``` text
N       next
P       previous
Space   mark
Q       quit
F       fullscreen
```

`F2` returns to the search-bar interface.

------------------------------------------------------------------------

# 53. Performance-related source constants

The following implementation constants are not configuration-file
options, but explain some behavior:

``` text
MAX_LOAD_DIM          = 4096
IMG_WORKERS           = 20
THUMB_WORKERS         = 20
PREFETCH_MAX          = 20
THUMB_MAX_IN_FLIGHT   = 20
QUEUE_POLL_MS         = 20
FILTER_DEBOUNCE_MS    = 60

LAZY_BATCH_SIZE       = 128
LISTBOX_INSERT_CHUNK  = 1000

GALLERY_TARGET_ROWS   = 3.5
GALLERY_TILE_MIN      = 96
GALLERY_TILE_MAX      = 512
GALLERY_SIZE_QUANTUM  = 8
GALLERY_ASPECT_SAMPLE = 20
GALLERY_ZOOM_STEP     = 32
```

These are source-level constants, not documented user configuration
settings.

------------------------------------------------------------------------

# 54. Supported invocation aliases

The dispatcher recognizes these viewer names:

``` text
img
view
viewer
pysxiv
```

and these selector names:

``` text
select
sel
selector
sel_img
```

Thus all of the following invoke selector mode:

``` bash
tkiv select ~/Pictures
tkiv sel ~/Pictures
tkiv selector ~/Pictures
tkiv sel_img ~/Pictures
```

------------------------------------------------------------------------

# 55. Current implementation caveats

The source contains several CLI options that are parsed for
compatibility or future functionality but are not currently connected to
behavior:

``` text
-A / --framerate
-c / --clean-cache
-e / --embed
-p / --private
--cache-allow
--cache-deny
--update-cache
```

`--class` is implemented as a deprecated alias-like title mechanism.

`--alpha-layer` has an unusual interface because its optional argument
defaults to `no`; use:

``` bash
--alpha-layer yes
```

if you intend to enable its internal state.

Brightness adjustment exists internally but has no default key binding
and is not exposed as a CLI option.

These details are based on the current source rather than on the option
names alone.

------------------------------------------------------------------------

# 56. Quick reference

## Launch

``` bash
tkiv img FILE...
tkiv select PATH...
```

## Modes

``` text
Tab             next mode
Shift+Tab       previous mode
Return          switch image/gallery/list
F2              search/direct-key mode
```

## Navigation

``` text
Arrow keys      navigate/pan
Home            first
End             last
PageUp          page back
PageDown        page forward
Ctrl+N          next
Ctrl+P          previous
Ctrl+[          -10
Ctrl+]          +10
```

## Image

``` text
Ctrl+W          fit down
Ctrl+Shift+W    fit
Ctrl+Shift+F    fill
Ctrl+E          fit width
Ctrl+Shift+E    fit height

Ctrl++          zoom in
Ctrl+-          zoom out
Ctrl+0          100%

Ctrl+H/J/K/L    pan
Ctrl+Z          center

Ctrl+<          rotate left
Ctrl+>          rotate right
Ctrl+?          rotate 180
Ctrl+|          flip horizontal
Ctrl+_          flip vertical

Ctrl+I          anti-alias
Ctrl+Shift+I    alpha state

Ctrl+(          contrast down
Ctrl+)          contrast up
Ctrl+{          gamma down
Ctrl+}          gamma up
```

## Files and selection

``` text
Ctrl+M          mark
Ctrl+U          unmark all
Ctrl+D          remove current/marked entries
Delete          remove current/marked entries
Ctrl+R          reload
```

## Viewer controls

``` text
Ctrl+Q          quit
Ctrl+F          fullscreen
Ctrl+B          status bar
Ctrl+S          slideshow
Ctrl+Space      animation
Ctrl+Y          sort cycle
Ctrl+Shift+Y    reverse sort
Esc             clear filter / quit
```

## Selector

``` text
Return          accept
Esc             cancel
Ctrl+M          mark
Ctrl+Enter      mark
```

------------------------------------------------------------------------

# 57. Minimal reference card

A compact everyday invocation set:

``` bash
# Normal viewer
tkiv img image.jpg

# Directory viewer
tkiv img ~/Pictures

# Recursive gallery
tkiv img -g -r ~/Pictures

# Fullscreen
tkiv img -f image.jpg

# Searchless/direct-key interface
tkiv img --no-searchbar ~/Pictures

# Lazy scan
tkiv img --lazy -r ~/Pictures

# Newest first
tkiv img --sort mtime ~/Pictures

# Selector
tkiv select ~/Pictures

# Selector with recursive gallery
tkiv select -g -r ~/Pictures

# Multi-selection with NUL output
tkiv select -g -r --null ~/Pictures

# Label/path paired selector
tkiv select \
    --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

