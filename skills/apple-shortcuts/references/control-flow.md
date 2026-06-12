# Control flow

Shortcuts control flow uses paired start/end actions sharing a
`GroupingIdentifier` UUID. Mismatched or missing ends break import.

## Paired-block rule

Every control flow block is a contiguous pair (or triplet) of action
dicts sharing the same `GroupingIdentifier`. Each element carries a
`WFControlFlowMode` integer:

| Mode | Meaning                                       |
| ---- | --------------------------------------------- |
| `0`  | Block start (`If`, `Repeat`, menu header)     |
| `1`  | Block middle (`Otherwise`, menu item)         |
| `2`  | Block end                                     |

`GroupingIdentifier` is a UUIDv4 generated at write time, shared
across all members of the same block.

## If / Otherwise / End If

Identifier: `is.workflow.actions.conditional`.

### Condition (start, mode 0)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>D1F2E3C4-A5B6-4789-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFCondition</key>
    <string>Equals</string>
    <key>WFConditionalActionString</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>string</key>
        <string>production</string>
        <key>attachmentsByRange</key>
        <dict/>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenString</string>
    </dict>
    <key>WFInput</key>
    <dict>
      <key>Variable</key>
      <dict>
        <key>Value</key>
        <dict>
          <key>Type</key>
          <string>Variable</string>
          <key>VariableName</key>
          <string>env</string>
        </dict>
        <key>WFSerializationType</key>
        <string>WFTextTokenAttachment</string>
      </dict>
    </dict>
  </dict>
</dict>
```

### Otherwise (middle, mode 1)

Optional. Skip if you only want `if` without `else`.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>D1F2E3C4-A5B6-4789-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>1</integer>
  </dict>
</dict>
```

### End If (end, mode 2)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>D1F2E3C4-A5B6-4789-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>2</integer>
    <key>UUID</key>
    <string>E1F2E3C4-A5B6-4789-0123-456789ABCDEF</string>
  </dict>
</dict>
```

The `End If` may carry its own `UUID` and produce output — the
output is the last value produced inside the chosen branch.
Reference this UUID from downstream actions to capture the If's
result.

### `WFCondition` values

Compare strings:

| Value             | Operator             |
| ----------------- | -------------------- |
| `Equals`          | `==`                 |
| `Does Not Equal`  | `!=`                 |
| `Contains`        | substring            |
| `Does Not Contain`| substring negation   |
| `Begins With`     | prefix               |
| `Ends With`       | suffix               |
| `Has Any Value`   | non-null             |
| `Does Not Have Any Value` | null         |

Compare numbers:

| Value                            | Operator |
| -------------------------------- | -------- |
| `Equals`                         | `==`     |
| `Does Not Equal`                 | `!=`     |
| `Is Greater Than`                | `>`      |
| `Is Greater Than or Equal To`    | `>=`     |
| `Is Less Than`                   | `<`      |
| `Is Less Than or Equal To`       | `<=`     |
| `Is Between`                     | range    |

When `WFCondition` is `Is Between`, provide both
`WFConditionalActionNumber` (lower) and
`WFConditionalActionAnotherNumber` (upper).

When `WFCondition` is `Equals` / string comparisons, use
`WFConditionalActionString`. When numeric, use
`WFConditionalActionNumber`.

## Repeat (fixed count)

Identifier: `is.workflow.actions.repeat.count`.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.repeat.count</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>F1A2B3C4-D5E6-4789-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFRepeatCount</key>
    <integer>3</integer>
  </dict>
</dict>
...
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.repeat.count</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>F1A2B3C4-D5E6-4789-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>2</integer>
    <key>UUID</key>
    <string>F1A2B3C4-DEAD-BEEF-0123-456789ABCDEF</string>
  </dict>
</dict>
```

Special variables inside a `Repeat.count` block:

- `Repeat Index` — 1-based iteration index. Accessible via
  `Type: Variable, VariableName: Repeat Index` in attachments.

Output of the end is the list of values returned by the body
(concatenated, per iteration).

## Repeat with Each

Identifier: `is.workflow.actions.repeat.each`.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.repeat.each</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>01234567-89AB-CDEF-0123-456789ABCDEF</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFInput</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>Type</key>
        <string>Variable</string>
        <key>VariableName</key>
        <string>items</string>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenAttachment</string>
    </dict>
  </dict>
</dict>
```

Special variables:

- `Repeat Item` — current list element.
- `Repeat Index` — 1-based.

End is the same shape as `Repeat.count`'s end, mode 2.

## Choose from Menu

Identifier: `is.workflow.actions.choosefrommenu`.

Three kinds of members:

- Mode 0 (start): menu prompt + item list.
- Mode 1 (middle): one per menu item; the body follows until the
  next mode-1 or the end.
- Mode 2 (end): close.

Start:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.choosefrommenu</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>ABCDEF01-2345-6789-ABCD-EF0123456789</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFMenuPrompt</key>
    <string>Choose an action</string>
    <key>WFMenuItems</key>
    <array>
      <string>Create</string>
      <string>Read</string>
      <string>Update</string>
      <string>Delete</string>
    </array>
  </dict>
</dict>
```

Middle (one per item):

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.choosefrommenu</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>ABCDEF01-2345-6789-ABCD-EF0123456789</string>
    <key>WFControlFlowMode</key>
    <integer>1</integer>
    <key>WFMenuItemTitle</key>
    <string>Create</string>
  </dict>
</dict>
<!-- actions for "Create" branch here -->
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.choosefrommenu</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>ABCDEF01-2345-6789-ABCD-EF0123456789</string>
    <key>WFControlFlowMode</key>
    <integer>1</integer>
    <key>WFMenuItemTitle</key>
    <string>Read</string>
  </dict>
</dict>
<!-- actions for "Read" branch here -->
<!-- ... -->
```

End:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.choosefrommenu</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>ABCDEF01-2345-6789-ABCD-EF0123456789</string>
    <key>WFControlFlowMode</key>
    <integer>2</integer>
  </dict>
</dict>
```

`WFMenuItemTitle` in each middle must match one of the `WFMenuItems`
strings in the start (exact match including case).

## Wait (delay)

Identifier: `is.workflow.actions.delay`.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.delay</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDelayTime</key>
    <real>2.5</real>
  </dict>
</dict>
```

Unit is seconds. Decimals allowed.

## Exit Shortcut

Identifier: `is.workflow.actions.exit`.

Early-exit. The shortcut ends; downstream actions do not run.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.exit</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

## Stop and Output

Identifier: ⚠ unverified. Shortcuts has a "Stop and Output" variant
in the UI distinct from plain Exit. Round-trip an example through
Shortcuts.app (see `third-party/discovery-pattern.md`) before
generating.

## Nothing

Identifier: `is.workflow.actions.nothing`.

A no-op. Useful as a placeholder or to block variable propagation.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.nothing</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

## Comment

Identifier: `is.workflow.actions.comment`.

Annotation-only, no effect on execution.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.comment</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFCommentActionText</key>
    <string>Fetch user, validate, save</string>
  </dict>
</dict>
```

## Validation rules specific to control flow

- `GroupingIdentifier` must be present on every control flow action.
- For `conditional`: exactly one mode-0, zero or one mode-1, exactly
  one mode-2 per GroupingIdentifier.
- For `repeat.count` / `repeat.each`: exactly one mode-0 and one
  mode-2.
- For `choosefrommenu`: one mode-0, N mode-1 (one per `WFMenuItems`),
  one mode-2.
- Blocks must be properly nested. No crossing boundaries.
- Mode-0 must appear before its paired mode-2 in the actions array.

## Nested control flow

Nesting is supported. Each inner block gets its own
`GroupingIdentifier`. Example — `If` inside `Repeat`:

```text
Repeat (GID_A, mode 0)
  If (GID_B, mode 0)
    ...
  Otherwise (GID_B, mode 1)
    ...
  End If (GID_B, mode 2)
End Repeat (GID_A, mode 2)
```

Each block's start/middle/end share their own UUID; no overlap.

## Common bugs

- Orphan start without end — Shortcuts refuses to import.
- Reused GroupingIdentifier across blocks — same symptom.
- Middle (`Otherwise`, menu item) outside its block — same.
- Menu item title typo — the branch never runs; no error reported.
- `WFControlFlowMode` as string instead of integer — silently
  ignored; the action behaves as if mode 0.

## Sources

- joshfarrant shortcuts-js:
  `https://github.com/joshfarrant/shortcuts-js`
- sebj iOS Shortcuts reference (If/Repeat/Menu detail):
  `https://github.com/sebj/iOS-Shortcuts-Reference`
