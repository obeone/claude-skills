# a-Shell

_Last verified: 2026-04-19_

Unix-like shell for iOS. Exposes commands to Shortcuts.

- **App Store**:
  `https://apps.apple.com/app/a-shell/id1473805438` (free, full)
  / `a-shell-mini/id1501592214` (free, small).
- **Developer**: Nicolas Holzschuch.
- **Bundle ID**: `AsheKube.app.a-Shell` (full) /
  `AsheKube.app.a-Shell-mini` (mini).
- **Source**: `https://github.com/holzschu/a-shell`.
- **Price**: Free, open source (BSD).
- **Platforms**: iOS, iPadOS.

## What it provides

- BSD userland (`ls`, `grep`, `sed`, `awk`, `find`).
- Python 3 (full version).
- Lua 5.4.
- `vim`, `nano`.
- Text-mode web (`curl`, `wget`).
- SSH client.

## Shortcuts bridge

Two actions:

### Execute command

Runs a command and returns stdout to Shortcuts.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>AsheKube.app.a-Shell.ExecuteCommandIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>command</key>
    <string>echo $((2 + 2))</string>
  </dict>
</dict>
```

⚠ Literal identifier unverified; rediscover via
`tools/list-app-intents.py --bundle AsheKube.app.a-Shell`.

### Execute command and open

Same, but opens a-Shell's UI afterwards to show output and allow
follow-up commands.

## Use cases

- **Quick calculations** beyond native Calculate — use `bc`, `python
  -c`.
- **Text processing** — `awk`, `sed`, `jq` (if installed).
- **File juggling** beyond native file actions — `find`,
  `rsync` (within sandbox).
- **Network probing** — `curl`, `dig`, `host`.
- **Python scripts** without Scriptable — write to a file, invoke
  via `python script.py`.

## Gotchas

- Sandbox-limited. Cannot touch other apps' data.
- Shell commands run in a-Shell's bundle context — environment,
  PATH, and installed tools differ from macOS.
- Output size is limited (iOS pasteboard limits).
- No real `cron` / persistent daemons.

## Example — JSON query via jq

```text
1. Get Contents of URL → JSON response
2. Set Variable: resp
3. a-Shell: Execute command
   Command: echo '[resp]' | jq '.items[0].id'
4. Show Result
```

Variable interpolation into the `command` parameter requires
`WFTextTokenString` serialization. See
`references/variables-and-types.md`.
