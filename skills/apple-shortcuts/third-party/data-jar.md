# Data Jar

_Last verified: 2026-04-19_

Persistent key-value store for Shortcuts. Syncs via iCloud.

- **App Store**: `https://apps.apple.com/app/data-jar/id1453273600`
- **Developer**: Simon Støvring (Simon Bæk Støvring).
- **Bundle ID**: `dk.simonbs.datajar` ⚠ confirmed via iCloud folder
  name `iCloud~dk~simonbs~datajar`.
- **iCloud folder**: `iCloud~dk~simonbs~datajar`.
- **Price**: Free with IAP for advanced features (~€4).
- **Platforms**: iOS, macOS (Catalyst).

## What it solves

Native Shortcuts has no persistent storage. Named variables only
live for the duration of one run. Data Jar provides:

- Persistent dictionary, keyed by dotted paths.
- Cross-shortcut access.
- iCloud sync across devices.
- Arrays, numbers, booleans, text, images, files as values.

## Actions

⚠ Identifier suffixes not publicly documented. Typical shapes below;
discover via `tools/list-app-intents.py --bundle dk.simonbs.datajar`.

| Action              | Purpose                                         |
| ------------------- | ----------------------------------------------- |
| Get Value           | Read at key path                                |
| Set Value           | Write at key path                               |
| Delete Value        | Remove at key path                              |
| Has Value           | Predicate                                       |
| Increase Number     | Atomic increment                                |
| Decrease Number     | Atomic decrement                                |
| Toggle Boolean      | Boolean flip                                    |
| Format Value        | Stringify with formatter                        |
| Get All Keys        | Enumerate                                       |
| Get All Values      | Enumerate                                       |
| Clear All           | Drop everything (use with care)                 |

## Usage

### Increment a counter

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>dk.simonbs.datajar.IncreaseNumberIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>key</key>
    <string>stats.runs</string>
    <key>amount</key>
    <integer>1</integer>
  </dict>
</dict>
```

⚠ Literal identifier unverified; confirm via discovery.

### Rate limiting

```text
1. Data Jar: Get Value "ratelimit.last_call"
2. Date: Current Date
3. Calculate: difference in seconds
4. If less than 60: Exit Shortcut
5. Data Jar: Set Value "ratelimit.last_call" to Current Date
```

### Cross-shortcut cache

```text
1. Data Jar: Has Value "api.cache.user_123"
2. If true: Data Jar: Get Value → return
3. Otherwise: call API, Data Jar: Set Value, return
```

## Gotchas

- iCloud sync is eventual, not immediate. Two devices writing to the
  same key can produce last-writer-wins conflicts.
- Values are typed. Writing a string to a key previously holding a
  number doesn't auto-convert; the next `Get Value` returns the new
  type.
- Clear All is destructive and not undoable. Guard behind a
  confirmation dialog.

## When to prefer over native

Native `Set Variable` lives one run. Data Jar is the go-to for:

- Daily counters.
- Feature flags shared across shortcuts.
- OAuth tokens / session state (but see `gotchas/` re secrets).
- Small lookup tables.

For larger or relational data, prefer a real API or use Scriptable
with a SQLite wrapper.
