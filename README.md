<<<<<<< HEAD
# The-Library
A library website template for public use.
=======
# My Library

A personal book-writing app that runs entirely in the browser. Write and organize your books by chapter, with Markdown support and custom cover art. No accounts, no cloud, no tracking — just you and your writing, running locally on your own machine.

## Features

- **Book library** — displays your books as a cover grid with title and chapter count
- **Chapter editor** — write each chapter separately with a full-screen editor
- **Informational chapters** — mark a chapter as "information" (e.g. world-building, character notes) via a checkbox in the editor; these are tracked and displayed separately from your regular chapter count
- **Markdown support** — headings, bold, italic, blockquotes, code blocks, lists, links, and more
- **Live preview** — toggle between raw Markdown and rendered output while writing
- **Cover art** — upload a custom image as the cover for each book
- **Local storage** — everything is saved in your browser automatically, no backend needed
- **Keyboard shortcut** — Ctrl/Cmd+S saves your chapter from anywhere in the editor

## File Structure

```
index.html   — the app structure and markup
style.css    — all styling
app.js       — all logic, Markdown parsing, and localStorage handling
```

## Running Locally

Just open `index.html` in your browser. No build step, no dependencies, no internet connection required.

## Running Over a Local Network

To access the app from other devices on your home network, use Python's built-in HTTP server:

```bash
cd /path/to/this/folder
python3 -m http.server 8080 --bind 0.0.0.0
```

Then open `http://your-local-ip:8080` on any device on the same network. Find your local IP with `ip a` (Linux/Mac) or `ipconfig` (Windows).

### Auto-start on Linux with systemd

Create a service file at `/etc/systemd/system/mylibrary.service`:

```ini
[Unit]
Description=My Library Web Server
After=network.target

[Service]
WorkingDirectory=/path/to/this/folder
ExecStart=/usr/bin/python3 -m http.server 8080 --bind 0.0.0.0
User=your-username

[Install]
WantedBy=default.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mylibrary.service
```

The server will now start automatically every time you boot your machine.

## Data & Privacy

All data is stored in your browser's `localStorage`. Nothing is ever sent to a server. Because of this, your library is tied to the specific browser and device you use — it won't sync across devices.

## Notes

- Covers are stored as base64 data URLs inside localStorage, so large images may take up significant storage space over time
- If your localStorage gets cleared (e.g. through browser settings), your books will be lost — consider periodically backing up your data by exporting localStorage manually if needed
- This app has no built-in authentication; it's intended for local/personal use only
>>>>>>> f17c54a (Initial commit.)
