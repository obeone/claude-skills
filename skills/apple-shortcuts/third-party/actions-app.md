# Actions (Sindre Sorhus)

_Last verified: 2026-04-19_

The **Actions** app by Sindre Sorhus is the most useful third-party
action pack: free, open source (MIT), actively maintained, and
covers roughly 80% of the gaps in native Shortcuts.

- **App Store**: `https://apps.apple.com/app/actions/id1586435171`
- **Site**: `https://sindresorhus.com/actions`
- **Source**: `https://github.com/sindresorhus/Actions`
- **Bundle ID**: `com.sindresorhus.Actions` ⚠ action suffixes not
  publicly documented in a flat list; names below are from the
  author's official action list.
- **Price**: Free.
- **Platforms**: iOS 15+, macOS 12+, visionOS.

## Identifier format

Action identifiers follow the bundle ID + intent name convention.
Example (observed via round-trip on Actions v2.x):

```text
com.sindresorhus.Actions.GenerateUUIDIntent
com.sindresorhus.Actions.ParseJSONIntent
com.sindresorhus.Actions.FormatCurrencyIntent
```

⚠ The exact suffix (with or without `Intent`) varies and is not
publicly documented. To confirm for a given action, export a shortcut
containing it and inspect via `tools/inspect-shortcut.py`.

## Action catalog (selected)

Complete list at `https://sindresorhus.com/actions#included-actions`
(180+ actions). Grouped highlights:

### Text

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Trim Whitespace               | Strip leading/trailing whitespace        |
| Normalize Text                | Unicode NFC/NFD/NFKC/NFKD                |
| Transliterate Text            | ASCII transliteration                    |
| Remove Emojis                 | Strip emoji characters                   |
| Remove Non-Printable          | Strip invisible chars                    |
| Truncate Text                 | Cut to N chars with ellipsis             |
| Count Occurrences             | Substring count                          |
| Format Person Name            | Given/family with localized ordering     |
| Random Text                   | Lorem ipsum, names, etc.                 |
| Parse CSV                     | CSV → Dictionary                         |
| Generate CSV                  | Dictionary → CSV                         |

### Encoding / hashing

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Hex Encode                    | Text → hex                               |
| Hex Decode                    | hex → Text                               |
| HMAC                          | HMAC-SHA1/SHA256/SHA384/SHA512           |
| Generate UUID                 | UUIDv4                                   |
| Is Valid UUID                 | Predicate                                |
| Encrypt File                  | AES-256-GCM                              |
| Decrypt File                  | AES-256-GCM                              |

### JSON / data

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Parse JSON5                   | Relaxed JSON parser                      |
| Parse JSON                    | (For cases where native coercion fails)  |
| Pretty Print Dictionaries     | Indented JSON output                     |
| Transform Dictionary          | Key/value transforms                     |
| Sort Dictionary by Key        | Ordered output                           |
| Merge Dictionaries            | Shallow or deep merge                    |

### Numbers

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Clamp Number                  | Min/max bounds                           |
| Format Currency               | Locale-aware currency                    |
| Format Number                 | Locale-aware number                      |
| Random Floating-Point Number  | Random decimal                           |
| Get Random Boolean            | Bernoulli(0.5)                           |

### Images

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Get SF Symbol Image           | Apple SF Symbols → image                 |
| Scan QR Codes in Image        | Decode QR from image                     |
| Blur Image                    | Gaussian blur                            |
| Invert Image Colors           | Color inversion                          |
| Get Image Type                | Format detection                         |
| Remove Alpha Channel          | Flatten transparency                     |
| Get Average Color             | Dominant color                           |

### Variables / persistence

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Global Variable — Get         | Cross-shortcut persistent var            |
| Global Variable — Set         |                                          |
| Global Variable — Delete      |                                          |
| Named Clipboard — Get         | Named clipboards (iCloud-synced)         |
| Named Clipboard — Set         |                                          |
| Named Clipboard — Clear       |                                          |

### Device / system

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Is Dark Mode On               | Predicate                                |
| Is Online                     | Predicate                                |
| Authenticate                  | Face ID / Touch ID / passcode gate       |
| Wait Milliseconds             | Sub-second delay                         |
| Haptic Feedback               | iOS haptic                               |
| Get Device Orientation        | Portrait/landscape/etc.                  |
| Speak Text (Offline)          | Speech synthesis                         |

### Network

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Download File                 | Non-blocking download with filename      |
| Resolve DNS                   | Hostname → IPs                           |
| Ping                          | ICMP (macOS)                             |

### Date / time

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Format Date Difference        | Relative string ("3 days ago")           |
| Get Calendar Info             | Month/week/day boundaries                |
| Days In Month                 | Integer                                  |
| Get Week Number               | ISO / locale week                        |

### Files

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Get File Type                 | UTType of file                           |
| Count Files                   | In a folder                              |
| Write or Append to Text File  | Convenience wrapper                      |
| Get Line in Text File         | By index                                 |

### URL

| Name                          | Purpose                                  |
| ----------------------------- | ---------------------------------------- |
| Get URL Components            | Scheme/host/path/query/fragment          |
| Modify URL                    | Replace components                       |
| Parse Query String            | → Dictionary                             |

Total: ~180 actions as of v2.x. Full list on the site.

## Usage patterns

### Generate UUID → use as entity ID

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>com.sindresorhus.Actions.GenerateUUIDIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>UUID</key>
    <string>11111111-1111-1111-1111-111111111111</string>
  </dict>
</dict>
```

⚠ Confirm the exact identifier via round-trip — the literal
`GenerateUUIDIntent` suffix is indicative, not guaranteed.

### Parse JSON with JSON5 tolerance

Use when the API returns valid JSON but native coercion fails
(unusual Content-Type, BOM, trailing comma). Follow with
`getvalueforkey`.

### Global Variable for shared state

Useful for counters and flags shared across shortcuts. Synchronized
via iCloud.

## Discovery

To get the authoritative identifier for any action:

1. On macOS, create a shortcut in Shortcuts.app that uses the action.
2. Export: `shortcuts export "<name>" --output-path /tmp/out.shortcut`.
3. Inspect: `./tools/inspect-shortcut.py /tmp/out.shortcut`.

Alternative (faster for bulk discovery):

```bash
./tools/list-app-intents.py --bundle com.sindresorhus.Actions
```

This parses `/Applications/Actions.app/Contents/Resources/
Metadata.appintents/extract.actionsdata` and dumps the full intent
registry.

## Why this app matters

- Patches most native Shortcuts gaps (hex encoding, SF symbols,
  authenticate, JSON5, etc.).
- Regular updates following iOS releases.
- No subscription, no IAP.
- MIT-licensed — inspect the intent declarations in source at
  `https://github.com/sindresorhus/Actions/tree/main/Shared`.

When the user mentions "Shortcuts action X but it doesn't exist
natively," check Actions first.
