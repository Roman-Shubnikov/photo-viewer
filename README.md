# Photo Viewer

Desktop gallery for photos copied from an iPhone. Live Photos (`HEIC` + `MOV` pairs) are marked with a
LIVE badge and play on click; regular photos, screenshots and videos open as usual. The app can also
import everything from a USB-connected iPhone.

## Run

```bash
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\photo-viewer
```

## Usage

- **Open folder** — scans a folder recursively and builds the gallery.
- **Import from iPhone** — copies all files (including Live Photo videos and edit sidecars) into a folder,
  keeping the iPhone's month folders and original timestamps. Already copied files are skipped, so an
  interrupted import can be resumed. Keep the iPhone unlocked during the import.
- Viewer: click / `Space` / LIVE button plays the Live Photo, `←` `→` navigate, `Esc` closes.

## Tests

```bash
.venv\Scripts\pytest
```
