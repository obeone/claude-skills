# Variables and types

Three variable flavors and a serialization system. Getting these
right is ~80% of "generated shortcuts that actually run."

## Variable flavors

### 1. Magic variables (action outputs)

Every action that produces a value can be referenced by downstream
actions. The producer carries a `UUID` in its parameters; consumers
reference that UUID in an attachment dict.

Producer (a Text action whose output is "Greeting"):

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>UUID</key>
    <string>A7D4F6C2-1B3E-4F5A-9C0D-2E4F6A8B1C3D</string>
    <key>CustomOutputName</key>
    <string>Greeting</string>
    <key>WFTextActionText</key>
    <string>Hello world</string>
  </dict>
</dict>
```

Consumer (Show Result, referencing Greeting):

```xml
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
        <string>&#xFFFC;</string>
        <key>attachmentsByRange</key>
        <dict>
          <key>{0, 1}</key>
          <dict>
            <key>Type</key>
            <string>ActionOutput</string>
            <key>OutputName</key>
            <string>Greeting</string>
            <key>OutputUUID</key>
            <string>A7D4F6C2-1B3E-4F5A-9C0D-2E4F6A8B1C3D</string>
            <key>Aggrandizements</key>
            <array/>
          </dict>
        </dict>
      </dict>
      <key>WFSerializationType</key>
      <string>WFTextTokenString</string>
    </dict>
  </dict>
</dict>
```

Rules:

- Producer's `UUID` must match consumer's `OutputUUID` exactly.
- `OutputName` should match `CustomOutputName` (or the action's
  default output name if `CustomOutputName` is absent).
- The object replacement character `U+FFFC` (`&#xFFFC;` in XML)
  occupies the text slot. One char per attachment.
- `attachmentsByRange` keys are strings in `NSStringFromRange` form:
  `"{position, length}"`. Literal curly braces, comma, space, single
  space after opening brace. Position is UTF-16 code unit index.

### 2. Named variables (Set Variable / Get Variable)

Named variables use reverse-DNS actions with string parameters
instead of UUID wiring.

Set:

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

The value stored is the action's *input* — the prior action's output.

Get:

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

Named variables are flat-scoped for the entire shortcut. There is no
block scope. Setting a variable inside an `If` body shadows nothing —
it mutates the shortcut-wide variable.

### 3. Built-in / special variables

These don't need declaration. Reference them via `Type` in the
attachment dict:

| `Type` value     | Meaning                                      |
| ---------------- | -------------------------------------------- |
| `ExtensionInput` | Shortcut Input — the input passed to the    |
|                  | shortcut (from Share Sheet, caller, etc.)   |
| `Clipboard`      | Current clipboard contents                   |
| `CurrentDate`    | `now` date                                   |
| `Ask`            | "Ask Each Time" — prompts the user          |
| `DeviceDetails`  | Device details (name, battery, model, etc.)|

Built-in variable reference example (Shortcut Input):

```xml
<dict>
  <key>Type</key>
  <string>ExtensionInput</string>
  <key>Aggrandizements</key>
  <array/>
</dict>
```

## Serialization types

A parameter value can be a bare literal or a dynamic dict carrying
`WFSerializationType`. Known serialization types:

### `WFTextTokenString`

Inline text with variable interpolation. Value is
`{ string: String, attachmentsByRange: Dict }`. Use when the
parameter accepts text and you need variable substitution.

```xml
<key>Message</key>
<dict>
  <key>Value</key>
  <dict>
    <key>string</key>
    <string>User &#xFFFC; logged in at &#xFFFC;</string>
    <key>attachmentsByRange</key>
    <dict>
      <key>{5, 1}</key>
      <dict>
        <key>Type</key><string>ActionOutput</string>
        <key>OutputName</key><string>Username</string>
        <key>OutputUUID</key><string>UUID-1</string>
        <key>Aggrandizements</key><array/>
      </dict>
      <key>{20, 1}</key>
      <dict>
        <key>Type</key><string>CurrentDate</string>
        <key>Aggrandizements</key><array/>
      </dict>
    </dict>
  </dict>
  <key>WFSerializationType</key>
  <string>WFTextTokenString</string>
</dict>
```

Count positions in UTF-16 units. Each attachment is one `U+FFFC`.

### `WFTextTokenAttachment`

A standalone variable reference (no surrounding text). Value is the
attachment dict itself.

```xml
<key>WFInput</key>
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
```

Used when the parameter accepts exactly one variable and nothing
else (e.g. `WFInput` of Get Dictionary Value).

### `WFDictionaryFieldValue`

A structured dictionary. Value is a dict with key
`WFDictionaryFieldValueItems`, an array of item dicts.

```xml
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
```

`WFItemType` values:

| Value | Type       |
| ----- | ---------- |
| `0`   | Text       |
| `1`   | Dictionary |
| `2`   | Array      |
| `3`   | Number     |
| `4`   | Boolean    |

For nested dictionaries (`WFItemType=1`) and arrays (`WFItemType=2`),
`WFValue` wraps another `WFDictionaryFieldValue` (for nested dict)
or a list dict.

### `WFNumberSubstitutableState`

A numeric parameter that may accept a variable.

```xml
<key>WFRepeatCount</key>
<dict>
  <key>Value</key>
  <dict>
    <key>Type</key>
    <string>Variable</string>
    <key>VariableName</key>
    <string>count</string>
  </dict>
  <key>WFSerializationType</key>
  <string>WFNumberSubstitutableState</string>
</dict>
```

When the value is a literal, this shape is often omitted and the
parameter takes a bare `<integer>` or `<real>`. When the value is a
variable, this wrapper is required.

### `WFArrayParameterState`

Array-valued parameter state. Used by actions that accept ordered
lists of items (e.g. URLs for Get Contents of URL when multiple
URLs). Structure is action-specific; inspect an existing example via
`tools/inspect-shortcut.py` before constructing by hand.

### Other serialization types seen in the wild

- `WFContactFieldValue` — contacts.
- `WFEmailAddressFieldValue` — email address parameters.
- `WFGenericFieldValue` — fallback.

These are action-specific and not safely generable without concrete
examples. When needed, discover via
`references/actions-native-*.md` or `tools/inspect-shortcut.py`.

## Type coercion and aggrandizements

`Aggrandizements` is an array of modifiers applied to a variable
reference. Common uses:

### Coerce to a specific type

```xml
<key>Aggrandizements</key>
<array>
  <dict>
    <key>Type</key>
    <string>WFCoercionVariableAggrandizement</string>
    <key>CoercionItemClass</key>
    <string>WFNumberContentItem</string>
  </dict>
</array>
```

`CoercionItemClass` values include `WFStringContentItem`,
`WFNumberContentItem`, `WFBooleanContentItem`, `WFDateContentItem`,
`WFURLContentItem`, `WFDictionaryContentItem`, `WFImageContentItem`.

### Access a property (Get Details of...)

```xml
<dict>
  <key>Type</key>
  <string>WFPropertyVariableAggrandizement</string>
  <key>PropertyName</key>
  <string>File Size</string>
  <key>PropertyUserInfo</key>
  <integer>0</integer>
</dict>
```

Property names are human-readable strings from the Shortcuts UI
("File Size", "Modification Date", "Creator", etc.).

### Access a dictionary/list element

```xml
<dict>
  <key>Type</key>
  <string>WFDictionaryValueVariableAggrandizement</string>
  <key>DictionaryKey</key>
  <string>name</string>
</dict>
```

Prefer a proper `Get Dictionary Value` action for clarity; the
aggrandizement form is terser but harder to read.

## Types (Shortcuts type system)

Shortcuts has a rough type system that actions declare inputs and
outputs against. Generating plist rarely requires explicit type
annotations — types are inferred from action outputs. When you *do*
need to coerce, use the `Aggrandizements` pattern above.

Known content item classes (same set as
`WFWorkflowInputContentItemClasses`):

`WFStringContentItem`, `WFNumberContentItem`,
`WFBooleanContentItem`, `WFDateContentItem`, `WFURLContentItem`,
`WFDictionaryContentItem`, `WFArrayContentItem`,
`WFImageContentItem`, `WFAVAssetContentItem`, `WFPDFContentItem`,
`WFGenericFileContentItem`, `WFRichTextContentItem`,
`WFContactContentItem`, `WFLocationContentItem`,
`WFPhoneNumberContentItem`, `WFEmailAddressContentItem`,
`WFArticleContentItem`, `WFSafariWebPageContentItem`,
`WFAppStoreAppContentItem`, `WFiTunesProductContentItem`,
`WFDCMapsLinkContentItem`.

## Common binding mistakes

1. **Missing `U+FFFC`** — the attachment has no slot to occupy. The
   rendered text shows the attachment description rather than the
   value.
2. **Wrong range in `attachmentsByRange` key** — off-by-one in
   position or length > 1. Position must be where the FFFC character
   lives; length is always 1.
3. **`OutputUUID` points to a later action** — variables must be set
   before they are read. The producer action must appear at a lower
   index in `WFWorkflowActions`.
4. **`OutputName` stale** — you renamed `CustomOutputName` on the
   producer but forgot the consumer. Names don't need to match
   exactly if UUID matches, but mismatches confuse the UI.
5. **Named variable referenced before set** — unlike magic variables,
   `Get Variable` on an unset name returns empty string silently,
   not an error. Silent bugs ensue.
6. **Variable inside If body "leaks"** — variables are not
   block-scoped. A `Set Variable` in the then-branch is visible
   after the `End If`. Plan accordingly.

## Validation checklist

Before handing off a plist, verify:

- [ ] Every `UUID` referenced by `OutputUUID` exists on a prior
      action.
- [ ] Every `attachmentsByRange` key matches `{N, M}` format, N is
      UTF-16 index, M equals count of FFFC at that position.
- [ ] Every `U+FFFC` in a `string` has a matching entry in
      `attachmentsByRange`.
- [ ] Every `WFSerializationType` value is from the known set.
- [ ] `WFItemType` values (in dictionary fields) are in `{0,1,2,3,4}`.

`tools/validate-shortcut.py` automates all of these.

## Sources

- sebj iOS Shortcuts reference:
  `https://github.com/sebj/iOS-Shortcuts-Reference`
- openclaw shortcuts-skill (modern Shortcuts semantics):
  `https://github.com/openclaw/skills`
- zachary7829 fileformat:
  `https://zachary7829.github.io/blog/shortcuts/fileformat`
