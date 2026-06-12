# Plist format reference

The `.shortcut` file on disk is either a binary plist (modern,
post-iOS 12) or XML plist. This skill generates XML plist; signing
and binary conversion are handled by `shortcuts sign` on macOS.

## XML envelope

Every shortcut starts with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  ...
</dict>
</plist>
```

The root element is a `<dict>`. Its keys are enumerated below.

## Top-level keys

### `WFWorkflowActions` (array of dict)

Required. Ordered list of action dicts. Every dict has two keys,
`WFWorkflowActionIdentifier` (string) and `WFWorkflowActionParameters`
(dict). See `variables-and-types.md` for how actions reference each
other.

### `WFWorkflowClientVersion` (string)

Recommended. Version of the Shortcuts app that created the file.
Modern values look like `"2607.0.3"` or `"2700.0.4"`. When generating
from scratch, use a recent value such as `"2607.0.3"` (Shortcuts on
macOS 14 Sonoma era). The Shortcuts app will overwrite this on
re-save.

### `WFWorkflowClientRelease` (string)

Optional, legacy. Semver of the creating app, e.g. `"1.7.8"`. Not
emitted by recent Shortcuts versions. Omit when generating fresh.

### `WFWorkflowIcon` (dict)

Optional but recommended. Controls the shortcut's tile icon.

```xml
<key>WFWorkflowIcon</key>
<dict>
  <key>WFWorkflowIconGlyphNumber</key>
  <integer>59511</integer>
  <key>WFWorkflowIconStartColor</key>
  <integer>463140863</integer>
</dict>
```

Glyph numbers and colors are in the tables below. A custom image icon
uses `WFWorkflowIconImageData` (Data) instead and takes precedence
over `WFWorkflowIconGlyphNumber`.

### `WFWorkflowImportQuestions` (array of dict)

Optional. Prompts shown to the user during import for values they must
supply. Each dict:

```xml
<dict>
  <key>ActionIndex</key>
  <integer>0</integer>
  <key>Category</key>
  <string>Parameter</string>
  <key>DefaultValue</key>
  <string></string>
  <key>ParameterKey</key>
  <string>WFURL</string>
  <key>Text</key>
  <string>Enter the base URL</string>
</dict>
```

- `ActionIndex` — index into `WFWorkflowActions` for the action whose
  parameter is being filled.
- `Category` — `"Parameter"` for action parameters; `"Variable"` for
  magic variable targets.
- `DefaultValue` — prefilled value. Type depends on parameter.
- `ParameterKey` — the key inside `WFWorkflowActionParameters` to
  populate.
- `Text` — the prompt shown to the user.

Use import questions to turn hardcoded secrets (API tokens, account
IDs) into user-supplied values.

### `WFWorkflowInputContentItemClasses` (array of string)

Required. Which Share Sheet input types this shortcut accepts. Empty
array means "no input". Legal values (17 total):

| Class                              | Meaning                   |
| ---------------------------------- | ------------------------- |
| `WFAppStoreAppContentItem`         | App Store app             |
| `WFArticleContentItem`             | Safari Reader article     |
| `WFContactContentItem`             | Contacts contact          |
| `WFDateContentItem`                | Date                      |
| `WFEmailAddressContentItem`        | Email address             |
| `WFGenericFileContentItem`         | Any file                  |
| `WFImageContentItem`               | Image                     |
| `WFiTunesProductContentItem`       | iTunes product            |
| `WFLocationContentItem`            | Location                  |
| `WFDCMapsLinkContentItem`          | Maps link                 |
| `WFAVAssetContentItem`             | Audio/video asset         |
| `WFPDFContentItem`                 | PDF                       |
| `WFPhoneNumberContentItem`         | Phone number              |
| `WFRichTextContentItem`            | Rich text                 |
| `WFSafariWebPageContentItem`       | Safari webpage            |
| `WFStringContentItem`              | Plain string              |
| `WFURLContentItem`                 | URL                       |

Example:

```xml
<key>WFWorkflowInputContentItemClasses</key>
<array>
  <string>WFURLContentItem</string>
  <string>WFSafariWebPageContentItem</string>
  <string>WFStringContentItem</string>
</array>
```

### `WFWorkflowOutputContentItemClasses` (array of string)

Optional. Same universe as input classes. Rarely populated in
real-world shortcuts; Shortcuts infers output from the last action.

### `WFWorkflowTypes` (array of string)

Optional. Which contexts this shortcut appears in. Legal values:

| Value             | Context                                       |
| ----------------- | --------------------------------------------- |
| `MenuBar`         | macOS menu bar Shortcut                       |
| `QuickActions`    | macOS Finder / Services quick action          |
| `ActionExtension` | iOS/macOS Share Sheet                         |
| `NCWidget`        | iOS Today widget (legacy)                     |
| `Sleep`           | Sleep Focus                                   |
| `Watch`           | Apple Watch                                   |
| `WatchKit`        | Apple Watch (legacy)                          |

Empty array means "run from app / manual trigger only".

### `WFWorkflowHasShortcutInputVariables` (bool)

Optional. `true` when the shortcut body references `Shortcut Input`
(the magic variable representing the shortcut's input). Set when you
wire any action's parameter back to `ExtensionInput`. Shortcuts.app
fixes this on re-save.

### `WFWorkflowHasOutputFallback` (bool)

Optional. Used for Share Sheet shortcuts that provide a default
behavior when no input is given. ⚠ full semantics not publicly
documented; treat as opaque — set `true` only if mirroring a known
template.

### `WFWorkflowMinimumClientVersion` (integer)

Recommended. The minimum Shortcuts app build required to run this
shortcut. Importing on an older build triggers "Shortcut Format Too
New".

⚠ **There is no publicly verified table mapping these build numbers
to iOS/macOS versions.** The value is an opaque Shortcuts build
number. Community-observed safe defaults:

| Value  | Notes                                             |
| ------ | ------------------------------------------------- |
| `411`  | Pre-iOS 13 era (sebj example)                     |
| `700`  | iOS 13 era (sebj example)                         |
| `900`  | Post iOS 15 default, widely used                  |

Default to `900` unless you know a specific action demands newer.
Shortcuts auto-raises this on save when you use a newer action, so an
underestimate is harmless at generation time.

### `WFWorkflowMinimumClientVersionString` (string)

Recommended. String mirror of `WFWorkflowMinimumClientVersion`, same
numeric value. Modern Shortcuts writes both.

### `WFWorkflowName` (string)

Optional. Display name. Falls back to filename stem if absent. Best
practice: omit and let the filename dictate, unless the user wants a
name that differs from the file.

## Action dict anatomy

Every entry in `WFWorkflowActions`:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextActionText</key>
    <string>Hello</string>
    <key>UUID</key>
    <string>A7D4F6C2-1B3E-4F5A-9C0D-2E4F6A8B1C3D</string>
    <key>CustomOutputName</key>
    <string>Greeting</string>
  </dict>
</dict>
```

- `WFWorkflowActionIdentifier` (string) — reverse-DNS action ID.
  Native actions: `is.workflow.actions.*`. Third-party: app bundle ID
  plus action suffix.
- `WFWorkflowActionParameters` (dict) — action-specific parameters.
  Keys vary per action; see `actions-native-*.md`.

Two optional but commonly used parameter keys exist on every action:

- `UUID` (string) — a per-action UUIDv4. Required on any action whose
  output is referenced by a downstream magic variable (see
  `variables-and-types.md`). Safe default: assign a UUID to every
  output-producing action.
- `CustomOutputName` (string) — user-visible name for the action's
  output, shown in the magic variable picker.

Control flow actions (`conditional`, `repeat.count`, `repeat.each`,
`choosefrommenu`) use a different UUID key, `GroupingIdentifier`. See
`control-flow.md`.

## Parameter value shapes

A parameter value is one of:

- A bare string, integer, boolean, or array — used when the parameter
  accepts a constant only.
- A dict with `WFSerializationType` — used when the parameter can
  accept a dynamic value (variable, inline text with variable
  interpolation, structured dictionary, etc.).

Example of a bare parameter:

```xml
<key>WFTextActionText</key>
<string>literal string</string>
```

Example of a dynamic parameter carrying an inline text with
interpolation:

```xml
<key>WFTextActionText</key>
<dict>
  <key>Value</key>
  <dict>
    <key>string</key>
    <string>The answer is &#xFFFC;</string>
    <key>attachmentsByRange</key>
    <dict>
      <key>{15, 1}</key>
      <dict>
        <key>Type</key>
        <string>ActionOutput</string>
        <key>OutputName</key>
        <string>Answer</string>
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
```

See `variables-and-types.md` for the full catalog of
`WFSerializationType` values and attachment types.

## Glyph numbers (selection)

Full authoritative list: the Cherri project's `glyphs.go`
(`https://github.com/electrikmilk/cherri/blob/main/glyphs.go`). Common
entries:

| Glyph name       | Number | Glyph name      | Number |
| ---------------- | ------ | --------------- | ------ |
| airplane         | 59648  | alarmClock      | 59649  |
| ambulance        | 59652  | bike            | 59668  |
| binoculars       | 59669  | bookmark        | 59670  |
| briefcase        | 59676  | buildings       | 59677  |
| bus              | 59678  | busDouble       | 61448  |
| calendar         | 59681  | camera          | 59682  |
| car              | 59452  | carMultiple     | 61446  |
| chatBubble       | 59414  | church          | 59688  |
| clipboard        | 59711  | clock           | 59712  |
| cloud            | 59714  | compass         | 59717  |
| creditCard       | 59719  | document        | 59725  |
| dollarSign       | 59395  | downloadArrow   | 59693  |
| electricCar      | 61447  | envelope        | 59773  |
| envelopeOpen     | 59774  | filmstrip       | 59733  |
| fire             | 59734  | flag            | 59736  |
| flower           | 59468  | folder          | 59737  |
| footprints       | 59738  | fuelstation     | 59741  |
| gear             | 59743  | globe           | 59412  |
| groceryStore     | 59747  | handbag         | 59750  |
| heart            | 59754  | hourglass       | 59757  |
| house            | 59755  | key             | 59760  |
| lightbulb        | 59763  | lock            | 59770  |
| magnifyingGlass  | 59772  | messageBubbles  | 59403  |
| microphone       | 59780  | moon            | 59782  |
| moonCircle       | 61517  | motorcycle      | 59783  |
| mountain         | 59785  | movieCamera     | 59402  |
| paintbrush       | 59793  | paperAirplane   | 59836  |
| pencil           | 59798  | person          | 59801  |
| phone            | 59814  | picture         | 59784  |
| pineTree         | 59731  | raincloud       | 59715  |
| sailboat         | 59823  | settings        | 62242  |
| shield           | 62501  | shoppingCart    | 59828  |
| signs            | 59724  | sliders         | 59833  |
| snowflake        | 59835  | star            | 59841  |
| stopwatch        | 59844  | sun             | 59845  |
| tag              | 59848  | textBubble      | 59779  |
| thermometer      | 59854  | tools           | 59749  |
| trashcan         | 59859  | trophy          | 59860  |
| umbrella         | 59861  | uploadArrow     | 59708  |
| utensils         | 59863  | videoIcon       | 59864  |
| wifi             | 59867  | wrench          | 59870  |

Default glyph when unsure: `59511` (the "bolt/sparkle" Shortcuts
default), or pick something semantically matching the shortcut's
purpose.

## Color values

Shortcuts packs the icon start color as RGBA-8 in a 32-bit integer.
Stored as unsigned decimal in plist XML (even though the internal
representation is signed in some Apple code paths).

| Label       | RGBA hex       | Decimal (unsigned) |
| ----------- | -------------- | ------------------ |
| Red         | `0xFF4351FF`   | `4282601983`       |
| Dark orange | `0xFD6631FF`   | `4251333119`       |
| Orange      | `0xFE9949FF`   | `4271458815`       |
| Yellow      | `0xFEC418FF`   | `4274264319`       |
| Yellow-green| `0xFFD426FF`   | `4292093695`       |
| Green       | `0x19BD03FF`   | `431817727`        |
| Light blue  | `0x55DAE1FF`   | `1440408063`       |
| Blue        | `0x1B9AF7FF`   | `463140863`        |
| Dark blue   | `0x3871DEFF`   | `946986751`        |
| Violet      | `0x7B72E9FF`   | `2071128575`       |
| Purple      | `0xDB49D8FF`   | `3679049983`       |
| Pink        | `0xED4694FF`   | `3980825855`       |
| Taupe       | `0xB4B2A9FF`   | `3031607807`       |
| Gray        | `0xA9A9A9FF`   | `2846468607`       |
| Black       | `0x000000FF`   | `255`              |

Note: Apple UI labels drift between Shortcuts versions ("Indigo",
"Brown"). The integers are stable; the labels are not. When in doubt,
match the RGBA intent rather than the label.

## Validation rules (enforced by `validate-shortcut.py`)

A well-formed plist passes all of these:

1. Root is a `<plist>` with exactly one child `<dict>`.
2. `WFWorkflowActions` is present and is an `<array>`.
3. Every `WFWorkflowActions` element is a `<dict>` with exactly two
   keys: `WFWorkflowActionIdentifier` (string) and
   `WFWorkflowActionParameters` (dict).
4. `WFWorkflowInputContentItemClasses` is present (possibly empty)
   and all values are legal content item class names.
5. `WFWorkflowTypes` values, if present, are in the legal set.
6. Every `GroupingIdentifier` appears an even number of times
   (start + end) — or even + one middle for `conditional` with
   `Otherwise`, or N middles for `choosefrommenu`.
7. Every `OutputUUID` in `attachmentsByRange` matches a `UUID` on an
   earlier action in `WFWorkflowActions`.
8. `plutil -lint` passes (valid XML plist syntax).

## Sources

- sebj iOS Shortcuts reference:
  `https://github.com/sebj/iOS-Shortcuts-Reference`
- zachary7829 fileformat:
  `https://zachary7829.github.io/blog/shortcuts/fileformat`
- Cherri file-format docs: `https://cherrilang.org/compiler/file-format.html`
- Cherri glyphs: `https://github.com/electrikmilk/cherri/blob/main/glyphs.go`
