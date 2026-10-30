# MusicCLI

A command-line music player and discovery tool with endless playback, taste profiling, and MCP integration.

## Structure

- `foundation/` — core CLI, TUI, and musiccli entrypoint
- `mcp/` — MCP server integration
- `docs/` — architecture decisions and research
- `tests` — pytest suites (`test_musiccli.py`, `test_musicly_daemon.py`, `test_musicly_mcp.py`)

## Setup

```bash
pip install -r requirements.txt  # if present
python foundation/musiccli.py
```
