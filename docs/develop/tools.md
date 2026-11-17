# Development tools

## Playwright CLI for GUI inspection

The local web UI is a FastAPI + htmx application. `playwright-cli` provides a token-efficient way
for coding agents to open the GUI, inspect the accessibility snapshot, click through workflows and
capture screenshots. The agent skill is committed at `.agents/skills/playwright-cli`, so a fresh
checkout only needs the CLI and a browser.

### Requirements

- Node.js 20 or newer
- npm
- Chromium (downloaded by Playwright, about 200 MB)

### Install the CLI

User-local, without sudo:

```bash
npm install -g --prefix "$HOME/.local" @playwright/cli@latest
export PATH="$HOME/.local/bin:$PATH"  # add this to your shell profile to persist it
```

System-wide, with sudo:

```bash
sudo npm install -g @playwright/cli@latest
```

Then install Chromium:

```bash
playwright-cli install-browser chromium
```

### Verify the setup

Start the GUI in one terminal:

```bash
uv run image-triage gui
```

In a second terminal:

```bash
playwright-cli --version
playwright-cli open http://127.0.0.1:8765/
playwright-cli snapshot
playwright-cli screenshot --filename /tmp/image-triage-gui.png
playwright-cli close
```

`playwright-cli` is headless by default. Use `--headed` for visual inspection and
`playwright-cli show` for the session dashboard. Transient snapshots and console logs are written
to `.playwright-cli/` and ignored by Git. The committed `.playwright/cli.config.json` pins Chromium.

### Refresh the skill

The skill is committed, so normal checkouts do not need this step. To refresh it after a CLI
upgrade:

```bash
playwright-cli install --skills=agents
```

### Fresh checkout

```bash
uv sync --all-groups
npm install -g --prefix "$HOME/.local" @playwright/cli@latest
playwright-cli install-browser chromium
```

Start the GUI with `uv run image-triage gui`, then use `playwright-cli` as shown above.