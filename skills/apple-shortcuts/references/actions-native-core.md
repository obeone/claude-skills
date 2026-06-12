# Core native actions

Text, dictionary/list constructors, variables, scripting, device,
and utility actions. All identifiers prefixed with
`is.workflow.actions.`.

For the flat identifier index see `actions-native-full-index.md`.

## Text

### Text (`gettext`)

**Identifier**: `is.workflow.actions.gettext`
**Platforms**: iOS, macOS, watchOS
**Input**: passthrough (anything)
**Output**: Text

**Parameters**:

| Key                 | Type                    | Required | Notes               |
| ------------------- | ----------------------- | -------- | ------------------- |
| `WFTextActionText`  | String or text token    | Yes      | The text content    |
| `UUID`              | String                  | No       | For downstream ref  |
| `CustomOutputName`  | String                  | No       | UI label            |

**Minimal**:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextActionText</key>
    <string>Hello world</string>
  </dict>
</dict>
```

**With interpolation**: use a `WFTextTokenString` dict for
`WFTextActionText` (see `variables-and-types.md`).

**Gotcha**: `text` (without `get`) is also seen in some exports as an
identifier; canonical form per joshfarrant enumeration is `gettext`.
Use `gettext`.

### URL (`url`)

**Identifier**: `is.workflow.actions.url`
**Input**: ignored
**Output**: URL

**Parameters**:

| Key             | Type         | Required | Notes                |
| --------------- | ------------ | -------- | -------------------- |
| `WFURLActionURL`| String/token | Yes      | URL (may be variable)|

**Minimal**:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.url</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFURLActionURL</key>
    <string>https://api.example.com/v1</string>
  </dict>
</dict>
```

### Number (`number`)

**Identifier**: `is.workflow.actions.number`
**Output**: Number

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.number</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFNumberActionNumber</key>
    <real>3.14</real>
  </dict>
</dict>
```

### Date (`date`)

**Identifier**: `is.workflow.actions.date`
**Output**: Date

**Parameters**:

| Key              | Type   | Required | Notes                        |
| ---------------- | ------ | -------- | ---------------------------- |
| `WFDateActionMode` | String | No     | `Current Date`, `Specified Date` |
| `WFDateActionDate` | Date   | If mode is `Specified Date` | ISO-8601 date |

**Minimal (now)**:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.date</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDateActionMode</key>
    <string>Current Date</string>
  </dict>
</dict>
```

### Format Date (`format.date`)

**Identifier**: `is.workflow.actions.format.date`
**Input**: Date
**Output**: Text

**Parameters**:

| Key                      | Type   | Required | Notes                           |
| ------------------------ | ------ | -------- | ------------------------------- |
| `WFDateFormatStyle`      | String | Yes      | `None`, `Short`, `Medium`, `Long`, `Full`, `Custom` |
| `WFTimeFormatStyle`      | String | No       | Same scale                      |
| `WFDateFormat`           | String | If style is `Custom` | Unicode date format string |

**ICU date tokens** (when `WFDateFormatStyle` is `Custom`):

| Token | Meaning       | Example |
| ----- | ------------- | ------- |
| `yyyy`| 4-digit year  | 2026    |
| `MM`  | 2-digit month | 04      |
| `dd`  | 2-digit day   | 19      |
| `HH`  | 24-hour       | 14      |
| `mm`  | minute        | 30      |
| `ss`  | second        | 45      |
| `EEE` | short weekday | Sun     |

**Example**:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.format.date</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDateFormatStyle</key>
    <string>Custom</string>
    <key>WFDateFormat</key>
    <string>yyyy-MM-dd HH:mm</string>
  </dict>
</dict>
```

### Change Case (`text.changecase`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.text.changecase</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFCaseType</key>
    <string>UPPERCASE</string>
  </dict>
</dict>
```

`WFCaseType` values: `UPPERCASE`, `lowercase`, `Capitalize Every Word`,
`Capitalize with Title Case`, `Capitalize with sentence case`.

### Match Text (`text.match`)

Regex matcher.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.text.match</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFMatchTextPattern</key>
    <string>\b[\w.%+-]+@[\w.-]+\.[A-Z]{2,}\b</string>
    <key>WFMatchTextCaseSensitive</key>
    <false/>
  </dict>
</dict>
```

Output is a list of match strings. Follow with `Get Group from
Matched Text` (`text.match.getgroup`) to extract capture groups.

### Replace Text (`text.replace`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.text.replace</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFReplaceTextFind</key>
    <string>foo</string>
    <key>WFReplaceTextReplace</key>
    <string>bar</string>
    <key>WFReplaceTextCaseSensitive</key>
    <true/>
    <key>WFReplaceTextRegularExpression</key>
    <false/>
  </dict>
</dict>
```

### Split Text (`text.split`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.text.split</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextSeparator</key>
    <string>New Lines</string>
  </dict>
</dict>
```

`WFTextSeparator` values: `New Lines`, `Spaces`, `Custom`. When
`Custom`, provide `WFTextCustomSeparator`.

### Combine Text (`text.combine`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.text.combine</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextSeparator</key>
    <string>New Lines</string>
  </dict>
</dict>
```

## Variables

### Set Variable (`setvariable`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setvariable</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFVariableName</key>
    <string>counter</string>
  </dict>
</dict>
```

Value stored is the prior action's output.

### Get Variable (`getvariable`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvariable</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFVariable</key>
    <dict>
      <key>Value</key>
      <dict>
        <key>Type</key>
        <string>Variable</string>
        <key>VariableName</key>
        <string>counter</string>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenAttachment</string>
    </dict>
  </dict>
</dict>
```

### Add to Variable (`appendvariable`)

Appends to a variable's list.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.appendvariable</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFVariableName</key>
    <string>results</string>
  </dict>
</dict>
```

First use: creates a list variable. Subsequent uses: append.

## Dictionary and list

### Dictionary (`dictionary`)

Inline dict literal.

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
            <key>WFItemType</key><integer>0</integer>
            <key>WFKey</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>name</string>
                <key>attachmentsByRange</key><dict/>
              </dict>
              <key>WFSerializationType</key>
              <string>WFTextTokenString</string>
            </dict>
            <key>WFValue</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>Alice</string>
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
```

See `variables-and-types.md` for `WFItemType` encoding.

### Get Dictionary Value (`getvalueforkey`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFGetDictionaryValueType</key>
    <string>Value</string>
    <key>WFDictionaryKey</key>
    <string>user.email</string>
  </dict>
</dict>
```

`WFGetDictionaryValueType` values: `Value`, `All Keys`, `All Values`,
`Dictionary`.

`WFDictionaryKey` supports dotted key paths and `[N]` index access.

### Set Dictionary Value (`setvalueforkey`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setvalueforkey</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDictionaryKey</key>
    <string>user.email</string>
    <key>WFDictionaryValue</key>
    <string>alice@example.com</string>
  </dict>
</dict>
```

### List (`list`)

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
            <key>string</key><string>one</string>
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
            <key>string</key><string>two</string>
            <key>attachmentsByRange</key><dict/>
          </dict>
          <key>WFSerializationType</key>
          <string>WFTextTokenString</string>
        </dict>
      </dict>
    </array>
  </dict>
</dict>
```

### Get Item from List (`getitemfromlist`)

⚠ identifier not in joshfarrant 2019 enumeration; widely observed.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getitemfromlist</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFItemSpecifier</key>
    <string>First Item</string>
  </dict>
</dict>
```

`WFItemSpecifier` values: `First Item`, `Last Item`, `Random Item`,
`Item at Index`, `Items in Range`. When `Item at Index`, add
`WFItemIndex` (integer).

### Count (`count`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.count</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFCountType</key>
    <string>Items</string>
  </dict>
</dict>
```

`WFCountType` values: `Items`, `Characters`, `Words`, `Sentences`,
`Lines`.

## Scripting (iOS + macOS)

### Run JavaScript (`runjavascriptonwebpage`)

**Safari-only, iOS and macOS.** Runs JS against the current Safari
tab or a Web Page input.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.runjavascriptonwebpage</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFJavaScript</key>
    <string>document.title</string>
  </dict>
</dict>
```

### Run Shortcut (`runworkflow`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.runworkflow</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFWorkflowName</key>
    <string>Helper</string>
    <key>WFShowWhenRun</key>
    <false/>
  </dict>
</dict>
```

Input passed to the called shortcut is the preceding action's output.
Output is whatever the called shortcut returns. `WFShowWhenRun=false`
runs headless.

### Calculate (`math`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.math</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFMathOperand</key>
    <integer>2</integer>
    <key>WFMathOperation</key>
    <string>×</string>
  </dict>
</dict>
```

`WFMathOperation` is one of `+`, `−`, `×`, `÷`, `mod`, `^`. Note the
Unicode mathematical operators (not ASCII `*` or `/`) — these are
the literal values Shortcuts writes.

### Scientific calculator (`calculateexpression`)

⚠ identifier unverified. For complex expressions, round-trip an
example before generating.

### Random Number (`number.random`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.number.random</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFRandomNumberLowerBound</key>
    <integer>1</integer>
    <key>WFRandomNumberUpperBound</key>
    <integer>100</integer>
  </dict>
</dict>
```

## Scripting (macOS-only)

### Run Shell Script

**Identifier**: ⚠ unverified. Typically seen as
`is.workflow.actions.runshellscript` or a bundle-specific identifier
in recent macOS. Round-trip an example from Shortcuts.app before
generating.

**Parameters** (observed):

| Key                    | Type    | Notes                    |
| ---------------------- | ------- | ------------------------ |
| `Script`               | String  | The shell script text    |
| `Shell`                | String  | `/bin/zsh`, `/bin/bash`, etc. |
| `Input`                | String  | `to stdin`, `as arguments` |
| `InputMode`            | String  | Input handling           |

### Run AppleScript

**Identifier**: ⚠ unverified (likely
`is.workflow.actions.runapplescript`). Same caveat — round-trip.

### Run JavaScript for Automation

**Identifier**: ⚠ unverified. JXA. macOS-only.

For all three above: generate the plist using the identifier you
observed from a round-trip export via
`third-party/discovery-pattern.md`. This skill intentionally does
not invent these.

## Device

### Set Brightness (`setbrightness`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setbrightness</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFBrightness</key>
    <real>0.5</real>
  </dict>
</dict>
```

Range: 0.0 to 1.0.

### Set Volume (`setvolume`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setvolume</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFVolume</key>
    <real>0.75</real>
  </dict>
</dict>
```

### Vibrate Device (`vibrate`)

iOS only.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.vibrate</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

### Set Wi-Fi (`wifi.set`)

iOS only.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.wifi.set</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>OnValue</key>
    <true/>
  </dict>
</dict>
```

### Set Airplane Mode (`airplanemode.set`)

Same shape as Set Wi-Fi.

### Set Bluetooth (`bluetooth.set`)

Same shape.

### Set Cellular Data (`cellulardata.set`)

iOS only. Same shape.

### Set Low Power Mode (`lowpowermode.set`)

Same shape.

### Set Flashlight (`flashlight`)

iOS only.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.flashlight</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFFlashlightSetting</key>
    <string>On</string>
  </dict>
</dict>
```

`WFFlashlightSetting` values: `On`, `Off`, `Toggle`.

### Get Battery Level (`getbatterylevel`)

Output: Number (0.0 to 1.0).

### Get Device Details (`getdevicedetails`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getdevicedetails</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDeviceDetail</key>
    <string>Device Name</string>
  </dict>
</dict>
```

`WFDeviceDetail` values: `Device Name`, `Device Hostname`,
`Device Model`, `System Version`, `Screen Width`, `Screen Height`,
`Current Volume`, `Current Brightness`, `Current Network`,
`Current Wi-Fi Network`, `IP Address`.

## Utility

### Comment (`comment`)

See `control-flow.md`.

### Nothing (`nothing`)

See `control-flow.md`.

### Wait / Delay (`delay`)

See `control-flow.md`.

### Get Name (`getitemname`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getitemname</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Output: the input item's name.

### Get Type (`getitemtype`)

Returns the content-item type of the input.

### Set Name (`setitemname`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setitemname</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFName</key>
    <string>new name</string>
  </dict>
</dict>
```

Useful before `Save File` to control the saved filename.

## Sources

- joshfarrant/shortcuts-js:
  `https://github.com/joshfarrant/shortcuts-js`
- sebj reference:
  `https://github.com/sebj/iOS-Shortcuts-Reference`
- openclaw shortcuts-skill:
  `https://github.com/openclaw/skills`
