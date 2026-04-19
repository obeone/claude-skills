# Scriptable

_Last verified: 2026-04-19_

JavaScript runtime for iOS with a Shortcuts bridge.

- **App Store**: `https://apps.apple.com/app/scriptable/id1405459188`
- **Developer**: Simon Støvring.
- **Bundle ID**: `dk.simonbs.Scriptable`.
- **Price**: Free.
- **Platforms**: iOS 14+, iPadOS 14+.

## Two integrations

Scriptable exposes two actions to Shortcuts:

### Run Script

Runs a named script file saved in Scriptable.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>dk.simonbs.Scriptable.RunScriptIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>scriptName</key>
    <string>FetchAndParse</string>
  </dict>
</dict>
```

⚠ Literal identifier suffix unverified; Scriptable intents are
registered via App Intents and should be rediscovered via:

```bash
./tools/list-app-intents.py --bundle dk.simonbs.Scriptable
```

### Run Inline Script

Runs ad-hoc JS from the shortcut itself. Useful for logic too
awkward to express in pure actions (complex regex, multi-step JSON
transforms, date math).

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>dk.simonbs.Scriptable.RunInlineScriptIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>scriptCode</key>
    <string>
      const input = args.plainTexts[0];
      const doubled = input.toUpperCase() + input.toLowerCase();
      Script.setShortcutOutput(doubled);
    </string>
  </dict>
</dict>
```

## Bridge API

Inside a Scriptable script invoked by Shortcuts:

- `args.plainTexts`, `args.urls`, `args.images`, `args.fileURLs`,
  `args.notifications` — input passed from Shortcuts.
- `Script.setShortcutOutput(value)` — return a value to Shortcuts.
- `Script.complete()` — must be called to terminate.

Full API: `https://docs.scriptable.app/`.

## When to use

- Complex JSON/CSV/XML transforms — native actions chain becomes
  unwieldy.
- HTTP requests with custom timeout, redirect handling, or cookies.
- SQL-like queries against structured data via a bundled SQLite
  wrapper.
- UI creation via `UITable` or WebView (but output back to Shortcuts
  is limited to scalar types).

## When NOT to use

- Simple text manipulation — native or Actions app is faster.
- Cross-device — Scriptable is iOS-only. Shortcut with Scriptable
  action fails on macOS/watchOS.

## Security note

Inline scripts have access to all Scriptable APIs including
filesystem (within Scriptable's sandbox), HTTP, and Keychain. Don't
accept untrusted JS into your inline action.

## Identifier discovery

Script-name enum for "Run Script" is dynamic — each user has their
own script library. The `scriptName` parameter is a free-form string
that matches the script file's name in Scriptable's Documents
folder.
