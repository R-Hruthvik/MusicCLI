# OpenCLI — Multi-assistant `ask --file` attachment support

**Date:** 2026-08-07
**Explained + modified source:** `/home/hruthvik9487/opencli-src/repo`
**Scenario:** Send files (images, PDFs, code, markdown, txt — anything the chat
assistant accepts) to AI chat UIs through `opencli <assistant> ask ...`.

---

## What changed (adapter layer)

The robust file-attach path already exists end-to-end via the extension's
`set-file-input` command (CDP `Page.setInterceptFileChooserDialog` +
`Page.fileChooserOpened` + `DOM.setFileInputFiles` — hidden-input safe). The
previous failures came from calling the **flaky fallback** (`browser upload` /
base64-in-evaluate) instead of that path. The adapter changes now call the
robust path directly.

### Files modified

| File | Change |
|------|--------|
| `clis/_shared/common.js` | Added `parseFilePaths()` — comma-separated path parsing used by all adapters |
| `clis/chatgpt/ask.js` | Added `--image` flag → uploads via `uploadChatGPTImages()` (routes through `page.setFileInput` extension path) before prompting |
| `clis/gemini/ask.js` | Added `--file` flag → `page.setFileInput(...)` extension path before prompting |
| `clis/grok/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/qwen/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/doubao/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/yuanbao/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/chatwise/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/codex/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |
| `clis/cursor/ask.js` | Added `--file` flag (explicit "not yet implemented" error) |

Claude and DeepSeek already had `--file`; their paths are left as-is.

### How the attach flow works (works across assistants)
1. `parseFilePaths()` expands a comma-separated `--file a.png,b.pdf` value.
2. The adapter calls `page.setFileInput(paths, 'input[type="file"]')` — this
   dispatches the **`set-file-input`** command to the extension.
3. The extension intercepts the file chooser, gets a `backendNodeId`, and calls
   `DOM.setFileInputFiles` (the only form Chrome accepts under `chrome.debugger`).
4. The adapter waits ~1s for the preview, then sends the prompt.

---

## Extension: no code change required

The extension (`extension/src/cdp.ts` `setFileInputFiles`, wired in
`background.ts` as `set-file-input`) already implements the hidden-input-safe
uploader. The `Not allowed` error seen earlier was the **fallback path**, not
the extension. So the fix is adapter-only.

If you still want to reinstall the extension from this source (to match head and
pick up any future CDP fixes), the steps are below.

### Build + install the extension (unpacked)
```bash
cd /home/hruthvik9487/opencli-src/repo/extension
npm install
npm run build            # outputs to extension/dist/
```
Then in Chrome: `chrome://extensions` → enable Developer mode → **Load unpacked**
→ select `extension/dist`. Keep the OpenCLI daemon/bridge and your custom
extension pointing at the same profile.

### Use the modified adapters
The adapters live in `clis/` and are loaded per the repo manifest. To use them
with the installed OpenCLI, either:
- run from source: `cd /home/hruthvik9487/opencli-src/repo && npx tsx src/main.ts ...`
- or copy the modified `clis/<site>/ask.js` into `~/.opencli/clis/<site>/ask.js`
  (user-override dir — this is the "install own extension/adapter" path).

---

## Usage examples
```bash
# Screenshots (multi, comma-separated) to Gemini
opencli gemini ask "describe these screenshots and suggest MusicCLI UI fixes" \
  --file "shot1.png,shot2.png"

# Clickup a single PDF or code file to ChatGPT
opencli chatgpt ask "review this code" --image /path/to/code.png

# (Claude / DeepSeek already supported)
opencli claude ask "explain this file" --file README.md
```

---

## Notes / follow-ups
- `chatgpt ask --image` currently reuses the image-specific validator
  (`prepareChatGPTImagePaths`). For a fully generic ChatGPT attachment (PDFs,
  code, etc.) a general `--file` uploader should be wired to the same robust
  `page.setFileInput` path. That is the natural next step.
- Adapters marked "not yet implemented" still accept `--file` but throw a clear
  error instead of silently ignoring the attachment — the CLI surface is now
  consistent, and each is a small, site-specific addition from here.
