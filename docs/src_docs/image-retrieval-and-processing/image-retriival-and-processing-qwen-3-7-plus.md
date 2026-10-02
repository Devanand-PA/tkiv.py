# Deep Dive into Image Retrieval and Processing in `tkiv.py`

The `tkiv.py` script is a highly optimized, multi-threaded image viewer and selector. To maintain a responsive UI while handling potentially massive image files, it employs a sophisticated architecture that separates file I/O, decoding, processing, and rendering across multiple threads. 

Below is a comprehensive breakdown of how image retrieval, processing, and rendering are implemented under the hood.

---

## 1. Architectural Overview
The application relies on a **producer-consumer model** utilizing Python's `concurrent.futures.ThreadPoolExecutor`. 
* **`_img_executor`**: Dedicated to decoding full-resolution images for the main viewer.
* **`_thumb_executor`**: Dedicated to generating thumbnails for the gallery and list views.
* **`_main_queue`**: A thread-safe `queue.Queue` that background threads use to push completed tasks and decoded image data back to the Tkinter main thread.
* **`_poll_main_queue`**: A Tkinter `after()` loop running every 20ms (`QUEUE_POLL_MS`) that drains the queue and applies results to the UI safely.

---

## 2. The Decoding Engines (pyvips & Pillow)
`tkiv` uses a hybrid decoding approach, preferring the C-based `pyvips` library for its speed and low memory footprint, with `Pillow` (PIL) acting as a robust fallback.

### Full Image Loading (`load_frames`)
When an image is requested, `load_frames(path, max_dim)` is called.
1. **pyvips Path**: If available, it calls `_vips_load_frames`. 
   * It checks for multi-page images (like GIFs or animated WebPs) using the `n-pages` metadata.
   * If the image exceeds `max_dim` (default 4096px), it downscales it *during* the decode phase using `vimg.resize()`, saving massive amounts of RAM.
   * It extracts frame delays for animations.
2. **Pillow Fallback**: If `pyvips` fails or is missing, `_pil_load_frames` takes over.
   * It uses `Image.open()` and iterates through `n_frames` using `im.seek(i)`.
   * Frames are converted to `RGBA` to ensure consistent handling of transparency.

### Thumbnail Generation (`load_gallery_thumb` & `_decode_thumb`)
Thumbnails are handled differently to prioritize speed.
* **Gallery**: Uses `pyvips.Image.thumbnail()` or `PIL.Image.thumbnail()`.
* **List View / Advanced**: `_decode_thumb` employs aggressive optimizations for JPEGs, using `img.draft()` and `img.reduce()` to skip decoding irrelevant pixel data before applying the final `thumbnail()` resize.

---

## 3. Asynchronous Loading & Concurrency Model
Navigating through a directory of high-res images can easily block a GUI. `tkiv` solves this with an **Async Token System**.

1. **Requesting an Image**: When the user navigates, `load_image_async(n)` is called. It increments a global `_load_token` and submits the decode job to `_img_executor`.
2. **Cancellation via Tokens**: If the user scrolls rapidly, multiple decode jobs are queued. When a background thread finishes, it passes the `_load_token` it was assigned back to the main thread. 
3. **Stale Result Discarding**: In `_apply_async_result`, the main thread checks `if token != self._load_token: return`. If the token is outdated (meaning the user has already navigated away), the decoded image is instantly discarded, preventing UI lag and race conditions.

### Prefetching
To make navigation feel instant, `_prefetch_neighbors(n)` automatically submits decode jobs for the images immediately preceding and following the current one. These are stored in an `OrderedDict` (`_prefetch_cache`) acting as an LRU (Least Recently Used) memory cache, capped at `PREFETCH_MAX` (3) items.

---

## 4. Caching Strategies
### Memory Cache
* **`_prefetch_cache`**: Stores fully decoded frames for adjacent images.
* **`tns_thumbs`**: A pre-allocated list storing `ImageTk.PhotoImage` objects for the gallery view, preventing the need to re-decode thumbnails when scrolling back and forth.

### Disk Cache
To survive application restarts, thumbnails are cached to disk in `~/.cache/tkiv_thumbs`.
* **Cache Key**: A SHA1 hash generated from `f"{path}|{mtime_ns}|{size}|{w}x{h}"`. This ensures the cache is instantly invalidated if the file is edited or resized.
* **Format**: Thumbnails are saved as **WebP** (`CACHE_WEBP_QUALITY = 82`) to minimize disk space while retaining transparency and high quality.
* **Atomic Writes**: The cache uses a `.tmp` file and `os.replace()` to prevent corrupted cache entries if the app crashes mid-write.

---

## 5. Image Processing & Color Adjustments
`tkiv` supports real-time Gamma, Brightness, and Contrast adjustments. To prevent applying heavy math to entire 4K images, processing is done **only on the visible viewport**.

### The `_prepare_crop` Pipeline
1. **Alpha Flattening**: If the image has an alpha channel, it is pasted onto a background-colored RGB canvas to prevent transparency artifacts.
2. **Brightness & Contrast**: Handled via `PIL.ImageEnhance`.
3. **Gamma Correction**: Instead of using slow pixel-by-pixel loops, `tkiv` generates a **256-item Lookup Table (LUT)** based on the gamma exponent. It then applies this LUT instantly using `im.point(lut)`.

---

## 6. Rendering Pipelines

### Image Mode (Viewport Culling)
In `render_image()`, the app calculates the exact pixel coordinates of the screen viewport (`x0, y0, x1, y1`) based on the current zoom and pan offsets.
1. **Crop**: It crops the *original* high-res frame to the exact visible area.
2. **Process**: Color adjustments are applied *only* to this cropped region.
3. **Resize**: The cropped region is upscaled/downscaled to match the screen's zoom level using `BICUBIC` (or `NEAREST` if anti-aliasing is off).
4. **Draw**: The resulting `PhotoImage` is drawn to the Tkinter `Canvas`.
*This "Crop -> Process -> Resize" pipeline ensures that adjusting gamma on a 50MP image takes milliseconds instead of seconds.*

### Gallery Mode (Smart Tiling & Virtualization)
The gallery is designed to handle tens of thousands of images without freezing.
1. **Aspect Ratio Detection**: `_get_gallery_aspect` spawns a background thread to read the dimensions of the first 20 images (`GALLERY_ASPECT_SAMPLE`). It calculates the **median aspect ratio** to ensure tiles are uniformly sized without stretching images.
2. **Tile Metrics**: `_compute_tile_metrics` calculates the optimal tile width/height based on window size, target rows, and the quantum grid size (`GALLERY_SIZE_QUANTUM = 8`).
3. **Virtual Scrolling**: `render_gallery()` only draws tiles that are currently visible on the screen, plus an overscan buffer (`GALLERY_OVERSCAN_ROWS = 2`). 
4. **Lazy Thumbnailing**: If a visible tile hasn't been decoded yet, `_submit_gallery_tile` pushes it to the `_thumb_executor`.

### List Mode
The list view uses a standard Tkinter `Listbox` for text, but loads image previews asynchronously. When an item is selected, `render_list` submits a decode job constrained by the preview label's physical pixel dimensions (`max(pw, ph)`), ensuring minimal memory usage.

---

## 7. Lazy Directory Scanning
If the user passes a directory containing 100,000 images, parsing the filesystem synchronously would freeze the app before the UI even appears. 

`start_lazy_scan` solves this:
1. A background daemon thread (`tkiv-scan`) uses `pathlib.Path.glob()` to traverse directories.
2. It batches discovered image paths into chunks of 128 (`LAZY_BATCH_SIZE`).
3. It pushes these batches to the main thread via `_queue_lazy_files`.
4. The main thread commits the batch to the `self.files` list and triggers an idle redraw (`_schedule_lazy_redraw`).
This allows the UI to open instantly and populate images progressively as the disk I/O completes.
