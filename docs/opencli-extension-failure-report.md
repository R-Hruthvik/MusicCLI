# OpenCLI Extension Failure Report

**Date:** 2026-08-07  
**Project:** MusicCLI  
**Environment:** `/usr/local/nodejs/bin/opencli` v1.8.6, Node v24.14.0

---

## Executive Summary

**The OpenCLI extension shows as connected in `opencli doctor`, but browser-based image-upload commands are failing in practice.**  
Diagnostics are mixed: some cookie-mode adapters report login/connectivity OK, while direct browser automation for image upload to ChatGPT returns `Not allowed` / max-attempts-exhausted errors.

---

## Diagnostic Evidence

### 1. `opencli doctor` Output

```
[OK] Daemon: running on port 19825 (v1.8.6)
[OK] Extension: connected (v1.0.22)

Profiles:
  • 2c4x62kr: connected v1.0.22
[OK] Connectivity: connected in 0.1s

Everything looks good!
```

**Note:** doctor reported connectivity OK earlier, but later `-v` runs showed:
```
[FAIL] Connectivity: failed (Browser exec command timed out after 8s)
```

### 2. Working / Partial Health Checks

| Adapter | Command | Result |
|---------|---------|--------|
| `chatgpt status` | `opencli chatgpt status` | `Connected`, `Login: Yes` |
| `gemini status` | `opencli gemini status` | `Connected`, `Login: Yes` |
| `youtube search` | `opencli youtube search ...` | Results returned |
| `duckduckgo search` | `opencli duckduckgo search musiccli` | Results returned |

### 3. Failing Browser Automation / Image-Upload Paths

| Attempt | Command | Error |
|---------|---------|-------|
| `browser cli upload "#upload-photos" ...` | Upload to ChatGPT photo input | `{"code":-32000,"message":"Not allowed"}` |
| `browser cli upload --testid "upload-photos-input" ...` | Same input by testid | `{"code":-32000,"message":"Not allowed"}` |
| `opencli chatgpt image ... --image <screenshot>` | ChatGPT image-attach prompt | `Failed to upload image to ChatGPT: sendCommand: max attempts exhausted` |

These failures indicate the extension is either blocked from file-input mutation on chatgpt.com, or the adapter’s upload automation path is incompatible with the current page markup/permissions.

---

## Root Cause Assessment

1. **Partial failure, not total outage** — daemon + extension handshake reports healthy, and some adapters work.
2. **Image upload specifically fails** — likely one of:
   - Chrome extension lacks the host permission / CDP file-attach capability for chatgpt.com’s current upload flow.
   - Page uses a nonstandard upload path the adapter does not handle.
   - The `chatgpt image` adapter attempts a send loop and gives up after retries.
3. **`opencli doctor` is not a full smoke test** — it validates daemon/extension presence and a basic connectivity probe, but does not validate adapter command success or file-upload automation.

---

## Reproducible Steps

```bash
# 1. Health check shows OK
opencli doctor

# 2. Open ChatGPT in browser session
opencli browser cli open https://chatgpt.com/

# 3. Find file input
opencli browser cli find --css "input[type=file]"
# => shows #upload-photos, #upload-camera

# 4. Attempt upload
opencli browser cli upload "#upload-photos" /path/to/screenshot.png
# => {"code":-32000,"message":"Not allowed"}

# 5. Adapter-level attempt also fails
opencli chatgpt image "describe these screenshots" --image /path/to/screenshot.png
# => max attempts exhausted
```

---

## Workarounds Available Now

### A. Use the web UI manually
- Open https://chatgpt.com/ and https://gemini.google.com/app in a browser.
- Use the built-in attachment controls to upload your screenshots.
- Ask the AI to describe the images and suggest MusicCLI improvements.

### B. Use text-only analysis via AI
- Send a written description of the screenshots to `opencli gemini ask` or `opencli chatgpt ask`.
- You can still get UI improvement recommendations without image upload.

### C. Use Gemini Deep Research / text flow
- `opencli gemini deep-research "MusicCLI terminal UI UX improvements"`
- `opencli gemini ask "terminal music player UI best practices"`

---

## Recommended Actions

1. **Upgrade OpenCLI** — check whether a newer release fixes adapter upload behavior.
2. **Reinstall/refresh the Chrome extension** — reinstall from the Chrome Web Store and confirm version.
3. **Run browser verification** once upload flow is fixed:
   - `opencli browser verify chatgpt/image`
   - `opencli validate chatgpt`
4. **File upstream issue** with:
   - opencli version
   - Chrome extension version
   - exact failing command + error envelope
   - page URL + observed selectors

---

## Conclusion

The OpenCLI extension is **connected but functionally failing for image upload automation on ChatGPT**. Other adapters remain usable. Until the upload path is repaired, use manual web-UI upload or text-only AI prompts.
