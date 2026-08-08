# MusicCLI Extended (Never-Ending Radio, Clean Metadata, & Playback Controls) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance `musiccli.py` to support clean single-line metadata display, playlist/source info, history (Prev/Next), Stop/Restart, Queue inspection, and Never-Ending Radio mode.

**Architecture:** Extend the existing single-file Python script (`musiccli.py`) with enhanced state management (history stack, active queue, radio mode flag) and interactive keyboard / command loop enhancements.

**Tech Stack:** Python 3, `yt-dlp`, `ffplay`, threading, subprocess.

## Global Constraints
- Pure Python + existing tools (`yt-dlp`, `ffplay`), no new pip packages.
- Clean UTF-8 encoding support on Windows.
- Clean tabular / single-line metadata output (no cluttered multi-line boxes).

---

## File Structure

- Modify: `C:\Users\hruth\Desktop\MusicCLI\musiccli.py`

---

### Task 1: Clean Metadata Extraction & Display

**Files:**
- Modify: `C:\Users\hruth\Desktop\MusicCLI\musiccli.py`

**Interfaces:**
- Consumes: yt-dlp `--print` output with title, id, uploader, channel.
- Produces: `search_youtube` returning richer dict structure `{'title': ..., 'uploader': ..., 'url': ..., 'id': ...}`.

- [ ] **Step 1: Update `search_youtube` to parse uploader/artist**
- [ ] **Step 2: Update `display_results` to print clean song name, artist, and playlist/source name**
- [ ] **Step 3: Test search and metadata display format**

---

### Task 2: Playback History, Queue & Never-Ending Radio Mode

**Files:**
- Modify: `C:\Users\hruth\Desktop\MusicCLI\musiccli.py`

**Interfaces:**
- Consumes: Track results and active queue list.
- Produces: History stack (`history`), active queue (`queue`), and radio mode toggle (`radio_mode`).

- [ ] **Step 1: Implement queue and history lists in `main()` state**
- [ ] **Step 2: Implement `[R]` toggle for Never-Ending Radio Mode**
- [ ] **Step 3: Implement auto-fetching similar tracks via `yt-dlp ytsearch20:similar to {title}` when queue empties or radio mode is active**

---

### Task 3: Robust Playback Controls (Stop, Restart, Next, Prev, Queue)

**Files:**
- Modify: `C:\Users\hruth\Desktop\MusicCLI\musiccli.py`

**Interfaces:**
- Consumes: Subprocess handle, stop event, history, queue.
- Produces: Interactive control loop supporting `X` (Stop), `Z` (Restart), `S` / `N` (Next), `P` (Prev), `Q` (Queue inspect).

- [ ] **Step 1: Add Stop (`X`) and Restart (`Z`) controls during playback**
- [ ] **Step 2: Add Previous (`P`) track playback using history stack**
- [ ] **Step 3: Add Queue inspection (`Q` command to view upcoming tracks)**
- [ ] **Step 4: Verify full interactive flow**

---
