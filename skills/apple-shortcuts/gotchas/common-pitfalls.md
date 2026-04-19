# Gotcha: Common pitfalls

### Variable scope leaks out of If / Repeat

**Symptom**: A variable set inside `If` body is readable after `End
If`.

**Cause**: Shortcuts variables are shortcut-global. No block scope.

**Fix**: Expected behavior. Plan accordingly. To avoid leaks, use
magic variables (per-action UUIDs) instead of named variables —
they're implicitly scoped to the action that produced them.

### Get Dictionary Value on missing key returns empty string

**Symptom**: Downstream logic receives "" instead of an error.

**Cause**: Native silently returns empty on miss.

**Fix**: Guard with `If Has Any Value`. See
`patterns/error-handling.md`.

### Named variable read before set returns empty string

Same silent-empty behavior. Unlike programming languages, no
"undefined" error.

### UUID duplicates

**Symptom**: Shortcut imports but behaves oddly — magic variable
references resolve to the wrong producer.

**Cause**: Two actions share the same `UUID`. Shortcuts picks
whichever comes first when resolving `OutputUUID`.

**Fix**: Generate unique UUIDs per action. `validate-shortcut.py`
reports duplicates as errors.

### Magic variable bound to renamed producer shows stale name

**Symptom**: The UI shows an outdated variable name chip; the
underlying value resolves correctly.

**Cause**: `OutputName` in the consumer is a cached display name.
After renaming the producer's `CustomOutputName`, the consumer's
`OutputName` is stale.

**Fix**: Cosmetic-only. If it bothers you, update all consumer
`OutputName` values to match. Shortcuts app refreshes on re-save.

### attachmentsByRange off-by-one

**Symptom**: Variable interpolation places the value in the wrong
position, or shows the variable chip as plain text.

**Cause**: The `{position, length}` key doesn't match the U+FFFC
character's actual position (UTF-16 index) or length (always 1).

**Fix**:

- Position = exact UTF-16 code-unit index of the U+FFFC character.
- Length = 1 per FFFC.
- Count carefully with multi-byte characters (emoji, CJK) — they
  may be 1 or 2 UTF-16 units.

Use `tools/validate-shortcut.py` which checks these ranges.

### Object replacement character missing from string

**Symptom**: The variable's value doesn't render in the text.

**Cause**: `attachmentsByRange` has entries but the `string` lacks
U+FFFC at the specified positions.

**Fix**: Each attachment needs exactly one U+FFFC in `string` at
its declared position.

### WFControlFlowMode written as string instead of integer

**Symptom**: If / Repeat behaves as if mode 0; Otherwise branch
doesn't run.

**Cause**: `<string>0</string>` instead of `<integer>0</integer>`.

**Fix**: Use `<integer>` for `WFControlFlowMode`. Always.

### GroupingIdentifier reused across blocks

**Symptom**: Shortcut fails to import or behaves chaotically.

**Cause**: Two different control-flow blocks share the same
`GroupingIdentifier`.

**Fix**: Generate a unique UUID for each block. Inner nested blocks
get their own.

### Missing end for a start block

**Symptom**: "Couldn't add shortcut" during import.

**Cause**: An `if` without matching `end if`, or `repeat` without
`end repeat`.

**Fix**: Pair every mode-0 with a mode-2 sharing the same UUID.

### Menu item title typo

**Symptom**: Menu branch never fires; no error.

**Cause**: `WFMenuItemTitle` doesn't match any entry in the start's
`WFMenuItems` array (case-sensitive).

**Fix**: Copy titles literally. Validate with
`tools/validate-shortcut.py`.

### 32-bit integer overflow in dictionaries

**Symptom**: Large integers (e.g. timestamps in microseconds)
truncate.

**Cause**: ⚠ observed in some older Shortcuts builds; dict integer
values can be limited to 32-bit in legacy serialization paths.

**Fix**: Store large numbers as strings in dictionaries; convert
on use via Number action or Aggrandizement.

### Shortcut Input is empty when run from app

**Symptom**: `WFWorkflowHasShortcutInputVariables=true` but the
variable is empty when running manually.

**Cause**: Manual run has no input. `Shortcut Input` is populated
only from Share Sheet / caller.

**Fix**: Guard with `Has Any Value` on Shortcut Input. Fall back
to `Ask for Input`.

### Running in automation context silences UI actions

**Symptom**: Ask for Input / Show Alert / Choose from Menu skipped
when run via Personal Automation.

**Cause**: Silent automation context can't render UI. Actions that
require UI either fail or are skipped depending on version.

**Fix**: Detect context (no clean native way, workaround: check
`Shortcut Input` presence). For automation-only shortcuts, design
without UI. Use Show Notification for visible feedback.

### Clipboard actions fail silently on lock screen

**Symptom**: Set Clipboard / Get Clipboard succeed in the UI but
not when triggered from a locked state.

**Cause**: Clipboard access gated by foreground state in
background contexts.

**Fix**: Use Pushcut's notification action for cross-context
messaging; avoid clipboard as a channel.

### Shortcuts silently changes WFWorkflowMinimumClientVersion on save

**Symptom**: You set `WFWorkflowMinimumClientVersion=900` but
Shortcuts.app re-saves with a higher value.

**Cause**: When the shortcut uses an action that requires newer
Shortcuts, the app raises the minimum on save.

**Fix**: Expected. Sign after your final edit; Shortcuts's
modification is fine and keeps the shortcut importable on the
actual minimum OS.

### iCloud-shared shortcut doesn't update after edit

**Symptom**: You edit a shortcut, re-share the iCloud link; the
recipient still sees the old version.

**Cause**: iCloud share URLs are immutable per version. Editing
produces a new UUID.

**Fix**: Re-share the shortcut to generate a new link. Old link
keeps serving the old version.
