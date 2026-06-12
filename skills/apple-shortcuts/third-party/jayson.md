# Jayson

_Last verified: 2026-04-19_

JSON viewer, formatter, and query tool with Shortcuts integration.

- **App Store**: `https://apps.apple.com/app/jayson/id1447062859`
- **Developer**: Simon Støvring.
- **Bundle ID**: `dk.simonbs.Jayson` ⚠ unverified; pattern matches
  Støvring's other apps.
- **Price**: Free with one-time unlock (~€4) for Pro features.
- **Platforms**: iOS, macOS.

## What it provides

- JSON / JSON5 / YAML parsing and formatting.
- JSONPath / JMESPath queries.
- Schema validation.
- Large-document viewer with tree navigation.

## Shortcut actions

⚠ Intent identifiers not publicly documented. Rediscover via
`tools/list-app-intents.py --bundle dk.simonbs.Jayson`. Named
actions observed:

| Action             | Purpose                                      |
| ------------------ | -------------------------------------------- |
| View JSON          | Open JSON in Jayson viewer                   |
| Format JSON        | Pretty-print with indent options             |
| Query JSON         | JSONPath / JMESPath expression               |
| Validate JSON      | Parse + return success/error                 |
| Convert Format     | JSON ↔ YAML ↔ plist                          |

## When to prefer over native

- Native `Get Dictionary Value` supports `key.subkey[0]` but not full
  JSONPath (`$.items[?(@.price > 10)]`). Jayson handles this.
- Native produces no error when a key is missing; Jayson's Query
  returns a typed error.
- Conversion between JSON and YAML is not available natively.

## Example — JMESPath over an API response

```text
1. Get Contents of URL
2. Jayson: Query JSON
   expression: items[?status == 'open'].id
3. Repeat with Each (over the IDs)
```

## Gotchas

- Pro features may IAP-gate some actions; shortcut fails when
  recipient doesn't own Pro.
- Large documents (> 50MB) may hit iOS extension memory limits.

## Relation to Data Jar and Scriptable

All three are by Støvring and share idioms (naming, icon style,
Shortcut action conventions). A shortcut using multiple Støvring
apps is aesthetically coherent but adds dependencies.
