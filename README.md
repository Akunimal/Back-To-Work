# Back To Work

**A tiny CLI that rings a sound the moment your Claude Code (or Codex) usage comes back.**

You hit the 5-hour usage limit, you walk away. Leave `backtowork` running in a
terminal — it shows a big green Commodore-style countdown, and when your credit
refills it **plays a sound** and pops a **desktop toast** so you know it's time
to get back to work.

```
   ╭──────────────────────────────────╮
   │  back to work  ·  ⏳ watching...  │
   ╰──────────────────────────────────╯

            ███ ███     ███ ███     ███ ███
              █ █          █ █ █     █ █ █ █
            ███ ███  █   ███ ███  █  ███ ███
            █     █     █ █ █ █      █ █ █ █
            ███ ███     ███ ███     ███ ███
                  2:14:09  until back to work
```

- **Windows-first.** Sound via the stdlib `winsound`, native toast via
  `winotify`. No PowerShell, no admin rights. Works on macOS/Linux too.
- **Zero-cost detection.** Reads each tool's *own local logs* — never calls a
  model API, so it never spends a token of your usage. Claude Code: exact when
  the CLI wrote a real usage-limit marker. **Codex: exact**, read straight from
  the rate-limit snapshot the Codex CLI caches under `~/.codex`.
- **Exact mode.** Know the time already? `backtowork watch --reset 3h`.
- **Agnostic.** A `command` provider lets you watch *any* tool via a tiny probe.

## Install

Needs Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "backtowork[toast]"      # [toast] adds the Windows popup
```

or with pip:

```bash
pip install "backtowork[toast]"
```

From source:

```bash
git clone https://github.com/Akunimal/Back-To-Work
cd Back-To-Work
uv tool install ".[toast]"
```

## Quick start

```bash
# Exact countdown — no config needed:
backtowork watch --reset 3h        # or 90m, 2h30m, or an ISO time

# Auto mode — read your tool's local logs (Claude Code / Codex):
backtowork watch                   # uses a backtowork.toml (see below)

# Hear the sound + see the banner right now:
backtowork test
```

Press `Ctrl-C` to quit.

## How auto-detection works (and its limits)

### Claude Code (exact when limited)

Claude Code writes a transcript for every session under
`~/.claude/projects/**/*.jsonl`. When the CLI actually hits the usage limit it
records a `Claude Code usage limit reached|<unix_epoch>` marker. `backtowork`
reads that marker locally and counts down to the exact reset time.

Having recent activity does **not** mean you are out of credit. If no limit
marker is present, the provider reports available. It **never contacts the
Anthropic API**, by design — detection must not cost usage.

### Codex (exact, not an estimate)

The OpenAI Codex CLI caches the server's rate-limit snapshot into its session
logs under `~/.codex/sessions` (set `$CODEX_HOME` to relocate). The `codex`
provider reads the latest snapshot — the `primary` (~5h) or `secondary` (weekly)
window's `used_percent` and reset time (`resets_at` in current builds,
`resets_in_seconds` in older builds) — and counts down to the real reset. No
model API call.

```toml
[[provider]]
kind = "codex"
name = "codex"
# window = "primary"   # or "secondary" for the weekly cap
```

Some Codex versions log `rate_limits` as `null` until the server first sends
one; until then the provider reports `unknown` — fall back to `--reset` or a
`command` provider.

## Configure

Copy [`config.example.toml`](config.example.toml) to `backtowork.toml` (in the
folder you run from), or to `%APPDATA%\backtowork\config.toml` (Windows) /
`~/.config/backtowork/config.toml`.

```toml
[settings]
play_sound = true
show_toast = true
# sound    = "C:/path/to/your.wav"   # override the bundled chime

[[provider]]
kind = "claude_code"     # zero-cost local 5h-block estimate
name = "claude"
```

Provider kinds:

| kind          | what it does                                                   |
|---------------|---------------------------------------------------------------|
| `claude_code` | exact Claude Code usage-limit marker from local logs (no API) |
| `codex`       | exact usage from OpenAI Codex CLI logs (`~/.codex`, no API)    |
| `manual`      | exact countdown to a `reset_at` you supply                     |
| `command`     | run any script; `exit 0` = credit, `exit 75` = exhausted       |

The `command` provider may also print `reset_at=<ISO8601>` on stdout so the
watcher can sleep smartly until just before the reset.

## Commands

| command              | what it does                                  |
|----------------------|-----------------------------------------------|
| `backtowork watch`   | live monitor with the big green countdown     |
| `backtowork status`  | poll every provider once and print            |
| `backtowork test`    | fire a fake refill (banner + sound + toast)   |

Flags: `--reset <when>`, `--sound <path.wav>`, `--no-sound`, `--no-toast`,
`--config <path>`.

## Development

```bash
uv run pytest                         # tests
uv run python scripts/gen_sound.py    # regenerate the bundled chime
uv run backtowork test                # try it
```

## License

MIT © Akunimal
