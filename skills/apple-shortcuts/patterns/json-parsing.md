# Pattern: JSON parsing

## Problem

Extract values from a JSON object or array returned by an API or
stored in a file.

## Solution

Rely on native auto-coercion + `is.workflow.actions.getvalueforkey`
(Get Dictionary Value) with a dotted / indexed key path.

## Plist — extract from nested JSON

Suppose the response is:

```json
{
  "user": {
    "profile": { "name": "Alice", "email": "a@x.com" },
    "permissions": ["read", "write", "admin"]
  }
}
```

To get `user.profile.email`:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFGetDictionaryValueType</key>
    <string>Value</string>
    <key>WFDictionaryKey</key>
    <string>user.profile.email</string>
  </dict>
</dict>
```

To get the third permission:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFGetDictionaryValueType</key>
    <string>Value</string>
    <key>WFDictionaryKey</key>
    <string>user.permissions[2]</string>
  </dict>
</dict>
```

## `WFGetDictionaryValueType` values

| Value          | Returns                                         |
| -------------- | ----------------------------------------------- |
| `Value`        | Value at the key path                           |
| `All Keys`     | Top-level keys as a list                        |
| `All Values`   | Top-level values as a list                      |
| `Dictionary`   | Subdict at the key path                         |

## Key path syntax

- `a.b.c` — nested dict access.
- `list[N]` — zero-based array index.
- `a.b[0].c` — combined.
- Special keys containing `.` or `[` require escape — ⚠ not cleanly
  supported natively. Workaround: Scriptable or Jayson.

## Variations

- **Iterate over an array**: `Get Dictionary Value: users` →
  `Repeat with Each` → inside the body, the current element is
  `Repeat Item`; extract fields from it with `getvalueforkey`.
- **Missing key handling**: `Get Dictionary Value` on a missing key
  returns empty string (*not* an error). Guard with `If` + `Has Any
  Value`.

```xml
<!-- After getvalueforkey on "optional_field" -->
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>GUARD-UUID-HERE-0000-000000000000</string>
    <key>WFControlFlowMode</key><integer>0</integer>
    <key>WFCondition</key><string>Has Any Value</string>
  </dict>
</dict>
```

## Parsing JSON from a string (not from URL)

When JSON arrives as a string (clipboard, file, Ask for Input) it is
*not* auto-coerced. Two paths:

### Native: coerce via aggrandizement

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFInput</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>Type</key><string>Variable</string>
        <key>VariableName</key><string>json_text</string>
        <key>Aggrandizements</key>
        <array>
          <dict>
            <key>Type</key>
            <string>WFCoercionVariableAggrandizement</string>
            <key>CoercionItemClass</key>
            <string>WFDictionaryContentItem</string>
          </dict>
        </array>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenAttachment</string>
    </dict>
    <key>WFDictionaryKey</key>
    <string>user.name</string>
  </dict>
</dict>
```

`CoercionItemClass=WFDictionaryContentItem` parses the string as
JSON before extraction. ⚠ strict JSON only; trailing commas fail.

### Actions app: Parse JSON / JSON5

Handles edge cases native can't:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>com.sindresorhus.Actions.ParseJSON5Intent</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

⚠ Literal identifier unverified; discover via
`tools/list-app-intents.py --bundle com.sindresorhus.Actions`.

## Building JSON to send

`Get Contents of URL` with `WFHTTPBodyType=JSON` takes a
`WFJSONValues` of `WFDictionaryFieldValue`. See
`references/actions-native-web.md` for the full shape.

For deeply nested output, consider building a dictionary via
`is.workflow.actions.dictionary` then passing it as input.

## Gotchas

- **Silent missing keys**: Get Dictionary Value's empty-string on
  miss is the #1 source of silent bugs. Always guard with `Has Any
  Value` when the field is optional.
- **Type coercion fragility**: if an API returns `"123"` (string) and
  downstream code expects a number, Shortcuts will treat it as text
  in some actions and number in others. Explicit coercion via
  aggrandizement is reliable; concatenation is not.
- **Booleans**: JSON booleans come through as Shortcuts booleans
  (0/1 in UI but boolean internally). `If` conditions on them work.
- **null vs missing**: JSON `null` and missing key both produce empty
  string. No way to distinguish natively.
- **Arrays of mixed types** — iterating with `Repeat with Each`
  works but each iteration's type is inferred per-item, causing
  downstream actions to behave inconsistently.
