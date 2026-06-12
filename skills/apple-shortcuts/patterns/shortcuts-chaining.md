# Pattern: Chaining shortcuts

## Problem

Call one shortcut from another. Pass data in. Get data out. Compose
small focused shortcuts into larger workflows.

## Solution

Use `is.workflow.actions.runworkflow` (Run Shortcut). Input to the
action becomes input to the called shortcut. Output of the called
shortcut is the action's output.

## Plist — call a helper

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextActionText</key>
    <string>https://example.com/long-url-to-shorten</string>
    <key>UUID</key>
    <string>10101010-1010-1010-1010-101010101010</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.runworkflow</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFWorkflowName</key>
    <string>URL Shortener</string>
    <key>WFShowWhenRun</key>
    <false/>
    <key>WFInput</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>Type</key>
        <string>ActionOutput</string>
        <key>OutputName</key><string>Text</string>
        <key>OutputUUID</key>
        <string>10101010-1010-1010-1010-101010101010</string>
        <key>Aggrandizements</key><array/>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenAttachment</string>
    </dict>
    <key>UUID</key>
    <string>20202020-2020-2020-2020-202020202020</string>
    <key>CustomOutputName</key>
    <string>Short URL</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.showresult</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>Text</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>string</key>
        <string>Shortened to: &#xFFFC;</string>
        <key>attachmentsByRange</key>
        <dict>
          <key>{14, 1}</key>
          <dict>
            <key>Type</key><string>ActionOutput</string>
            <key>OutputName</key><string>Short URL</string>
            <key>OutputUUID</key>
            <string>20202020-2020-2020-2020-202020202020</string>
            <key>Aggrandizements</key><array/>
          </dict>
        </dict>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenString</string>
    </dict>
  </dict>
</dict>
```

## `runworkflow` parameters

| Key                | Type           | Notes                       |
| ------------------ | -------------- | --------------------------- |
| `WFWorkflowName`   | String         | Display name of the called shortcut |
| `WFInput`          | Attachment     | Explicit input (optional)  |
| `WFShowWhenRun`    | Bool           | Open Shortcuts UI while running |
| `UUID`             | String         | For referencing output      |

When `WFInput` is omitted, the preceding action's output is passed
as input. When set, the explicit input wins.

## Returning structured output

The called shortcut should end with a Dictionary / Text / whatever
you want as output. Shortcuts passes back the last action's output
unless an explicit `Exit Shortcut` was invoked earlier.

Convention for structured result:

```text
Called shortcut:
  ... logic ...
  Dictionary { ok: true, data: <value> }
  (implicit return via last action)
```

Caller:

```text
Run Shortcut "HelperName"
Get Dictionary Value "ok"
If equal to false:
  Get Dictionary Value "error"
  Show Alert
End If
```

## Variations

- **Silent run**: `WFShowWhenRun=false`. No visual transition.
- **Show called shortcut UI**: `WFShowWhenRun=true`. Useful when the
  helper contains Ask for Input.
- **iCloud-shared helper**: Name must match exactly, case-sensitive.
  Shortcuts are addressable only by display name.
- **Parameterized action-via-intent**: on iOS 15+, some built-in
  apps expose shortcut-like actions via App Intents with named
  parameters. These are not `runworkflow` — they are their own
  action identifiers discovered via `tools/list-app-intents.py`.

## Deep linking

`shortcuts://run-shortcut?name=<Name>&input=<text>` is a URL scheme
for triggering a shortcut from any URL-capable context (clipboard,
browser, another app). Useful for bridging non-Shortcuts apps; not
used from inside a shortcut — `runworkflow` is cleaner internally.

## Gotchas

- **Name must match exactly.** No fuzzy match. A renamed called
  shortcut breaks the caller.
- **Recursion allowed** but no tail-call optimization. Deep
  recursion stack-overflows; Shortcuts errors with "Too many nested
  shortcut calls" (limit is ~10).
- **Circular calls** are allowed syntactically and deadlock at the
  nesting limit.
- **Output type**: Shortcuts doesn't enforce type contracts between
  caller and callee. A callee returning text when the caller
  expected a dictionary will cause downstream Get Dictionary Value
  to return empty string silently.
- **iOS vs macOS**: a shortcut using `runworkflow` requires the
  called shortcut to exist on the running device. iCloud sync is
  not instant; after import the called shortcut must be available
  locally.
