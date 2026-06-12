# Pattern: Error handling

## Problem

Handle failures gracefully: API errors, missing values, user cancels,
unauthorized states.

## Solution

Shortcuts has no native try/catch. Approximate with:

- `Exit Shortcut` for early termination.
- `If` on sentinel values to detect error shapes.
- Passthrough of input to `Show Alert` / `Show Notification` for user
  feedback.
- Default fallbacks via `If` + `Has Any Value`.

## Plist — guard an API call

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.downloadurl</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFURL</key>
    <string>https://api.example.com/v1/items/42</string>
    <key>WFHTTPMethod</key>
    <string>GET</string>
    <key>UUID</key>
    <string>AAAA0000-AAAA-AAAA-AAAA-AAAAAAAAAAAA</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDictionaryKey</key><string>error</string>
    <key>WFGetDictionaryValueType</key><string>Value</string>
    <key>UUID</key>
    <string>BBBB0000-BBBB-BBBB-BBBB-BBBBBBBBBBBB</string>
    <key>CustomOutputName</key>
    <string>Error Message</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>CCCC0000-CCCC-CCCC-CCCC-CCCCCCCCCCCC</string>
    <key>WFControlFlowMode</key><integer>0</integer>
    <key>WFCondition</key><string>Has Any Value</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.alert</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAlertActionTitle</key>
    <string>API Error</string>
    <key>WFAlertActionMessage</key>
    <string>&#xFFFC;</string>
    <key>WFAlertActionCancelButtonShown</key><false/>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.exit</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>CCCC0000-CCCC-CCCC-CCCC-CCCCCCCCCCCC</string>
    <key>WFControlFlowMode</key><integer>2</integer>
  </dict>
</dict>
```

The `Show Alert` inside the `If` has its message wired to the error
message from Get Dictionary Value. See `references/variables-and-
types.md` for attachment wiring.

## Variations

- **Retry**: wrap the API call in `Repeat 3` with an `If Has Any
  Value` inside to break on success.
- **Fallback value**: after Get Dictionary Value, `If Does Not Have
  Any Value` → Set Variable to default; Otherwise Set Variable to
  fetched value.
- **User cancel as error**: Ask for Input's cancel terminates the
  shortcut. To detect specifically "cancel" vs "empty" — not
  possible natively. Use Toolbox Pro's Present Text Field which
  exposes a cancel result.

## Patterns for specific errors

### HTTP 4xx/5xx

Native `Get Contents of URL` does not fail on HTTP errors. The
response body (typically error JSON) is returned as Dictionary.
Check a known error key; if present, treat as failure.

### Unauthorized (401)

```text
1. Get Contents of URL
2. Get Dictionary Value: error.code (or status / message)
3. If equals "401" or "Unauthorized"
4.   Show Alert "Session expired. Re-authenticate in Settings."
5.   Open Shortcut to the auth shortcut
6.   Exit Shortcut
7. End If
```

### Network failure

A network failure *does* terminate Get Contents of URL with an error
dialog shown to the user. You can't catch this without Toolbox Pro.

Workaround: use Actions app's `Is Online` pre-check:

```text
1. Is Online
2. If not
3.   Show Alert "You're offline."
4.   Exit Shortcut
5. End If
6. Get Contents of URL
```

## Exit Shortcut semantics

`is.workflow.actions.exit` ends the shortcut normally. It does NOT:

- Return an error code to the caller.
- Produce output unless you pass input to it (then that input
  becomes the shortcut's output).

If you want an error-valued output (e.g. when called by another
shortcut via `Run Shortcut`), build a dictionary like
`{ "ok": false, "error": "..." }` and feed it to Exit Shortcut.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.dictionary</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFItems</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>WFDictionaryFieldValueItems</key>
        <array>
          <dict>
            <key>WFItemType</key><integer>4</integer>
            <key>WFKey</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>ok</string>
                <key>attachmentsByRange</key><dict/>
              </dict>
              <key>WFSerializationType</key>
              <string>WFTextTokenString</string>
            </dict>
            <key>WFValue</key><false/>
          </dict>
          <dict>
            <key>WFItemType</key><integer>0</integer>
            <key>WFKey</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>error</string>
                <key>attachmentsByRange</key><dict/>
              </dict>
              <key>WFSerializationType</key>
              <string>WFTextTokenString</string>
            </dict>
            <key>WFValue</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>Validation failed</string>
                <key>attachmentsByRange</key><dict/>
              </dict>
              <key>WFSerializationType</key>
              <string>WFTextTokenString</string>
            </dict>
          </dict>
        </array>
      </dict>
      <key>WFSerializationType</key>
      <string>WFDictionaryFieldValue</string>
    </dict>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.exit</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

## Gotchas

- There is no global exception handler. Each failure mode must be
  explicitly checked where it can occur.
- `Show Alert` with a Cancel button: tapping Cancel terminates the
  shortcut as if Exit had been called. Use `WFAlertActionCancel
  ButtonShown=false` when you don't want that.
- Personal automation context: errors may be invisible. The user
  never sees a dialog. Log via Data Jar or Pushcut notification.
