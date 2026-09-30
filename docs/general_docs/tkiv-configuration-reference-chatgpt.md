# tkiv Configuration and Usage Reference

**Version documented:** `0.4.0`

This document describes the configuration and command-line interface
implemented by `tkiv.py`.

`tkiv` has two modes:

``` text
tkiv.py img [OPTIONS] FILES...
tkiv.py select [OPTIONS] PATHS...
```

The `img` mode is the image viewer. The `select` mode is the interactive
image selector / dmenu-like interface.

The program also accepts these aliases:

``` text
img     view     viewer     pysxiv
select  sel      selector   sel_img
```

## 1. Configuration file

The configuration file is:

``` text
$XDG_CONFIG_HOME/tkiv.py/config
```

or, when `XDG_CONFIG_HOME` is not set:

``` text
~/.config/tkiv.py/config
```

The file has an INI-like syntax with three supported sections:

``` ini
[keys]
...

[theme]
...

[behavior]
...
```

Blank lines and lines beginning with `#` are ignored.

Every setting must occur inside one of these sections:

``` ini
[keys]
next = Ctrl+N
```

A key outside a section is an error.

### Important: configuration errors are all-or-nothing

If **any** configuration error occurs, the entire configuration file is
discarded and tkiv uses its built-in defaults.

For example:

``` ini
[theme]
bg_primary = #202020

[behavior]
slideshow_delay = abc
```

causes the whole configuration to be ignored, rather than applying the
valid `bg_primary` setting.

The program reports the configuration error on stderr unless otherwise
suppressed by the surrounding invocation.

------------------------------------------------------------------------

# 2. `[keys]`

The `[keys]` section changes the keyboard binding for actions.

The left-hand side must be one of the action names listed below.

``` ini
[keys]
next = Ctrl+N
```

An action may occur more than once. Repeated entries add additional
bindings rather than replacing previous entries.

For example:

``` ini
[keys]
next = Ctrl+N
next = Space
next = Right
```

makes all three keys perform the `next` action.

## 2.1 Key specification syntax

Modifiers are written with `+`:

``` text
Ctrl+N
Ctrl+Shift+W
Alt+X
Meta+Q
```

The following modifier names are recognized:

  Modifier   Aliases
  ---------- ---------------------------
  `Ctrl`     `Control`
  `Shift`    ---
  `Alt`      ---
  `Meta`     `Cmd`, `Super`, `Command`

Examples:

``` ini
quit = Ctrl+Q
quit = Control+Q
quit = Ctrl+Shift+Q
quit = Alt+Q
quit = Super+Q
```

Single-character keys can be written directly:

``` ini
next = n
next = N
next = 5
```

Special keys have aliases.

### Special-key aliases

  Key            Accepted names
  -------------- ----------------------------
  Space          `Space`
  Plus           `Plus`, `+`
  Minus          `Minus`, `-`
  Equals         `Equal`, `=`
  `[`            `BracketLeft`, `[`
  `]`            `BracketRight`, `]`
  `{`            `BraceLeft`, `{`
  `}`            `BraceRight`, `}`
  `(`            `ParenLeft`, `(`
  `)`            `ParenRight`, `)`
  `<`            `Less`, `<`
  `>`            `Greater`, `>`
  `?`            `Question`, `?`
  `|`            `Bar`, `|`
  `_`            `Underscore`, `_`
  Enter          `Return`, `Enter`
  Escape         `Escape`, `Esc`
  Tab            `Tab`
  Backspace      `Backspace`, `BS`
  Delete         `Delete`, `Del`
  Home           `Home`
  End            `End`
  Page Up        `PageUp`, `PgUp`, `Prior`
  Page Down      `PageDown`, `PgDn`, `Next`
  Arrow Up       `Up`
  Arrow Down     `Down`
  Arrow Left     `Left`
  Arrow Right    `Right`
  Insert         `Insert`, `Ins`
  Pause          `Pause`
  Print Screen   `Print`

The numeric keypad keys are also supported:

``` text
KP_Add
KP_Subtract
KP_Enter
KP_Multiply
KP_Divide
KP_Decimal
KP_0 ... KP_9
```

Function keys `F1` through `F12` are supported.

Examples:

``` ini
fullscreen = F11
next = KP_Add
quit = Ctrl+F4
```

### The `+` key

Because `+` normally separates modifiers, the program has special
handling for a literal plus key:

``` ini
zoom_in = Ctrl++
```

or:

``` ini
zoom_in = Ctrl+Plus
```

------------------------------------------------------------------------

# 3. Configurable keyboard actions

These are all of the action names accepted by `[keys]`.

  -------------------------------------------------------------------------
  Action                  Default binding         Function
  ----------------------- ----------------------- -------------------------
  `quit`                  `Ctrl+Q`                Quit

  `toggle_bar`            `Ctrl+B`                Toggle status bar

  `remove`                `Ctrl+D`                Remove current/marked
                                                  entries from the current
                                                  list

  `fit_width`             `Ctrl+E`                Fit image to window width

  `fullscreen`            `Ctrl+F`                Toggle fullscreen

  `first`                 `Ctrl+G`                Go to first visible entry

  `pan_left`              `Ctrl+H`                Pan left in image mode

  `toggle_antialias`      `Ctrl+I`                Toggle image
                                                  resampling/antialiasing

  `pan_down`              `Ctrl+J`                Pan down

  `pan_up`                `Ctrl+K`                Pan up

  `pan_right`             `Ctrl+L`                Pan right

  `toggle_mark`           `Ctrl+M`                Mark/unmark current entry

  `next`                  `Ctrl+N`                Next visible entry

  `prev`                  `Ctrl+P`                Previous visible entry

  `reload`                `Ctrl+R`                Reload current
                                                  image/thumbnail

  `slideshow`             `Ctrl+S`                Toggle slideshow

  `unmark_all`            `Ctrl+U`                Clear all marks

  `fit_down`              `Ctrl+W`                Fit image down without
                                                  enlarging it

  `sort_cycle`            `Ctrl+Y`                Cycle through sorting
                                                  modes/directions

  `center`                `Ctrl+Z`                Center image

  `animate`               `Ctrl+Space`            Toggle animation of
                                                  multi-frame images

  `zoom_100`              `Ctrl+0`                Set 100% zoom

  `zoom_in`               `Ctrl+Plus`             Zoom in; in gallery mode,
                                                  enlarge tiles

  `zoom_out`              `Ctrl+Minus`            Zoom out; in gallery
                                                  mode, shrink tiles

  `nav_10_forward`        `Ctrl+BracketRight`     Move 10 visible entries
                                                  forward

  `nav_10_back`           `Ctrl+BracketLeft`      Move 10 visible entries
                                                  backward

  `gamma_down`            `Ctrl+BraceLeft`        Decrease gamma

  `gamma_up`              `Ctrl+BraceRight`       Increase gamma

  `contrast_down`         `Ctrl+ParenLeft`        Decrease contrast

  `contrast_up`           `Ctrl+ParenRight`       Increase contrast

  `rotate_left`           `Ctrl+Less`             Rotate 90°
                                                  counter-clockwise

  `rotate_right`          `Ctrl+Greater`          Rotate 90° clockwise

  `rotate_180`            `Ctrl+Question`         Rotate 180°

  `flip_h`                `Ctrl+Bar`              Flip horizontally

  `flip_v`                `Ctrl+Underscore`       Flip vertically

  `fit`                   `Ctrl+Shift+W`          Fit image to window

  `fill`                  `Ctrl+Shift+F`          Fill window, potentially
                                                  cropping

  `fit_height`            `Ctrl+Shift+E`          Fit image to window
                                                  height

  `toggle_alpha`          `Ctrl+Shift+I`          Toggle alpha-related
                                                  display state

  `sort_reverse`          `Ctrl+Shift+Y`          Reverse the current
                                                  sorting direction

  `toggle_searchbar`      `F2`                    Toggle
                                                  search-bar/direct-key
                                                  mode
  -------------------------------------------------------------------------

### Example: completely custom bindings

``` ini
[keys]

quit = Ctrl+Escape

next = Right
prev = Left

fullscreen = F11

toggle_mark = Space
unmark_all = Ctrl+Shift+Space

zoom_in = +
zoom_out = -

fit = F
fill = Shift+F

rotate_left = [
rotate_right = ]

toggle_searchbar = F2
```

## 3.1 Direct-key mode

Starting with:

``` bash
tkiv.py img --no-searchbar image.jpg
```

hides the search bar and strips `Ctrl`, `Alt`, and `Meta` from
configurable bindings.

For example:

``` ini
[keys]
next = Ctrl+N
prev = Ctrl+P
fullscreen = Ctrl+F
```

becomes approximately:

``` text
N = next
P = previous
F = fullscreen
```

A binding containing `Shift` retains `Shift`. Thus:

``` ini
fit = Ctrl+Shift+W
```

becomes:

``` text
Shift+W
```

in direct-key mode.

`F2` switches between search-bar and direct-key modes at runtime.

The following navigation/mode keys are not part of the configurable
action system and remain fixed:

``` text
Arrow keys
Tab
Shift+Tab
Return
Escape
Delete
Page Up
Page Down
Home
End
```

------------------------------------------------------------------------

# 4. `[theme]`

Theme values must be six-digit hexadecimal RGB colors:

``` text
#RRGGBB
```

For example:

``` ini
[theme]
bg_primary = #111111
fg_text = #eeeeee
accent = #88c0d0
```

Short forms such as `#fff` are **not** accepted.

## 4.1 Theme settings

  -----------------------------------------------------------------------
  Setting                 Default                 Used for
  ----------------------- ----------------------- -----------------------
  `bg_primary`            `#2e3440`               Main window/image
                                                  background

  `bg_secondary`          `#3b4252`               Secondary panels, list
                                                  background, borders

  `bg_input`              `#4c566a`               Search input background

  `fg_text`               `#d8dee9`               Normal text

  `fg_bright`             `#eceff4`               Brighter text, such as
                                                  list filename

  `accent`                `#88c0d0`               Accent/selection/mark
                                                  indicators

  `accent_fg`             `#2e3440`               Defined accent
                                                  foreground color

  `selected_bg`           `#5e81ac`               Selected list-entry
                                                  background

  `selected_fg`           `#eceff4`               Selected list-entry
                                                  foreground

  `hover_border`          `#4c566a`               Non-current gallery
                                                  tile border
  -----------------------------------------------------------------------

Example:

``` ini
[theme]
bg_primary = #181818
bg_secondary = #242424
bg_input = #303030

fg_text = #d0d0d0
fg_bright = #ffffff

accent = #7aa2f7
accent_fg = #181818

selected_bg = #3d59a1
selected_fg = #ffffff

hover_border = #444444
```

You can change only one color:

``` ini
[theme]
bg_primary = #000000
```

All other colors retain their built-in defaults.

------------------------------------------------------------------------

# 5. `[behavior]`

Only two persistent behavior settings are currently exposed.

``` ini
[behavior]
slideshow_delay = 5
max_load_dim = 4096
```

## 5.1 `slideshow_delay`

Default:

``` text
5
```

Unit:

``` text
seconds
```

It controls the default interval between slideshow images.

It must be a positive integer.

Examples:

``` ini
[behavior]
slideshow_delay = 2
```

Two-second slideshow:

``` bash
tkiv.py img --ss-delay 0
```

then use `Ctrl+S`; the configured `slideshow_delay` is used.

A value of `1` gives a one-second default delay:

``` ini
[behavior]
slideshow_delay = 1
```

## 5.2 `max_load_dim`

Default:

``` text
4096
```

This is the maximum width/height dimension used when decoding full
images through the pyvips path.

For example:

``` ini
[behavior]
max_load_dim = 2048
```

causes very large images to be reduced so that their largest dimension
is at most approximately 2048 pixels when loaded through pyvips.

It must be a positive integer.

A larger value preserves more source resolution at the cost of
potentially greater memory use.

A smaller value reduces memory use for very large images.

------------------------------------------------------------------------

# 6. Complete example configuration

Here is a practical complete configuration:

``` ini
# ~/.config/tkiv.py/config

[keys]

# Navigation
next = Ctrl+N
prev = Ctrl+P
first = Ctrl+Home

# Also allow arrow keys
next = Right
prev = Left

# Window
quit = Ctrl+Q
fullscreen = F11
toggle_bar = Ctrl+B

# Image manipulation
fit = Ctrl+Shift+W
fill = Ctrl+Shift+F
fit_width = Ctrl+E
fit_height = Ctrl+Shift+E

zoom_in = Ctrl+Plus
zoom_out = Ctrl+Minus
zoom_100 = Ctrl+0

rotate_left = Ctrl+Less
rotate_right = Ctrl+Greater

# Selection
toggle_mark = Ctrl+M
unmark_all = Ctrl+U

# Other
reload = Ctrl+R
slideshow = Ctrl+S
toggle_searchbar = F2


[theme]

bg_primary = #181818
bg_secondary = #242424
bg_input = #303030

fg_text = #d0d0d0
fg_bright = #ffffff

accent = #7aa2f7
accent_fg = #181818

selected_bg = #3d59a1
selected_fg = #ffffff
hover_border = #444444


[behavior]

slideshow_delay = 4
max_load_dim = 4096
```

------------------------------------------------------------------------

# 7. Shared command-line options

These options are accepted by both `img` and `select`.

## `-g`, `-t`, `--gallery`, `--thumbnail`

Start directly in gallery mode.

``` bash
tkiv.py img --gallery *.jpg
```

Aliases:

``` bash
tkiv.py img -g *.jpg
tkiv.py img -t *.jpg
tkiv.py img --thumbnail *.jpg
```

## `-T N`, `--gallery-tile-size N`, `--thumb-size N`

Set the gallery tile size in pixels.

``` bash
tkiv.py img --gallery --gallery-tile-size 256 *.jpg
```

The implementation treats this as the gallery tile's long side and
derives the other dimension from the gallery aspect ratio.

## `--gallery-rows N`

Specify the target number of visible gallery rows.

Default target:

``` text
3.5
```

Example:

``` bash
tkiv.py img --gallery --gallery-rows 5 ~/Pictures
```

## `--gallery-cols N`

Specify the target number of gallery columns.

``` bash
tkiv.py img --gallery --gallery-cols 6 ~/Pictures
```

## `--gallery-aspect N`

Set the gallery tile width/height ratio.

For 16:9:

``` bash
tkiv.py img --gallery --gallery-aspect 1.777 ~/Pictures
```

For square tiles:

``` bash
tkiv.py img --gallery --gallery-aspect 1 ~/Pictures
```

If omitted, tkiv samples up to 20 images and uses the median image
aspect ratio.

The internally enforced aspect-ratio range is:

``` text
0.4 ... 3.0
```

## `--lazy`

Show the UI immediately and scan directories asynchronously.

Useful for directories containing many images:

``` bash
tkiv.py img --lazy ~/Pictures
```

Combine with recursive scanning:

``` bash
tkiv.py img --lazy --recursive ~/Pictures
```

## `-r`, `--recursive`

Recursively search directories for supported image files.

``` bash
tkiv.py img --recursive ~/Pictures
```

## `-H`, `--hidden`

Include hidden files/directories while scanning.

``` bash
tkiv.py img --recursive --hidden ~/.pictures
```

## `--time`

Sort directory results by modification time, newest first, during
directory collection.

``` bash
tkiv.py img --time ~/Pictures
```

This is distinct from the runtime `Ctrl+Y` sorting cycle.

## `--sort MODE`

Set the initial sorting mode.

Allowed values:

``` text
none
name
mtime
size
```

Examples:

``` bash
tkiv.py img --sort name ~/Pictures
tkiv.py img --sort mtime ~/Pictures
tkiv.py img --sort size ~/Pictures
```

Meaning:

  Mode      Meaning
  --------- --------------------------
  `none`    Preserve discovery order
  `name`    Name, alphabetically
  `mtime`   Modification time
  `size`    File size

The implementation displays name sorting in ascending order by default,
while `mtime` and `size` are initially descending (newest/largest
first).

## `-R`, `--sort-reverse`

Reverse the selected sorting direction.

``` bash
tkiv.py img --sort name --sort-reverse ~/Pictures
```

For names this gives reverse alphabetical order.

For modification time and size it reverses the normal
newest/largest-first behavior.

## `-n N`, `--start-at N`, `--pass-idx N`

Start at a **1-based** index.

``` bash
tkiv.py img --start-at 20 ~/Pictures
```

The value is clamped to the available file range.

## `--name NAME`, `--custom-title NAME`

Set the window title.

``` bash
tkiv.py img --name "My Images" *.jpg
```

## `--idx-write-path FILE`

Write the current 1-based index to a file.

``` bash
tkiv.py img \
    --idx-write-path /tmp/tkiv-index \
    ~/Pictures
```

The file contains a number such as:

``` text
17
```

This is primarily useful for scripting/debugging.

## `--pre-select LABELS`

Pre-mark entries whose labels match the supplied newline-separated
labels.

Example:

``` bash
tkiv.py select \
    --pre-select $'image1.jpg\nimage3.jpg' \
    ~/Pictures
```

Matching is against the entry's **label**, not an arbitrary substring.

Only the first matching occurrence of a label is marked.

## `--pre-select-file FILE`

Read pre-selected labels from a file.

``` bash
tkiv.py select \
    --pre-select-file selected.txt \
    ~/Pictures
```

The file contains one label per line.

`--pre-select` and `--pre-select-file` are mutually exclusive.

## `--no-searchbar`, `--no-search`, `--direct-keys`

Start with the search bar hidden and use direct-key bindings.

All three forms are aliases:

``` bash
tkiv.py img --no-searchbar *.jpg
tkiv.py img --direct-keys *.jpg
```

Press `F2` to restore the search bar.

## `-q`, `--quiet`

Suppresses various diagnostic/error messages emitted by tkiv.

``` bash
tkiv.py img --quiet ~/Pictures
```

It does not disable the program's normal UI.

## `-v`, `--version`

Print the program version for the selected mode.

``` bash
tkiv.py img --version
tkiv.py select --version
```

Current source version:

``` text
0.4.0
```

## `-h`, `--help`

Show mode-specific help.

``` bash
tkiv.py img --help
tkiv.py select --help
```

------------------------------------------------------------------------

# 8. Viewer-only options

These options are accepted by:

``` bash
tkiv.py img ...
```

## `-a`, `--animate`

Start animated images with animation enabled.

``` bash
tkiv.py img --animate animation.gif
```

For multi-frame images, `Ctrl+Space` toggles animation after startup.

## `-A N`, `--framerate N`

The option is parsed, but the current source does not use
`args.framerate` after parsing.

Therefore:

``` bash
tkiv.py img --framerate 30 animation.gif
```

does **not currently configure animation to 30 FPS**.

Animation timing comes from the image's frame delays, with a built-in
fallback of 75 ms.

## `--assume-files`

If an image cannot be decoded, keep the entry rather than automatically
removing it from the internal list.

``` bash
tkiv.py img --assume-files broken.jpg
```

This is primarily useful for integrations where the supplied file list
should remain intact.

## `-b`, `--no-bar`

Start with the status bar hidden.

``` bash
tkiv.py img --no-bar *.jpg
```

## `--bar`

Explicitly enable the status bar.

``` bash
tkiv.py img --bar *.jpg
```

If both `--no-bar` and `--bar` are supplied, `--bar` wins because the
implementation computes:

``` text
show_bar = not no_bar OR bar
```

## `--floating-window`

Enable the floating/dialog-style window behavior.

``` bash
tkiv.py img --floating-window *.jpg
```

The implementation makes the window topmost, attempts to set the X11
window type to `dialog`, and uses a large screen-relative geometry.

## `-c`, `--clean-cache`

The option is parsed, but the current source does not use
`args.clean_cache`.

Therefore it currently has no implemented effect.

## `-e N`, `--embed N`

The option is parsed, but `args.embed` is not subsequently used by the
program.

It currently has no implemented effect.

## `-f`, `--fullscreen`

Start in fullscreen mode.

``` bash
tkiv.py img --fullscreen image.jpg
```

`Ctrl+F` toggles fullscreen after startup.

## `-G N`, `--gamma N`

Set the initial gamma adjustment.

``` bash
tkiv.py img --gamma 4 image.jpg
```

The source stores this as an integer adjustment step value.

The runtime adjustment is clamped to:

``` text
-32 ... +32
```

The underlying gamma mapping has a maximum gamma range of 10.0.

## `--geometry GEOMETRY`

Set the initial Tk window geometry.

Example:

``` bash
tkiv.py img --geometry 1200x800+100+50 image.jpg
```

The normal default is:

``` text
900x700
```

An invalid geometry causes the program to fall back to `900x700`.

## `-i`, `--stdin`

Read image paths from standard input.

Default separator:

``` text
newline
```

Example:

``` bash
find ~/Pictures -type f -name '*.jpg' |
    tkiv.py img --stdin
```

For NUL-separated input, combine with `-0`:

``` bash
find ~/Pictures -type f -print0 |
    tkiv.py img --stdin -0
```

A literal `-` as the sole file argument also triggers stdin mode:

``` bash
printf '%s\n' a.jpg b.jpg c.jpg | tkiv.py img -
```

## `-N NAME`, `--legacy-name NAME`

Legacy name option.

The current source copies it to `--name` when `--name` was not already
supplied.

``` bash
tkiv.py img --legacy-name "Pictures" *.jpg
```

## `--class NAME`

Legacy/deprecated option.

The program prints a warning:

``` text
tkiv img: --class is deprecated, use --name instead
```

If no `--name` was supplied, its value is used as the window title.

Prefer:

``` bash
tkiv.py img --name "Pictures" *.jpg
```

## `-o`, `--stdout`

On successful viewer exit, write the marked/current image path(s) to
stdout.

``` bash
tkiv.py img --stdout *.jpg
```

If nothing is marked, the current file is output.

If one or more files are marked, all marked files are output.

Use `-0` for NUL-separated output.

## `-p`, `--private`

The option is parsed, but the current source does not use
`args.private_mode`.

It currently has no implemented effect.

## `-S N`, `--ss-delay N`

Set the slideshow delay from the command line.

The value is a floating-point number in seconds.

``` bash
tkiv.py img --ss-delay 2.5 *.jpg
```

The runtime implementation converts it to tenths of a second internally.

If the value is greater than zero, slideshow mode is enabled
immediately.

Thus:

``` bash
tkiv.py img --ss-delay 3 *.jpg
```

starts with a three-second slideshow.

With the default:

``` text
-S 0
```

slideshow is initially disabled, and pressing `Ctrl+S` starts it using
`[behavior] slideshow_delay`.

## `-s MODE`, `--scale-mode MODE`

Set the initial scale mode.

The source defines these internal modes:

  Value   Meaning
  ------- -------------
  `d`     Fit down
  `f`     Fit
  `F`     Fill
  `w`     Fit width
  `h`     Fit height
  `z`     Manual zoom

Examples:

``` bash
tkiv.py img --scale-mode d image.jpg
tkiv.py img --scale-mode f image.jpg
tkiv.py img --scale-mode F image.jpg
tkiv.py img --scale-mode w image.jpg
tkiv.py img --scale-mode h image.jpg
```

The parser does not restrict this argument to those values. An
unsupported value effectively falls through to the normal fit
calculation, so use the values above.

## `-z N`, `--zoom N`

Start at a manual zoom percentage.

``` bash
tkiv.py img --zoom 200 image.jpg
```

This means:

``` text
200% = 2.0×
```

The implementation switches to manual zoom mode.

The normal runtime zoom levels are:

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

## `-Z`, `--zoom-100`

Start at exactly 100% zoom.

``` bash
tkiv.py img --zoom-100 image.jpg
```

This takes precedence over a positive `--zoom` value because it is
checked first.

## `-0`, `--null`

Use NUL separators for stdin/output instead of newlines.

For input:

``` bash
find . -type f -print0 | tkiv.py img --stdin --null
```

For output:

``` bash
tkiv.py img --stdout --null *.jpg
```

------------------------------------------------------------------------

# 9. Viewer options that are currently parsed but unused

The following viewer options exist in the argument parser but are not
actually consulted later in the current source:

``` text
--framerate
--clean-cache
--embed
--private
--cache-allow
--cache-deny
--update-cache
```

In particular, these should **not** be documented as functional features
until the implementation is changed.

The thumbnail disk cache itself is enabled internally and uses the
constants described later in this document; the three cache-related
command-line options do not currently control it.

------------------------------------------------------------------------

# 10. Selector-only options

The selector is invoked with:

``` bash
tkiv.py select ...
```

## `--dmenu-mode`

Enable dmenu-style operation where labels and image paths are supplied
as paired lists.

``` bash
tkiv.py select \
    --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

Each line in `labels.txt` corresponds to the image on the same line in
`images.txt`.

For example:

`labels.txt`:

``` text
Cat
Dog
Landscape
```

`images.txt`:

``` text
/home/me/cat.jpg
/home/me/dog.jpg
/home/me/landscape.jpg
```

The selector displays:

``` text
Cat
Dog
Landscape
```

but internally associates those labels with the corresponding image
paths.

The two files must contain the same number of lines.

## `--list-file FILE`

Read selector labels from a file.

``` bash
tkiv.py select --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

`--list-file` and `--list-entries` are mutually exclusive.

## `--list-entries TEXT`

Supply selector labels directly as a newline-separated argument.

``` bash
tkiv.py select --dmenu-mode \
    --list-entries $'Cat\nDog\nLandscape' \
    --image-file images.txt
```

## `--image-file FILE`

Read image paths from a newline-separated file.

``` bash
tkiv.py select --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

`--image-file` and `--image-entries` are mutually exclusive.

## `--image-entries TEXT`

Supply image paths directly as newline-separated text.

``` bash
tkiv.py select --dmenu-mode \
    --list-entries $'Cat\nDog' \
    --image-entries $'/home/me/cat.jpg\n/home/me/dog.jpg'
```

The number of labels and image paths must match.

## `--return-label`

Output the selector label rather than the image path.

Without it:

``` bash
tkiv.py select --dmenu-mode \
    --list-entries $'Cat\nDog' \
    --image-entries $'/home/me/cat.jpg\n/home/me/dog.jpg'
```

accepting `Cat` outputs:

``` text
/home/me/cat.jpg
```

With:

``` bash
--return-label
```

it outputs:

``` text
Cat
```

This is useful when `tkiv` is being used as a visual front-end for a
script.

------------------------------------------------------------------------

# 11. Selector output behavior

The selector exits successfully when the selection is accepted with
`Return`.

If no entries are marked, the current entry is output.

If one or more entries are marked, all marked entries are output.

Marking:

``` text
Ctrl+M
```

or, in search-bar mode:

``` text
Ctrl+Enter
```

clears/toggles the mark on the current entry.

Accepting with `Return` then prints all marked entries.

`Esc` cancels the selector.

------------------------------------------------------------------------

# 12. Search/filter behavior

When the search bar is enabled, it is focused automatically.

Typing filters entries.

The query is:

1.  converted to lowercase,
2.  split into whitespace-separated terms,
3.  matched against both the entry label and path.

Every term must match at least one of those two fields.

For example:

``` text
cat summer
```

matches an entry if both `cat` and `summer` occur somewhere in its
label/path.

The filter is debounced by an internal 60 ms delay.

Pressing `Esc` once while a search query is active clears the query.

Pressing `Esc` again when the query is empty quits.

------------------------------------------------------------------------

# 13. Gallery behavior

Gallery tiles are calculated dynamically.

Built-in limits/constants include:

``` text
minimum tile long side: 96 px
maximum tile long side: 512 px
target rows:             3.5
caption ratio:           16%
minimum caption height:  22 px
padding ratio:           4.5%
minimum padding:         6 px
size quantum:            8 px
overscan:                2 rows
interactive zoom step:   32 px
```

These are source-level constants, not configuration-file settings.

The persistent config file currently cannot change them.

### Gallery aspect ratio

Without `--gallery-aspect`, the program samples up to 20 images and
calculates the median width/height ratio.

The result is clamped to:

``` text
0.4 <= aspect <= 3.0
```

The initial provisional value is:

``` text
16:9 = 1.777...
```

If `--gallery-aspect` is specified, that value is used instead.

### Gallery zoom

In gallery mode:

``` text
Ctrl++    enlarge tiles
Ctrl+-    shrink tiles
```

The step is 32 pixels.

The resulting long side is clamped to the 96--512 pixel range.

------------------------------------------------------------------------

# 14. Built-in image formats

The file scanner recognizes these extensions:

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

Extension matching is case-insensitive.

------------------------------------------------------------------------

# 15. Image decoding

Pillow is mandatory.

If `pyvips` and NumPy are available, tkiv uses pyvips for several
image-loading and thumbnail operations.

Otherwise it falls back to Pillow.

The program explicitly warns when pyvips is unavailable unless `--quiet`
is used.

Install Pillow:

``` bash
pip install Pillow
```

For the accelerated path:

``` bash
pip install pyvips numpy
```

The exact system-level requirements for libvips depend on the operating
system.

------------------------------------------------------------------------

# 16. Internal performance settings

The following source-level constants affect performance but are **not
currently configurable through the config file**.

``` text
IMG_WORKERS         = 4
THUMB_WORKERS       = 4
PREFETCH_MAX        = 3
THUMB_MAX_IN_FLIGHT = 12
QUEUE_POLL_MS       = 20
FILTER_DEBOUNCE_MS  = 60

LAZY_BATCH_SIZE      = 128
LISTBOX_INSERT_CHUNK = 1000
```

Thumbnail disk-cache constants:

``` text
CACHE_SIZE          = 800
PRELOAD_AHEAD       = 3
DISK_CACHE_ENABLED  = True
CACHE_WEBP_QUALITY  = 82
```

The disk-cache directory is:

``` text
$XDG_CACHE_HOME/tkiv_thumbs
```

or, when `XDG_CACHE_HOME` is unset:

``` text
~/.cache/tkiv_thumbs
```

The current source does not expose these settings through `[behavior]`.

------------------------------------------------------------------------

# 17. Runtime key reference

The built-in viewer bindings are:

  Key                        Action
  -------------------------- ------------------------------------
  `Ctrl+Q`                   Quit
  `Tab`                      Image → Gallery → List → Image
  `Shift+Tab`                Reverse mode cycle
  `Return`                   Image/Gallery switch; List → Image
  `Esc`                      Clear search, otherwise quit
  `Ctrl+F`                   Fullscreen
  `Ctrl+B`                   Status bar
  `Ctrl+R`                   Reload
  `Ctrl+D`                   Remove
  `Ctrl+N` / `Ctrl+P`        Next / previous
  `Ctrl+]` / `Ctrl+[`        ±10 entries
  `Ctrl+Home` / `Ctrl+End`   First / last
  `Ctrl+M`                   Mark
  `Ctrl+U`                   Unmark all
  `Ctrl+W`                   Fit down
  `Ctrl+Shift+W`             Fit
  `Ctrl+Shift+F`             Fill
  `Ctrl+E`                   Fit width
  `Ctrl+Shift+E`             Fit height
  `Ctrl++` / `Ctrl+-`        Zoom
  `Ctrl+0`                   100%
  `Ctrl+Z`                   Center
  `Ctrl+H/J/K/L`             Pan
  `Ctrl+Space`               Animation
  `Ctrl+S`                   Slideshow
  `Ctrl+<` / `Ctrl+>`        Rotate 90°
  `Ctrl+?`                   Rotate 180°
  `Ctrl+|`                   Flip horizontally
  `Ctrl+_`                   Flip vertically
  `Ctrl+I`                   Antialias
  `Ctrl+Shift+I`             Alpha toggle
  `Ctrl+(` / `Ctrl+)`        Contrast
  `Ctrl+{` / `Ctrl+}`        Gamma
  `Ctrl+Y`                   Sort cycle
  `Ctrl+Shift+Y`             Reverse sort
  `F2`                       Search bar/direct-key mode

Additional fixed navigation:

``` text
Arrow keys
Page Up / Page Down
Home / End
Delete
Tab / Shift+Tab
Return
Escape
```

In search-bar mode, `Ctrl+Enter` is an additional mark toggle.

------------------------------------------------------------------------

# 18. Sorting

Runtime sorting cycles through these combinations:

``` text
name ascending
name descending
mtime descending
mtime ascending
size descending
size ascending
```

`Ctrl+Y` advances through that cycle.

`Ctrl+Shift+Y` reverses the current direction.

If sorting is currently `none`, `Ctrl+Shift+Y` starts with name
ascending.

The status bar shows the active sort using an arrow, for example:

``` text
name↑
name↓
date↓
size↑
```

------------------------------------------------------------------------

# 19. Command examples

## Open one image

``` bash
tkiv.py img photo.jpg
```

## Open several images

``` bash
tkiv.py img *.jpg
```

## Open a directory

``` bash
tkiv.py img ~/Pictures
```

## Recursively open a directory

``` bash
tkiv.py img --recursive ~/Pictures
```

## Include hidden images

``` bash
tkiv.py img --recursive --hidden ~/Pictures
```

## Start in gallery mode

``` bash
tkiv.py img --gallery ~/Pictures
```

## Start with 6 gallery columns

``` bash
tkiv.py img --gallery --gallery-cols 6 ~/Pictures
```

## Start with square gallery tiles

``` bash
tkiv.py img --gallery --gallery-aspect 1 ~/Pictures
```

## Start at image 50

``` bash
tkiv.py img --start-at 50 ~/Pictures
```

## Start fullscreen

``` bash
tkiv.py img --fullscreen ~/Pictures
```

## Hide the status bar

``` bash
tkiv.py img --no-bar ~/Pictures
```

## Hide the search bar

``` bash
tkiv.py img --no-searchbar ~/Pictures
```

## Start at 200% zoom

``` bash
tkiv.py img --zoom 200 photo.jpg
```

## Start an animated image

``` bash
tkiv.py img --animate animation.gif
```

## Start a slideshow

``` bash
tkiv.py img --ss-delay 3 *.jpg
```

## Sort by newest

``` bash
tkiv.py img --sort mtime ~/Pictures
```

## Sort alphabetically, reversed

``` bash
tkiv.py img --sort name --sort-reverse ~/Pictures
```

## Read filenames from stdin

``` bash
printf '%s\n' a.jpg b.jpg c.jpg |
    tkiv.py img --stdin
```

## NUL-separated stdin

``` bash
find ~/Pictures -type f -print0 |
    tkiv.py img --stdin --null
```

## Use selector mode

``` bash
tkiv.py select ~/Pictures
```

## Use selector mode with a dmenu-style label/path mapping

``` bash
tkiv.py select --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt
```

## Return labels instead of paths

``` bash
tkiv.py select --dmenu-mode \
    --list-file labels.txt \
    --image-file images.txt \
    --return-label
```

------------------------------------------------------------------------

# 20. Configuration recipes

## Minimal dark theme

``` ini
[theme]
bg_primary = #000000
bg_secondary = #111111
bg_input = #181818
fg_text = #dddddd
fg_bright = #ffffff
accent = #ffffff
accent_fg = #000000
selected_bg = #333333
selected_fg = #ffffff
hover_border = #444444
```

## Vim-like navigation

``` ini
[keys]
next = J
prev = K
first = G
pan_left = H
pan_down = J
pan_up = K
pan_right = L
```

Note that in image mode the configurable `pan_*` actions operate on the
image, while `next`/`prev` change files. Therefore assigning both `J` to
`next` and `pan_down` would create a conflict.

Avoid overlapping bindings unless that is intentional.

## Mouse-like arrow navigation

``` ini
[keys]
next = Right
prev = Left
```

## F-key controls

``` ini
[keys]
quit = F10
fullscreen = F11
toggle_bar = F9
reload = F5
```

## Space to mark

``` ini
[keys]
toggle_mark = Space
```

In search-bar mode, typing ordinary printable characters normally goes
into the search field. A configured action binding takes precedence when
it matches a key event.

## Multiple bindings

``` ini
[keys]
next = Ctrl+N
next = Right
next = Down
```

All three trigger the same action.

------------------------------------------------------------------------

# 21. Things that are not persistent configuration options

The following are defined internally but cannot currently be changed
through `~/.config/tkiv.py/config`:

``` text
zoom levels
minimum/maximum gallery tile size
gallery target rows
gallery caption sizing
gallery padding
gallery aspect sample size
number of worker threads
prefetch size
thumbnail in-flight limit
filter debounce time
lazy-scan batch size
list insertion chunk size
thumbnail WebP quality
thumbnail cache directory
image extension list
animation fallback delay
brightness controls
contrast limits
gamma limits
```

For these, changing the Python source itself is currently required.

------------------------------------------------------------------------

# 22. Brightness note

The source contains an `act_brightness()` action internally, and
brightness state is maintained, but there is no default keyboard binding
for it and no CLI/config-file option exposing it.

Therefore brightness is **implemented internally but not currently
user-configurable through the documented interfaces**.

------------------------------------------------------------------------

# 23. Alpha-display note

`toggle_alpha` is configurable as a key action.

The command-line option is:

``` bash
--alpha-layer
```

The parser accepts an optional argument, but the current initialization
only enables the state when the value is exactly `yes`.

Consequently:

``` bash
--alpha-layer yes
```

enables the initial state, while simply writing:

``` bash
--alpha-layer
```

passes the parser's `no` value and does not enable it.

The runtime `toggle_alpha` binding can still toggle the state.

------------------------------------------------------------------------

# 24. Configuration validation checklist

A valid configuration must satisfy all of the following:

-   Use only `[keys]`, `[theme]`, and `[behavior]`.
-   Put every setting inside a section.
-   Use `key = value` syntax.
-   Use only recognized action names under `[keys]`.
-   Use a valid key sequence under `[keys]`.
-   Use only recognized theme names under `[theme]`.
-   Use exactly `#RRGGBB` colors under `[theme]`.
-   Use only `slideshow_delay` and `max_load_dim` under `[behavior]`.
-   Give behavior values positive integers.
-   Avoid accidental typos in action names.
-   Remember that one invalid line causes the **entire config file** to
    be ignored.

A safe minimal test configuration is:

``` ini
[behavior]
slideshow_delay = 5
max_load_dim = 4096
```

If this works, additional sections can be added incrementally.

------------------------------------------------------------------------

# 25. Quick reference

### Config file

``` text
~/.config/tkiv.py/config
```

or:

``` text
$XDG_CONFIG_HOME/tkiv.py/config
```

### Sections

``` ini
[keys]
[theme]
[behavior]
```

### Behavior options

``` ini
slideshow_delay = 5
max_load_dim = 4096
```

### Theme options

``` ini
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

### Main modes

``` bash
tkiv.py img ...
tkiv.py select ...
```

### Most useful viewer options

``` text
--gallery
--gallery-tile-size N
--gallery-rows N
--gallery-cols N
--gallery-aspect N
--recursive
--hidden
--sort MODE
--sort-reverse
--start-at N
--name NAME
--no-searchbar
--fullscreen
--geometry GEOMETRY
--animate
--zoom N
--zoom-100
--ss-delay N
--stdin
--null
--stdout
```

### Most useful selector options

``` text
--dmenu-mode
--list-file FILE
--list-entries TEXT
--image-file FILE
--image-entries TEXT
--return-label
```

------------------------------------------------------------------------

## Source basis

This reference is derived from the `tkiv(2).py` source, including its
argument parsers, configuration parser, default key map, theme
definitions, runtime action map, and entry points. The source identifies
the program as version `0.4.0` and documents the three configuration
sections `[keys]`, `[theme]`, and `[behavior]`. It also explicitly
states that configuration syntax errors cause the entire configuration
to fall back to defaults.
