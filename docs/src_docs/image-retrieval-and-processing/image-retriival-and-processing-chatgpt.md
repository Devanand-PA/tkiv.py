# tkiv — Image Retrieval and Processing Pipeline

## 1. Overview

`tkiv` is a Tkinter-based image viewer/selector. Its image pipeline is deliberately split into several stages rather than treating "load an image" as a single operation.

At a high level, the program does this:

```text
Command-line arguments
        │
        ▼
   File discovery
        │
        ▼
     FileEntry
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
   Image mode                     Gallery mode
        │                              │
        ▼                              ▼
 asynchronous decode             thumbnail decode
        │                              │
        ▼                              ▼
 load_frames()                 load_gallery_thumb()
        │                              │
        ▼                              ▼
 Pillow / pyvips                 Pillow / pyvips
        │                              │
        ▼                              ▼
 frame list                     thumbnail image
        │                              │
        └──────────────┬───────────────┘
                       ▼
                 PIL Image object
                       │
                       ▼
                ImageTk.PhotoImage
                       │
                       ▼
                  Tkinter Canvas
```

There are actually **three different image-loading paths**:

1. **Full image loading** for the main image viewer.
2. **Thumbnail loading** for the gallery.
3. **Preview loading** for the list mode.

The program also has a separate thumbnail-cache function, `_decode_thumb()`, which implements a persistent WebP disk cache. The gallery's current loading path, however, uses `load_gallery_thumb()` directly rather than `_decode_thumb()`.

The program prefers **pyvips** when available and falls back to **Pillow**. Pillow is mandatory; pyvips and NumPy are optional. The source explicitly warns that Pillow becomes the decoding fallback when pyvips is unavailable.

---

# 2. Image Discovery

Before any image can be decoded, `tkiv` needs a list of paths.

The program recognizes images primarily through their filename extension.

The supported extensions are:

```text
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

This is represented by `IMAGE_EXTS`. `file_is_image()` then performs a case-insensitive extension test.

In other words:

```python
file_is_image(path)
```

essentially means:

```python
extension = os.path.splitext(path)[1].lower()
return extension in IMAGE_EXTS
```

This is important because `tkiv` does **not** first inspect the contents of every file to determine whether it is an image. The initial discovery mechanism is extension-based.

Actual decoding happens later, and a file whose extension looks valid can still fail during decoding.

---

# 3. Directory Traversal

When a directory is supplied, `collect_dir()` walks through it.

The basic process is:

```text
directory
   │
   ├── ordinary files
   │       └── if regular file + recognized extension → image list
   │
   └── subdirectories
           └── recurse only if --recursive
```

The function first obtains directory entries with:

```python
os.listdir(d)
```

and sorts them.

For each entry it:

1. Excludes hidden names unless `include_hidden` is enabled.
2. Builds the full path.
3. Calls `os.stat()`.
4. Checks whether it is a directory or regular file.
5. Adds recognized image files.
6. Recurses into subdirectories if requested.

This means directory traversal itself does **not decode image data**. It only discovers candidate paths.

That separation is useful because discovering thousands of filenames is considerably cheaper than decoding thousands of images.

---

# 4. Non-Lazy Versus Lazy Discovery

`tkiv` has two fundamentally different discovery modes.

## 4.1 Normal discovery

Without `--lazy`, directories are scanned before the Tk application starts.

The resulting paths become:

```python
entries = [FileEntry(p) for p in file_list]
```

and are passed to `TkivApp`.

Thus:

```text
filesystem
    ↓
directory scan
    ↓
complete file list
    ↓
TkivApp
    ↓
image loading
```

## 4.2 Lazy discovery

With `--lazy`, directories are not completely scanned before the interface appears.

Instead, directory paths are stored in `scan_paths`, and `start_lazy_scan()` launches a background scanning thread.

The scanner collects images into batches of:

```python
LAZY_BATCH_SIZE = 128
```

and sends those batches back to the Tk main thread.

The architecture therefore becomes:

```text
Tk main thread
      │
      ├── GUI remains responsive
      │
      └── receives discovered paths
                  ▲
                  │
          background scan thread
                  │
              filesystem
```

The scanner eventually calls `_lazy_scan_finished()`.

The main thread then incorporates the newly discovered files into `self.files`, extends the thumbnail array, updates filtering state, and redraws the relevant UI.

This is particularly important for directories containing very large numbers of images.

---

# 5. FileEntry: The Object Representing an Image

A discovered path becomes a `FileEntry`.

Conceptually:

```python
FileEntry(
    path,
    label=os.path.basename(path)
)
```

Each entry contains:

```text
name
path
flags
label
```

The actual filesystem path is stored separately from the human-readable label.

This distinction matters because filtering and captions operate on `label` and/or `path`, while decoding always ultimately needs `path`.

---

# 6. The Two Image Libraries

The image pipeline is built around two libraries:

## Pillow

Pillow is required.

It provides:

* image decoding fallback
* image representation
* resizing
* cropping
* color conversion
* image enhancements
* animation frame handling
* Tkinter integration through `ImageTk`

The program imports:

```python
Image
ImageTk
ImageOps
ImageEnhance
ImageFile
```

and enables:

```python
ImageFile.LOAD_TRUNCATED_IMAGES = True
```

The latter tells Pillow to permit loading certain truncated images rather than immediately rejecting them.

## pyvips

pyvips is optional.

When available, the program sets:

```python
HAVE_VIPS = True
HAS_VIPS = True
HAS_NUMPY = True
```

and uses libvips for several decoding and thumbnail operations. When pyvips is unavailable, the program falls back to Pillow.

This produces a general architecture of:

```text
                 Image file
                     │
             ┌───────┴───────┐
             │               │
       pyvips available?     no
             │               │
            yes              ▼
             │             Pillow
             ▼
          pyvips
```

The fallback is generally implemented with:

```python
try:
    ...
except Exception:
    ...
```

rather than making pyvips a hard dependency.

---

# 7. Full Image Loading

The primary image-viewer path begins with:

```python
load_frames(path, max_dim=MAX_LOAD_DIM)
```

where:

```python
MAX_LOAD_DIM = 4096
```

The application can override this through its behavior configuration.

The function first tries pyvips:

```python
if HAVE_VIPS:
    try:
        return _vips_load_frames(path, max_dim=max_dim)
    except Exception:
        pass

return _pil_load_frames(path)
```

So the hierarchy is:

```text
load_frames()
    │
    ├── pyvips → _vips_load_frames()
    │
    └── failure/unavailable
             ↓
        _pil_load_frames()
```

---

# 8. Full Image Loading With pyvips

`_vips_load_frames()` opens the image with:

```python
pyvips.Image.new_from_file(path, n=-1)
```

The `n=-1` request is intended to make libvips load all pages/frames when the underlying format supports multiple pages. If that fails, the function retries without `n=-1`.

The code then determines the number of pages:

```python
n_pages = int(vimg.get('n-pages') or 1)
```

with a minimum of one page.

---

# 9. The 4096-Pixel Maximum Dimension

One of the most important parts of the full-image pipeline is that the viewer does not necessarily decode an arbitrarily enormous source image at its original dimensions.

The code calculates:

```python
scale = max(
    vimg.width / max_dim,
    vimg.height / max_dim
)
```

If that value exceeds `1.0`, the image is resized:

```python
vimg = vimg.resize(1.0 / scale)
```

Therefore, the resulting image is constrained so that its largest dimension is approximately `max_dim`.

With the default:

```text
max_dim = 4096
```

an enormous image such as:

```text
12000 × 8000
```

would be reduced before becoming the Pillow image used by the viewer.

Conceptually:

```text
12000 × 8000
       │
       │ largest dimension = 12000
       ▼
scale = 12000 / 4096
       │
       ▼
approximately 4096 × 2731
```

This is an important distinction:

> The viewer's "full image" is not necessarily the source image at native resolution.

It is the decoded image after the maximum-dimension reduction.

---

# 10. Converting pyvips Images to Pillow

Tkinter's `ImageTk.PhotoImage` expects a Pillow image, so pyvips data eventually needs to cross into Pillow.

That happens through:

```python
_vips_to_pil(vimg)
```

The function first ensures an 8-bit unsigned-byte representation:

```python
if vimg.format != 'uchar':
    vimg = vimg.cast('uchar')
```

It then obtains a NumPy array:

```python
arr = vimg.numpy()
```

and examines the number of bands/channels.

The mapping is:

| pyvips bands | Pillow mode                  |
| -----------: | ---------------------------- |
|            1 | `L`                          |
|            2 | `LA`                         |
|            3 | `RGB`                        |
|            4 | `RGBA`                       |
|           >4 | first four channels → `RGBA` |

For non-contiguous NumPy arrays, the code creates a contiguous copy before handing the data to Pillow.

So the conversion path is:

```text
libvips image
      │
      ▼
uchar conversion
      │
      ▼
NumPy array
      │
      ▼
contiguous array if necessary
      │
      ▼
Pillow Image
```

---

# 11. Multi-Frame Images

`tkiv` does not restrict the main viewer to single-frame images.

If pyvips reports multiple pages, the combined image is treated as a sequence of frames.

The code calculates:

```python
page_height = vimg.height // n_pages
```

and then extracts each page with:

```python
vimg.crop(
    0,
    i * page_height,
    vimg.width,
    page_height
)
```

Each resulting page is converted to a Pillow image.

The corresponding frame delays are obtained from the `delay` metadata when available.

Missing or invalid delays become:

```python
DEF_ANIM_DELAY = 75
```

milliseconds.

Thus the return value is:

```python
frames, delays
```

rather than simply one image.

---

# 12. Pillow's Full Image Path

If pyvips is unavailable or fails, `_pil_load_frames()` handles the image.

It starts with:

```python
im = Image.open(path)
```

and checks:

```python
n_frames = getattr(im, 'n_frames', 1)
```

For multi-frame images it loops through every frame:

```python
im.seek(i)
f = im.convert('RGBA').copy()
```

The `.copy()` is important because it detaches the resulting frame from Pillow's underlying image object.

The duration is obtained from:

```python
im.info.get('duration', DEF_ANIM_DELAY)
```

and converted to at least one millisecond.

For ordinary single-frame images, the original Pillow image is retained if its mode is already one of:

```text
RGB
RGBA
L
LA
```

Otherwise it is converted to `RGBA`.

So:

```text
Single frame
    │
    ├── RGB/RGBA/L/LA → retain
    │
    └── other mode → convert RGBA
```

---

# 13. Full Image Loading Is Asynchronous

The GUI does not normally decode the current image directly on the Tkinter event loop.

The asynchronous entry point is:

```python
load_image_async(n)
```

It increments:

```python
self._load_token
```

and records the resulting token.

The token is later used to determine whether the result is still relevant.

The actual decoding is submitted through `_request_decode()`, which uses:

```python
self._img_executor
```

The executor is created with:

```python
ThreadPoolExecutor(
    max_workers=IMG_WORKERS,
    thread_name_prefix='tkiv-img'
)
```

and:

```python
IMG_WORKERS = 4
```

So up to four image-decoding worker threads can be active.

---

# 14. Why the Token Exists

Imagine the user rapidly presses:

```text
next
next
next
```

while the first image is still decoding.

The requests could finish in a different order from the order in which they were initiated.

Without protection, an old decode result could overwrite the currently selected image.

The program avoids this with:

```python
token = self._load_token
```

and later:

```python
if token != self._load_token:
    return
```

Therefore:

```text
Request A → token 10
Request B → token 11
Request C → token 12

A finishes late
     ↓
token 10 != current token 12
     ↓
discard

C finishes
     ↓
token 12 == current token 12
     ↓
display
```

This is a classic stale-result protection mechanism.

---

# 15. Avoiding Duplicate Decodes

`_request_decode()` maintains:

```python
self._img_in_flight
```

indexed by image index.

If an image is already being decoded:

```python
fut = self._img_in_flight.get(n)
```

returns its existing future.

The program therefore does not unnecessarily submit another decode of the same image.

The lifecycle is roughly:

```text
request image N
      │
      ▼
already decoding N?
   ┌──┴──┐
  yes    no
   │      │
   │      ▼
   │   submit worker
   │      │
   └──┬───┘
      ▼
 attach callback
```

---

# 16. Moving Results Back to Tkinter

Worker threads do not directly manipulate the Tkinter UI.

Instead, completed workers call:

```python
self._post(...)
```

which places a callable into:

```python
self._main_queue
```

The Tk thread periodically executes `_poll_main_queue()`.

It processes up to 64 queued callbacks at a time and schedules itself again after:

```python
QUEUE_POLL_MS = 20
```

milliseconds.

This produces a clean separation:

```text
Worker thread
    │
    │ decode
    ▼
Future callback
    │
    │ _post()
    ▼
main_queue
    │
    │ every ~20 ms
    ▼
Tk main thread
    │
    ▼
update widgets/canvas
```

This is particularly important because Tkinter is fundamentally GUI-thread oriented.

---

# 17. Installing a Decoded Image

Once an asynchronous result has passed the token check, `_install_image()` becomes responsible for making it the current image.

It stores:

```python
self.img_frames = frames
self.img_delays = delays
self.img_sel = 0
```

and obtains the first frame's dimensions:

```python
self.img_w, self.img_h = frames[0].size
```

It also calculates:

```python
self.img_multi_len = sum(delays)
```

for multi-frame images.

The current file's modification time is recorded in `_mtimes`, allowing the automatic-reload system to notice later modifications.

---

# 18. Neighbor Prefetching

After displaying an image, the viewer proactively loads neighboring images.

`_prefetch_neighbors()` looks at the current position in:

```python
self._visible_indices
```

and requests:

```text
next image
previous image
```

if they exist.

The prefetch cache is:

```python
self._prefetch_cache = OrderedDict()
```

with:

```python
PREFETCH_MAX = 3
```

So the program retains up to three decoded neighboring images.

The cache behaves approximately like an LRU cache:

```text
newly used item
      ↓
move_to_end()

too many items
      ↓
popitem(last=False)
      ↓
oldest item removed
```

This makes sequential browsing much faster because the next image may already be decoded before the user requests it.

---

# 19. Prefetch Is Different From Thumbnail Loading

There are two separate forms of preparation:

### Main viewer prefetch

```text
load_frames()
      ↓
complete decoded frame list
      ↓
_prefetch_cache
```

### Gallery thumbnails

```text
load_gallery_thumb()
      ↓
small resized image
      ↓
tns_thumbs
```

The first stores full viewer frames.

The second stores small display images.

They are deliberately separate because the requirements are different.

---

# 20. Gallery Thumbnail Loading

The gallery does not load every source image at full size.

Each tile requests:

```python
load_gallery_thumb(path, max_w, max_h)
```

With pyvips available:

```python
pyvips.Image.thumbnail(
    path,
    max_w,
    height=max_h
)
```

is used.

The resulting vips image is converted to Pillow and forced into `RGBA`.

Without pyvips:

```python
Image.open(path).convert('RGBA')
```

is followed by:

```python
im.thumbnail((max_w, max_h), Image.LANCZOS)
```

Therefore the gallery deliberately performs a bounded decode/resize rather than loading the entire source image into memory.

---

# 21. Gallery Thumbnail Worker Pool

The gallery has a separate worker pool:

```python
self._thumb_executor = ThreadPoolExecutor(
    max_workers=THUMB_WORKERS,
    thread_name_prefix='tkiv-thumb'
)
```

with:

```python
THUMB_WORKERS = 4
```

This is independent of the four image-viewer workers.

There is also a separate limit:

```python
THUMB_MAX_IN_FLIGHT = 12
```

which prevents the gallery from submitting an unlimited number of thumbnail jobs.

---

# 22. Gallery Thumbnail State

The application initially creates:

```python
self.tns_thumbs = [None] * len(self.files)
```

So there is one thumbnail slot for each file.

A slot eventually becomes something equivalent to:

```python
(
    PhotoImage,
    width,
    height
)
```

rather than merely a PIL image.

The separate width and height are useful because the renderer needs to center the actual thumbnail inside the tile.

---

# 23. Gallery Rendering Is Viewport-Aware

A major optimization is that `render_gallery()` does **not** request thumbnails for every image in the directory.

It determines which rows are currently visible and adds:

```python
GALLERY_OVERSCAN_ROWS = 2
```

extra rows before and after the visible region.

Conceptually:

```text
             visible viewport

       ┌─────────────────────┐
       │ overscan row         │
       │ overscan row         │
       ├─────────────────────┤
       │ visible row          │
       │ visible row          │
       │ visible row          │
       ├─────────────────────┤
       │ overscan row         │
       │ overscan row         │
       └─────────────────────┘
```

Only the resulting position range is processed for thumbnail submission.

This is a major scalability feature.

A gallery containing 20,000 images does not immediately decode 20,000 thumbnails.

---

# 24. Gallery Thumbnail Submission

For each visible/overscanned image:

```python
_submit_gallery_tile(i)
```

checks:

1. Is the index valid?
2. Does a thumbnail already exist?
3. Is a thumbnail already being decoded?
4. Has the in-flight limit been reached?

Only if all checks pass does it submit:

```python
self._thumb_executor.submit(
    load_gallery_thumb,
    path,
    tw,
    th
)
```

where:

```python
tw, th = self._tile_thumb_max
```

The generation number is captured at submission time.

---

# 25. Gallery Generation Numbers

The gallery has another stale-result protection mechanism:

```python
self._files_gen
```

When the file collection changes significantly—for example after sorting, removal, or gallery-aspect recalculation—the generation is incremented.

A thumbnail worker captures:

```python
gen = self._files_gen
```

When the worker finishes:

```python
if gen != self._files_gen:
    return
```

This prevents a thumbnail generated for an obsolete layout/file ordering from being inserted into the new gallery state.

There are therefore two related but separate concepts:

```text
_load_token
    → protects current image loads

_files_gen
    → protects file/gallery state
```

---

# 26. Converting Gallery Thumbnails to Tk Images

When a thumbnail finishes decoding:

```python
pil = f.result()
```

and the result is passed to:

```python
_on_gallery_tile_ready()
```

The program converts it to:

```python
ImageTk.PhotoImage(pil)
```

and stores:

```python
(ph, pil.size[0], pil.size[1])
```

in `self.tns_thumbs[i]`.

This conversion is necessary because a PIL image by itself is not a Tkinter canvas image.

The actual chain is:

```text
source file
    ↓
pyvips/Pillow
    ↓
PIL.Image
    ↓
ImageTk.PhotoImage
    ↓
Tk Canvas
```

---

# 27. Why `_gallery_photos` Exists

Tkinter `PhotoImage` objects have an important lifetime requirement: Python must retain a reference to them.

The renderer therefore keeps the currently displayed gallery photos in:

```python
self._gallery_photos
```

while rendering.

The thumbnail cache itself also stores the `PhotoImage` object, which keeps it alive for future redraws.

Without such references, images can disappear from Tk widgets even though the canvas item still exists conceptually.

---

# 28. Gallery Tile Dimensions

Gallery thumbnails are not assigned a fixed universal size.

The program computes tile dimensions based on:

* window width
* window height
* desired row count
* optional column count
* desired aspect ratio
* explicit tile-size override

Relevant constants include:

```python
GALLERY_TILE_MIN = 96
GALLERY_TILE_MAX = 512
GALLERY_TARGET_ROWS = 3.5
GALLERY_SIZE_QUANTUM = 8
```

and the gallery uses a caption and padding allowance.

The resulting thumbnail maximum is approximately:

```python
(tile_width - 5, tile_height - 5)
```

so the actual image has a small margin within the tile.

---

# 29. Automatic Gallery Aspect Ratio Detection

One of the more sophisticated parts of the gallery is that its tile aspect ratio can be inferred from the images.

If:

```text
--gallery-aspect
```

is explicitly supplied, that value is used.

Otherwise the program samples:

```python
GALLERY_ASPECT_SAMPLE = 20
```

images.

For each image it obtains the original dimensions through:

```python
_get_orig_size()
```

and calculates:

```python
width / height
```

The ratios are sorted and the middle value is selected. In other words, the gallery uses a median-like representative aspect ratio rather than simply assuming 16:9.

The resulting aspect ratio is clamped to:

```text
0.4 ≤ aspect ≤ 3.0
```

If the calculation has not completed yet, the gallery temporarily uses:

```python
GALLERY_ASPECT_DEFAULT = 16.0 / 9.0
```

---

# 30. `_get_orig_size()` Does Not Decode the Whole Image

The aspect-ratio calculation needs dimensions but does not need actual pixel data.

`_get_orig_size()` therefore tries:

```python
pyvips.Image.new_from_file(
    path,
    access='sequential'
)
```

and simply reads:

```python
v.width
v.height
```

If that fails, Pillow is used:

```python
with Image.open(path) as img:
    return img.size
```

So this operation is intentionally much cheaper than loading all pixels.

This distinction is important:

```text
get dimensions
    ≠
decode image pixels
```

The program uses the cheaper operation whenever it only needs geometry information.

---

# 31. Gallery Aspect Recalculation

The aspect-ratio detection is itself asynchronous.

A small daemon thread reads dimensions for the sample and posts the resulting ratios back to the Tk thread.

Initially:

```text
aspect cache = None
```

Then:

```text
start worker
     ↓
return provisional 16:9
     ↓
gallery renders immediately
     ↓
worker calculates real median
     ↓
main thread receives result
     ↓
replace aspect ratio
```

If the newly calculated ratio differs from the provisional one, the program invalidates the existing thumbnails:

```python
self._files_gen += 1
self.tns_thumbs = [None] * len(self.files)
self._gallery_in_flight.clear()
```

and redraws the gallery.

This means gallery thumbnails may be decoded twice in some circumstances:

1. once using the provisional tile geometry;
2. again after the real aspect ratio is known.

That is intentional: the first pass makes the UI appear quickly, while the second pass corrects the geometry.

---

# 32. The Persistent Thumbnail Cache

There is a second thumbnail mechanism implemented by:

```python
_decode_thumb()
```

It is separate from `load_gallery_thumb()`.

The cache is enabled by:

```python
DISK_CACHE_ENABLED = True
```

and stored under:

```python
$XDG_CACHE_HOME/tkiv_thumbs
```

or, if `XDG_CACHE_HOME` is not set:

```text
~/.cache/tkiv_thumbs
```

The cached format is WebP with:

```python
CACHE_WEBP_QUALITY = 82
```

---

# 33. How the Disk Cache Key Works

The cache filename is generated from:

```python
path
mtime_ns
file_size
requested_width
requested_height
```

specifically:

```python
f"{path}|{st.st_mtime_ns}|{st.st_size}|{w}x{h}"
```

which is SHA-1 hashed.

So conceptually:

```text
source path
     +
modification timestamp
     +
file size
     +
thumbnail dimensions
     │
     ▼
   SHA-1
     │
     ▼
cache filename
```

The first two hexadecimal characters of the SHA-1 are used as a directory prefix:

```text
cache/
  ab/
     abcdef....webp
```

This prevents all cache files from accumulating in a single enormous directory.

---

# 34. Why the Cache Invalidates When an Image Changes

Suppose:

```text
photo.jpg
```

produces a cached thumbnail.

If the file is later modified, its:

```text
mtime_ns
```

and/or:

```text
file size
```

will normally change.

Therefore the resulting SHA-1 changes.

The old cache entry remains associated with the old file state, while the new state gets a different cache key.

This avoids explicitly maintaining a separate database of cache metadata.

It is effectively content-state addressing based on:

```text
path + mtime + size + requested dimensions
```

rather than a hash of the image's actual pixel contents.

---

# 35. Disk Cache Read Path

`_decode_thumb()` first obtains:

```python
orig_size = _get_orig_size(path)
```

then constructs the cache path.

If the WebP cache file exists:

```python
with Image.open(cache_file) as img:
    img.load()
    return img, orig_size
```

So a valid cache hit avoids decoding the original image.

If the cached WebP cannot be read, it is deleted:

```python
cache_file.unlink()
```

and the original image is decoded instead.

---

# 36. Disk Cache Creation

If the thumbnail does not exist in the cache, `_decode_thumb()` creates it.

With pyvips and NumPy available, it uses:

```python
pyvips.Image.thumbnail(
    path,
    max_w,
    height=max_h,
    size="down"
)
```

and converts the resulting NumPy array into a Pillow image.

If that fails, Pillow takes over.

---

# 37. Pillow's Cached Thumbnail Path

The Pillow fallback has several optimizations.

For JPEG files:

```python
img.draft("RGB", (max_w, max_h))
```

is attempted.

For extremely large images, the code may first use:

```python
img.reduce(factor)
```

before the final thumbnail operation.

It then calls:

```python
img.thumbnail(
    (max_w, max_h),
    Image.Resampling.BILINEAR,
    reducing_gap=2.0
)
```

and converts the image into either RGB or RGBA.

The important idea is:

```text
huge image
   ↓
possibly JPEG draft decode
   ↓
possibly integer reduction
   ↓
thumbnail resize
   ↓
RGB/RGBA
```

This avoids unnecessarily carrying a giant full-resolution image through multiple processing steps.

---

# 38. Writing the WebP Cache Safely

The cache is not written directly to its final filename.

Instead:

```python
tmp = cache_file.with_name(
    cache_file.name + ".tmp"
)
```

The image is saved there:

```python
pil_img.save(
    tmp,
    "WEBP",
    quality=CACHE_WEBP_QUALITY,
    method=0
)
```

and then:

```python
os.replace(tmp, cache_file)
```

is used.

This is an atomic-style replacement strategy:

```text
write temporary file
       ↓
complete write
       ↓
atomic replacement
       ↓
final cache file
```

It prevents a partially written thumbnail from normally appearing under the final cache filename.

---

# 39. An Important Distinction: `_decode_thumb()` Is Not the Gallery's Main Path

The source contains both:

```python
_decode_thumb()
```

and:

```python
load_gallery_thumb()
```

but the current gallery submission code explicitly calls:

```python
self._thumb_executor.submit(
    load_gallery_thumb,
    path,
    tw,
    th
)
```

rather than `_decode_thumb()`.

Therefore the persistent WebP cache implemented by `_decode_thumb()` should **not** be assumed to be active for the current gallery thumbnail path.

This is a significant architectural detail.

The source currently contains two thumbnail-generation mechanisms:

```text
                         Thumbnail mechanisms
                                │
                ┌───────────────┴───────────────┐
                │                               │
        load_gallery_thumb()              _decode_thumb()
                │                               │
       current gallery path              disk-cache path
                │                               │
       pyvips/Pillow resize              cache → pyvips/Pillow
                │                               │
       in-memory tns_thumbs              persistent WebP cache
```

The code does not show `_decode_thumb()` being submitted by `_submit_gallery_tile()`.

---

# 40. List Mode Uses the Full-Image Loader

The list view behaves differently from the gallery.

When the selected item changes, `render_list()` calculates the available preview dimensions:

```python
pw = max(self.list_preview.winfo_width(), 64)
ph = max(self.list_preview.winfo_height(), 64)
```

and submits:

```python
load_frames(
    self.files[target].path,
    max(pw, ph)
)
```

to the image executor.

So list mode does **not** use `load_gallery_thumb()`.

It uses the same general full-frame loader as image mode, but gives it a dimension corresponding to the preview area.

---

# 41. List Preview Processing

When the list preview finishes decoding, `_apply_list_preview()` takes only:

```python
frames[0]
```

Thus even if the image is animated, the list preview displays only the first frame.

It copies that frame:

```python
im = frames[0].copy()
```

and then performs:

```python
im.thumbnail((pw, ph), Image.LANCZOS)
```

before converting it to:

```python
ImageTk.PhotoImage(im)
```

and assigning it to the preview label.

So:

```text
image file
    ↓
load_frames()
    ↓
possibly multiple frames
    ↓
frames[0]
    ↓
thumbnail()
    ↓
ImageTk.PhotoImage
    ↓
Label
```

---

# 42. Main Image Rendering Does Not Resize the Whole Image Every Time

Once the current image has been decoded, the rendering stage takes a different approach.

`render_image()` first determines the zoom factor.

Then it determines which portion of the source image is actually visible:

```python
x0
y0
x1
y1
```

It converts these into integer source-image coordinates:

```python
ix0
iy0
ix1
iy1
```

and crops only that region:

```python
cropped = frame.crop(
    (ix0, iy0, ix1, iy1)
)
```

This is a very important optimization.

Instead of doing:

```text
full 4096×3000 image
       ↓
resize entire image
       ↓
display only center
```

the renderer can do:

```text
4096×3000 source
       ↓
determine visible rectangle
       ↓
crop visible rectangle
       ↓
process crop
       ↓
resize crop
       ↓
display
```

---

# 43. Why Cropping First Matters

Suppose the source image is:

```text
4096 × 3000
```

but the user has zoomed in so only:

```text
1000 × 700
```

of the source is visible.

The program crops the approximately visible 1000×700 source region before resizing it.

This substantially reduces the amount of pixel data involved in:

* color adjustments
* resampling
* conversion to `PhotoImage`

especially during high zoom levels or panning.

---

# 44. Color Processing Happens on the Visible Crop

The cropped image is passed to:

```python
_prepare_crop()
```

This function handles:

* alpha flattening
* mode conversion
* brightness
* contrast
* gamma

For RGBA images, the code creates an RGB background using the viewer's background color and composites the image over it.

Therefore alpha is not necessarily preserved all the way into the final Tk canvas representation.

Instead:

```text
RGBA image
    ↓
background image
    ↓
alpha composite
    ↓
RGB
```

when `_prepare_crop()` is used in normal image rendering.

---

# 45. Brightness

Brightness is controlled through:

```python
ImageEnhance.Brightness(im).enhance(...)
```

The adjustment is calculated by `_steps_to_range()`.

The source defines:

```python
BRIGHTNESS_MAX = 2.0
CC_STEPS = 32
```

so the brightness control is converted from its integer step representation into a multiplicative brightness factor.

---

# 46. Contrast

Contrast uses:

```python
ImageEnhance.Contrast(im).enhance(...)
```

with:

```python
CONTRAST_MAX = 4.0
```

Again, the internal control value is translated into a continuous enhancement factor by `_steps_to_range()`.

---

# 47. Gamma

Gamma is implemented manually using a lookup table.

The code computes a gamma value and its reciprocal:

```python
inv = 1.0 / max(0.01, g)
```

then constructs 256 lookup entries:

```python
255 * ((i / 255.0) ** inv)
```

The LUT is applied with:

```python
im.point(lut)
```

for grayscale or:

```python
im.point(lut * 3)
```

for RGB.

Thus gamma correction is performed on the crop rather than the entire decoded source image.

---

# 48. Final Image Resampling

After processing the visible crop, the renderer calculates the destination dimensions:

```python
dw = int((ix1 - ix0) * z + 0.5)
dh = int((iy1 - iy0) * z + 0.5)
```

The resampling algorithm depends on antialiasing:

```python
Image.BICUBIC
```

when antialiasing is enabled, or:

```python
Image.NEAREST
```

when it is disabled.

Therefore:

```text
source crop
    │
    ├── antialias on  → BICUBIC
    │
    └── antialias off → NEAREST
```

---

# 49. Final Conversion to Tkinter

The final resized Pillow image becomes:

```python
self.tk_img = ImageTk.PhotoImage(resized)
```

The canvas is cleared:

```python
self.canvas.delete('all')
```

and the image is inserted:

```python
self.canvas.create_image(
    self.img_x + ix0 * z,
    self.img_y + iy0 * z,
    anchor='nw',
    image=self.tk_img
)
```

So the final display stage is:

```text
Pillow Image
     ↓
ImageTk.PhotoImage
     ↓
Tk Canvas image item
```

---

# 50. Fit Modes

The image's zoom factor is calculated from the window and image dimensions.

The program calculates:

```python
zw = window_width / image_width
zh = window_height / image_height
```

and then selects a scale according to the active mode.

The available modes include:

```text
fit-down
fit
fill
fit-width
fit-height
explicit zoom
```

For normal fit mode:

```python
z = min(zw, zh)
```

For fill:

```python
z = max(zw, zh)
```

For width:

```python
z = zw
```

For height:

```python
z = zh
```

For fit-down, the result is additionally capped at:

```python
1.0
```

so an image smaller than the window is not automatically enlarged.

---

# 51. Panning

Panning is handled by `img_x` and `img_y`.

Before rendering, `_check_pan()` ensures that:

* small images are centered;
* large images cannot be moved beyond their boundaries.

The crop coordinates are then derived from those offsets and the zoom level.

Thus panning does not trigger a new source decode.

The already-decoded frame remains in memory, while a different crop is selected for display.

---

# 52. Animation

For animated/multi-frame images:

```python
self.img_frames
```

contains all decoded frames and:

```python
self.img_delays
```

contains their delays.

If animation is enabled, `_schedule_animate()` schedules the next frame using the current frame's delay.

`animate()` then:

```python
self.img_sel = (self.img_sel + 1) % len(self.img_frames)
```

updates the selected frame and calls:

```python
self.redraw()
```

Importantly, animation does **not** repeatedly decode the source file.

All frames were decoded during the original `load_frames()` operation.

---

# 53. Automatic Reload

The program periodically checks the modification time of the currently displayed image.

If the mtime changes:

```python
self._prefetch_cache.pop(self.fileidx, None)
self.load_image_async(self.fileidx)
```

is used.

Thus a modified file causes the currently displayed decoded representation to be replaced.

This also invalidates its prefetched version so that an old decode does not get reused.

---

# 54. Filtering Does Not Decode Images

The search/filter mechanism operates on:

```python
f.label
f.path
```

and creates:

```python
self._visible_indices
```

It does not need to decode images merely to determine whether they match.

For a query consisting of multiple words, every term must appear somewhere in either the label or path.

Thus:

```text
search
  ↓
filename/path string matching
  ↓
visible index list
```

happens independently of:

```text
image decoding
```

This is another reason the program can handle large collections relatively efficiently.

---

# 55. Sorting and Image State

Sorting is also primarily filesystem metadata based.

The available sort keys are:

```text
name
mtime
size
```

The source uses:

```python
os.path.getmtime()
```

for modification time and:

```python
os.path.getsize()
```

for size.

When sorting occurs, the program keeps the `files` and `tns_thumbs` arrays paired:

```python
paired = list(zip(self.files, self.tns_thumbs))
```

and sorts the pairs together.

This prevents an existing thumbnail from becoming attached to the wrong file after reordering.

The sort operation also invalidates:

```text
_prefetch_cache
_img_in_flight
_gallery_in_flight
_mtimes
_gallery_aspect_cache
```

because those pieces of state depend on the previous file ordering.

---

# 56. Removing an Image

When a file is removed from the application list, its corresponding thumbnail slot is removed too:

```python
del self.files[n]
del self.tns_thumbs[n]
```

The relevant indices are adjusted, and:

```python
self._files_gen += 1
```

is performed.

The prefetch and in-flight gallery state is cleared.

This is another reason the generation mechanism exists: image indices are not permanently tied to one filesystem path.

---

# 57. Memory Model

At different points, the same source image may exist in several forms.

For the main viewer:

```text
filesystem file
      ↓
decoded PIL frame(s)
      ↓
cropped PIL image
      ↓
processed PIL image
      ↓
PhotoImage
```

Only some of these coexist simultaneously.

The original decoded frames remain in:

```python
self.img_frames
```

while the temporary crop/resized image is created during `render_image()`.

For the gallery:

```text
filesystem file
      ↓
small PIL thumbnail
      ↓
PhotoImage
      ↓
tns_thumbs
```

For prefetching:

```text
filesystem file
      ↓
complete decoded frames
      ↓
_prefetch_cache
```

So the biggest memory consumer is generally the main viewer's decoded frames and the prefetched neighboring frames, rather than the tiny gallery thumbnails.

---

# 58. Why the Main Viewer Has a 4096-Pixel Limit

The main viewer intentionally trades native-resolution fidelity for bounded memory use.

A source image could theoretically be:

```text
20,000 × 15,000
```

which represents:

```text
300 million pixels
```

before considering channel count or multiple frames.

At four bytes per RGBA pixel, that is approximately:

```text
300,000,000 × 4
≈ 1.2 GB
```

for a single uncompressed frame.

The source instead limits the decoded dimension to approximately 4096 pixels by default.

This is a major memory-control mechanism.

It also means the viewer's maximum practical image detail is determined partly by:

```python
max_load_dim
```

rather than simply by the original file resolution.

---

# 59. Gallery Memory Behavior

The gallery has a very different strategy.

It does not maintain full decoded versions of every image.

Instead:

```text
all files
    ↓
only visible/overscanned files
    ↓
small thumbnails
    ↓
PhotoImage objects
```

This is controlled by:

```python
GALLERY_OVERSCAN_ROWS = 2
```

and:

```python
THUMB_MAX_IN_FLIGHT = 12
```

So both the number of simultaneously decoded images and the number of images needing actual display are constrained.

---

# 60. Complete Main Viewer Pipeline

Putting everything together, the normal image-viewer path is:

```text
                 FILE SYSTEM
                      │
                      ▼
             path / directory
                      │
                      ▼
             extension filtering
                      │
                      ▼
                 FileEntry
                      │
                      ▼
              visible index list
                      │
                      ▼
                load_image_async
                      │
                      ▼
               _request_decode
                      │
                      ▼
             ThreadPoolExecutor
                 4 workers
                      │
                      ▼
                 load_frames
                      │
             ┌────────┴────────┐
             │                 │
        pyvips works      pyvips fails
             │                 │
             ▼                 ▼
     _vips_load_frames   _pil_load_frames
             │                 │
             └────────┬────────┘
                      ▼
              PIL frame list
                      │
                      ▼
              _install_image
                      │
                      ▼
               img_frames
                      │
                      ▼
                render_image
                      │
                      ▼
             calculate zoom/pan
                      │
                      ▼
            determine visible crop
                      │
                      ▼
                  crop()
                      │
                      ▼
              _prepare_crop()
                      │
            ┌─────────┼─────────┐
            │         │         │
       brightness  contrast   gamma
            │         │         │
            └─────────┴─────────┘
                      │
                      ▼
                  resize()
                      │
                      ▼
              ImageTk.PhotoImage
                      │
                      ▼
                 Tk Canvas
```

---

# 61. Complete Gallery Pipeline

The gallery path is:

```text
                 FILE SYSTEM
                      │
                      ▼
                 FileEntry list
                      │
                      ▼
          determine gallery geometry
                      │
                      ▼
        determine visible/overscan rows
                      │
                      ▼
             _submit_gallery_tile
                      │
                      ▼
             thumbnail executor
                 4 workers
                      │
                      ▼
          load_gallery_thumb()
                      │
             ┌────────┴────────┐
             │                 │
          pyvips              Pillow
             │                 │
             └────────┬────────┘
                      ▼
                small PIL image
                      │
                      ▼
             ImageTk.PhotoImage
                      │
                      ▼
                 tns_thumbs
                      │
                      ▼
              render_gallery()
                      │
                      ▼
                 Tk Canvas
```

Only visible and nearby tiles are normally submitted.

---

# 62. Complete List Preview Pipeline

The list view follows:

```text
FileEntry
    │
    ▼
selected index
    │
    ▼
render_list()
    │
    ▼
calculate preview dimensions
    │
    ▼
img executor
    │
    ▼
load_frames()
    │
    ▼
Pillow / pyvips
    │
    ▼
frames[0]
    │
    ▼
Pillow thumbnail()
    │
    ▼
ImageTk.PhotoImage
    │
    ▼
Tk Label
```

Only the first decoded frame is used for the preview.

---

# 63. What Is Actually Cached?

There are several different caches/state stores, and they should not be confused.

## `img_frames`

The currently displayed image's decoded frames.

```text
lifetime: current image
```

## `_prefetch_cache`

Decoded neighboring images.

```text
maximum: PREFETCH_MAX = 3
```

## `tns_thumbs`

Gallery thumbnail `PhotoImage` objects.

```text
one slot per file
```

but only requested thumbnails are populated.

## `_orig_sizes`

Known original dimensions used by gallery aspect-ratio calculation.

```text
path → (width, height)
```

## Disk thumbnail cache

`_decode_thumb()` provides a persistent WebP cache under:

```text
~/.cache/tkiv_thumbs
```

or `$XDG_CACHE_HOME/tkiv_thumbs`.

These are distinct mechanisms.

---

# 64. Threading Architecture

The program effectively has several kinds of background work:

```text
Tk main thread
│
├── GUI
├── canvas drawing
├── PhotoImage creation
├── state changes
└── main queue processing
│
├──────── image executor ────────┐
│                                │
│        up to 4 workers         │
│        full image decode       │
│                                │
├────── thumbnail executor ──────┤
│                                │
│        up to 4 workers         │
│        gallery thumbnails      │
│                                │
└────── auxiliary threads ───────┘
         │
         ├── lazy filesystem scan
         └── gallery aspect sampling
```

The worker threads do the expensive filesystem/image processing, while completed work is marshalled back to the Tk thread.

---

# 65. Failure Handling

There are multiple fallback layers.

For full images:

```text
pyvips
  ↓ failure
Pillow
```

For gallery thumbnails:

```text
pyvips
  ↓ failure
Pillow
```

For cached thumbnails:

```text
valid WebP
  ↓ failure/corruption
delete cache
  ↓
decode original
```

For asynchronous current-image failures:

```text
decode error
    ↓
if --assume-files:
    show empty image
else:
    attempt normal load/error handling
```

This is why an individual broken image does not necessarily cause the entire application to terminate.

---

# 66. A Subtle Difference Between "Decode" and "Render"

The program separates two concepts that are often combined in simple image viewers.

## Decode

Convert the source file into usable pixels:

```text
JPEG/PNG/WebP/etc.
       ↓
Pillow/pyvips
       ↓
PIL.Image
```

## Render

Take those already decoded pixels and prepare the portion needed by the screen:

```text
PIL.Image
   ↓
crop
   ↓
color processing
   ↓
resize
   ↓
PhotoImage
   ↓
Canvas
```

This distinction is especially important for zooming and panning.

Zooming does not cause the source file to be reopened. The program works with the decoded `img_frames`.

---

# 67. Another Important Distinction: Thumbnail Versus Zoom

Gallery thumbnails are created specifically for their display size:

```python
load_gallery_thumb(path, max_w, max_h)
```

The main viewer does not permanently create a thumbnail when zooming.

Instead:

```text
decoded frame
     ↓
visible crop
     ↓
zoom-dependent resize
```

Therefore gallery rendering and main-image rendering use fundamentally different strategies.

---

# 68. Why the Pipeline Is Structured This Way

The design addresses several competing requirements.

### Fast startup

Lazy scanning allows the GUI to appear before an enormous directory is completely scanned.

### Responsive navigation

Image decoding happens in worker threads.

### Sequential browsing

Adjacent images are prefetched.

### Large collections

Gallery rendering only requests visible and overscanned thumbnails.

### Large source images

The main decoder limits the maximum decoded dimension.

### Multiple formats

pyvips and Pillow provide broad decoder coverage.

### Animated images

The main image loader can retain multiple frames and their delays.

### Efficient zooming

Only the visible source crop is resized.

### Safe asynchronous behavior

Load tokens and generation counters prevent stale worker results from replacing current UI state.

### Persistent thumbnail optimization

A WebP disk cache exists through `_decode_thumb()`.

---

# 69. The Most Important Data Structures

For understanding the image system, these attributes are particularly important:

| Attribute                 | Purpose                                    |
| ------------------------- | ------------------------------------------ |
| `self.files`              | All `FileEntry` objects                    |
| `self._visible_indices`   | Current filtered subset                    |
| `self.fileidx`            | Currently selected file index              |
| `self.img_frames`         | Decoded frames for main image              |
| `self.img_delays`         | Animation delays                           |
| `self.img_sel`            | Current animation frame                    |
| `self.tns_thumbs`         | Gallery thumbnail objects                  |
| `self._prefetch_cache`    | Prefetched full image frames               |
| `self._img_in_flight`     | Currently decoding image futures           |
| `self._gallery_in_flight` | Gallery thumbnails currently being decoded |
| `self._orig_sizes`        | Cached source dimensions                   |
| `self._files_gen`         | File/gallery state generation              |
| `self._load_token`        | Current-image request generation           |
| `self._main_queue`        | Worker → Tk communication queue            |
| `self._img_executor`      | Full-image worker pool                     |
| `self._thumb_executor`    | Gallery-thumbnail worker pool              |

The initialization of these structures is concentrated in `TkivApp.__init__()`.

---

# 70. End-to-End Example

Suppose the user runs:

```bash
tkiv img ~/Pictures
```

with a directory containing:

```text
~/Pictures/
├── a.jpg
├── b.png
├── c.webp
└── sub/
    └── d.jpg
```

without `--recursive`, discovery produces approximately:

```text
a.jpg
b.png
c.webp
```

If `--recursive` is supplied:

```text
a.jpg
b.png
c.webp
sub/d.jpg
```

Each becomes a `FileEntry`.

When the viewer starts:

```text
FileEntry list
     ↓
Tk window
     ↓
load_image_async(current)
     ↓
image worker
     ↓
load_frames()
```

If pyvips works:

```text
file
 ↓
libvips
 ↓
max dimension reduction if needed
 ↓
PIL.Image
```

Then:

```text
PIL frames
 ↓
img_frames
 ↓
render_image()
 ↓
fit/zoom
 ↓
visible crop
 ↓
brightness/contrast/gamma
 ↓
BICUBIC/NEAREST resize
 ↓
PhotoImage
 ↓
Canvas
```

After the image is displayed:

```text
current index
   ├── next → prefetch
   └── previous → prefetch
```

If the user switches to gallery mode:

```text
gallery geometry
      ↓
visible rows
      ↓
thumbnail jobs
      ↓
load_gallery_thumb()
      ↓
small PIL images
      ↓
PhotoImage
      ↓
gallery canvas
```

If the user switches to list mode:

```text
selected FileEntry
      ↓
load_frames()
      ↓
first frame
      ↓
thumbnail()
      ↓
PhotoImage
      ↓
preview Label
```

---

# 71. Summary

The image subsystem in `tkiv` is not a single decoder. It is a layered pipeline with separate paths for full images, thumbnails, previews, and metadata.

The central design can be summarized as:

```text
                     IMAGE PATH
                         │
                         ▼
                  file discovery
                         │
                         ▼
                     FileEntry
                         │
                         ▼
                  visible selection
                         │
             ┌───────────┼───────────┐
             │           │           │
             ▼           ▼           ▼
          Image       Gallery       List
          viewer      thumbnails    preview
             │           │           │
             ▼           ▼           ▼
        load_frames  load_gallery  load_frames
             │           │           │
             ▼           ▼           ▼
         pyvips/      pyvips/      pyvips/
         Pillow       Pillow       Pillow
             │           │           │
             ▼           ▼           ▼
       decoded frames  small PIL   first frame
             │           │           │
             ▼           ▼           ▼
       crop/process   PhotoImage   thumbnail
             │           │           │
             ▼           ▼           ▼
          resize       Canvas       PhotoImage
             │
             ▼
         PhotoImage
             │
             ▼
           Canvas
```

The most important performance mechanisms are:

1. **Extension-based file discovery** avoids decoding during directory scanning.
2. **Lazy scanning** prevents large directory traversal from blocking startup.
3. **pyvips-first decoding** provides a fast image-processing path when installed.
4. **Pillow fallback** keeps the program functional without pyvips.
5. **Maximum decoded dimension** limits memory usage for huge source images.
6. **Separate worker pools** keep expensive image operations away from Tk's GUI thread.
7. **Load tokens** prevent stale asynchronous image results.
8. **Neighbor prefetching** reduces latency during sequential browsing.
9. **Viewport-aware gallery loading** prevents thousands of thumbnails from being decoded at once.
10. **Gallery generation counters** prevent obsolete thumbnail results from entering a changed gallery.
11. **Original-dimension inspection** allows aspect-ratio decisions without fully decoding images.
12. **Visible-region cropping** makes high-zoom rendering cheaper.
13. **Color adjustments happen after cropping**, so brightness/contrast/gamma are not unnecessarily applied to invisible pixels.
14. **`ImageTk.PhotoImage`** is the final bridge from Pillow's image representation into Tkinter.
15. **A persistent WebP thumbnail cache exists in `_decode_thumb()`**, although the current gallery submission path directly uses `load_gallery_thumb()` rather than `_decode_thumb()`.

In short, the program separates **retrieval**, **decoding**, **preparation**, **caching**, and **display** rather than performing all of them in one operation. That separation is what allows the same application to function both as a conventional image viewer and as a responsive large-image-collection browser.
