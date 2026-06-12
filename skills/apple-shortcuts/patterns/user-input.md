# Pattern: User input

## Problem

Ask the user for text, a choice from a list, or a yes/no
confirmation during shortcut execution.

## Solution

Three native actions cover the bases:

- `is.workflow.actions.ask` — Ask for Input (text/number/URL/date).
- `is.workflow.actions.choosefromlist` — Pick one or many from a
  supplied list.
- `is.workflow.actions.choosefrommenu` — Branch control flow by
  choice. See `references/control-flow.md`.

Plus `is.workflow.actions.alert` for confirmations.

## Ask for Input

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.ask</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAskActionPrompt</key>
    <string>What is the filename?</string>
    <key>WFInputType</key>
    <string>Text</string>
    <key>WFAskActionDefaultAnswer</key>
    <string>untitled.txt</string>
    <key>UUID</key>
    <string>99999999-9999-9999-9999-999999999999</string>
    <key>CustomOutputName</key>
    <string>Filename</string>
  </dict>
</dict>
```

`WFInputType` values: `Text`, `Number`, `URL`, `Date`, `Time`,
`Date and Time`.

Cancelation: tapping Cancel terminates the shortcut.

## Choose from List

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.list</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFItems</key>
    <array>
      <dict>
        <key>WFItemType</key><integer>0</integer>
        <key>WFValue</key>
        <dict>
          <key>Value</key>
          <dict>
            <key>string</key><string>Option A</string>
            <key>attachmentsByRange</key><dict/>
          </dict>
          <key>WFSerializationType</key>
          <string>WFTextTokenString</string>
        </dict>
      </dict>
      <dict>
        <key>WFItemType</key><integer>0</integer>
        <key>WFValue</key>
        <dict>
          <key>Value</key>
          <dict>
            <key>string</key><string>Option B</string>
            <key>attachmentsByRange</key><dict/>
          </dict>
          <key>WFSerializationType</key>
          <string>WFTextTokenString</string>
        </dict>
      </dict>
    </array>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.choosefromlist</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFChooseFromListActionPrompt</key>
    <string>Pick one</string>
    <key>WFChooseFromListActionSelectMultiple</key>
    <false/>
  </dict>
</dict>
```

Returns the selected string (or list of strings if `SelectMultiple=
true`).

## Choose from Menu — branching by choice

When the user's choice dictates different behavior per branch, use
Choose from Menu. See `references/control-flow.md` for the full
plist shape.

Quick summary:

```text
Choose from Menu "Action"
  items: ["Create", "Read", "Update", "Delete"]

  Menu item "Create"
    ... Create actions ...
  Menu item "Read"
    ... Read actions ...
  Menu item "Update"
    ... Update actions ...
  Menu item "Delete"
    Alert "Confirm?"
    Delete action
End Menu
```

## Show Alert as a confirmation

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.alert</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAlertActionTitle</key>
    <string>Delete file?</string>
    <key>WFAlertActionMessage</key>
    <string>This cannot be undone.</string>
    <key>WFAlertActionCancelButtonShown</key><true/>
  </dict>
</dict>
```

User taps Cancel → shortcut terminates immediately. User taps OK →
execution continues.

## Variations

- **Pre-filled Ask**: set `WFAskActionDefaultAnswer` to a value from
  a prior action via `WFTextTokenString`.
- **Ask for password / secret**: native Ask doesn't hide input.
  Use Actions app's `Authenticate` or Toolbox Pro's `Present Text
  Field` (which has a secure-entry option).
- **Choose from dynamic list**: build the list at runtime (e.g. from
  an API response) and feed into Choose from List.

## Gotchas

- **Ask triggers keyboard on iOS**; in an automation context it may
  fail silently if UI isn't available.
- **Choose from List on an empty list** terminates the shortcut with
  "No items to choose from" — guard with `Count Items` + `If`.
- **Choose from Menu vs Choose from List**: menu branches the
  action flow by selection; list returns the selection as a value
  without branching.
- **Personal automations cannot show UI**. Automations running
  silently skip Ask/Alert/Menu entirely or behave inconsistently.
  Use Data Jar for persisted choices or Pushcut for notification-
  based branching.
