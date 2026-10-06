# tkiv installation

This guide is for `tkiv.py` as provided.

## 1. System requirements

tkiv requires:

- Python 3
- Tkinter
- Pillow

Tkinter is part of Python's standard library, but on Linux it is commonly
provided by a separate system package. It is **not** installed through pip.

### Arch Linux

```bash
sudo pacman -S python tk
```

### Fedora

```bash
sudo dnf install python3 python3-tkinter
```

### Debian / Ubuntu

```bash
sudo apt install python3 python3-tk
```

If your distribution uses a different package name, install the package that
provides Python's `tkinter` module.

## 2. Create a virtual environment

A virtual environment is recommended so that tkiv's Python dependencies do
not interfere with system Python packages.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Install the Python dependencies

Install the supplied requirements file:

```bash
python -m pip install -r requirements.txt
```

The requirements file contains Pillow as the required dependency.

## 4. Optional: install pyvips acceleration

tkiv can use `pyvips` and NumPy for an alternative image-decoding and
thumbnail-generation path. They are optional: if they are unavailable,
tkiv falls back to Pillow.

The source checks for `pyvips` and `numpy` together, so both should be
installed for the accelerated path.

First install the system `libvips` library.

### Arch Linux

```bash
sudo pacman -S libvips
```

### Fedora

```bash
sudo dnf install vips
```

### Debian / Ubuntu

```bash
sudo apt install libvips-dev
```

Then install the Python packages:

```bash
python -m pip install pyvips numpy
```

Alternatively, uncomment the `pyvips` and `numpy` lines in
`requirements.txt` and run:

```bash
python -m pip install -r requirements.txt
```

If `libvips` is not installed correctly, the Python `pyvips` package alone
may not be sufficient.

## 5. Install/run tkiv

The program is a standalone Python script. It does not require a Python
package installation to run.

For example:

```bash
python tkiv(4).py image.jpg
```

or:

```bash
python tkiv(4).py img image.jpg
```

For selector mode:

```bash
python tkiv(4).py select ~/Pictures
```

If the script is executable:

```bash
chmod +x tkiv(4).py
./tkiv(4).py image.jpg
```

## 6. Install as `tkiv`

If you want to invoke it simply as `tkiv`, place it somewhere on your PATH.

For a per-user installation:

```bash
mkdir -p ~/.local/bin
cp tkiv(4).py ~/.local/bin/tkiv
chmod +x ~/.local/bin/tkiv
```

Make sure `~/.local/bin` is in your PATH:

```bash
echo "$PATH"
```

Then:

```bash
tkiv image.jpg
```

If `~/.local/bin` is not in your PATH, add it to your shell configuration,
for example in `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then start a new shell or source the file:

```bash
source ~/.bashrc
```

## 7. Configuration directory

tkiv looks for its configuration at:

```text
~/.config/tkiv.py/config
```

or, when `XDG_CONFIG_HOME` is set:

```text
$XDG_CONFIG_HOME/tkiv.py/config
```

Create the directory when needed:

```bash
mkdir -p ~/.config/tkiv.py
```

The configuration file is optional.

See the tkiv documentation for the complete `[keys]`, `[theme]`, and
`[behavior]` configuration reference.

## 8. Verify the installation

Check that Python can import both Pillow and Tkinter:

```bash
python -c 'from PIL import Image; import tkinter; print("Pillow and Tkinter OK")'
```

Then check tkiv itself:

```bash
python tkiv(4).py --help
```

Depending on how the script's command dispatcher is invoked, the subcommand
help can also be checked with:

```bash
python tkiv(4).py img --help
python tkiv(4).py select --help
```

## 9. Verify optional pyvips support

If you installed pyvips and NumPy:

```bash
python -c 'import pyvips, numpy; print("pyvips:", pyvips.version(0), "numpy:", numpy.__version__)'
```

When tkiv starts normally with pyvips available, it uses the pyvips path
instead of printing its "pyvips not available; falling back to Pillow"
warning.

If pyvips is not available, this is not a fatal error. tkiv is designed to
fall back to Pillow.

## 10. Troubleshooting

### `ModuleNotFoundError: No module named 'PIL'`

Install Pillow:

```bash
python -m pip install Pillow
```

or reinstall all Python dependencies:

```bash
python -m pip install -r requirements.txt
```

### `ModuleNotFoundError: No module named 'tkinter'`

Tkinter is a system package rather than a pip dependency. Install the
appropriate package for your distribution.

For example, on Arch:

```bash
sudo pacman -S tk
```

### `cannot open display`

tkiv is a graphical Tkinter application. It needs access to a graphical
display. Check that `DISPLAY` or the relevant graphical-session environment
is available and that you are running it from a graphical session.

### pyvips warning

A warning that pyvips is unavailable does not prevent tkiv from working.
The program falls back to Pillow.

Install the optional dependencies if you want the pyvips path:

```bash
sudo pacman -S libvips       # Arch
python -m pip install pyvips numpy
```

Replace the system package command with the equivalent for your distribution.

## 11. Recommended minimal installation

For a normal Pillow-based installation:

```bash
sudo pacman -S python tk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python tkiv(4).py image.jpg
```

For Arch Linux with the optional pyvips path:

```bash
sudo pacman -S python tk libvips
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pyvips numpy
python tkiv(4).py image.jpg
```
