---
name: apple-shortcuts
description: |
  Generate importable Apple Shortcuts (.shortcut / plist XML) for macOS
  and iOS. Use this skill whenever the user wants to create, modify,
  reverse-engineer, or understand Apple Shortcuts, including native
  actions, third-party app integrations (Actions, Data Jar, Toolbox
  Pro, Scriptable, a-Shell, Jayson, Pushcut), automations, and complex
  control flow. Trigger on mentions of "shortcut", "raccourci",
  "workflow iOS/macOS", ".shortcut file", "Apple automation", or any
  request to produce a file the user can import into the Shortcuts app.
metadata:
  version: "1.0.0"
---

# Apple Shortcuts

Generate plist XML that the Shortcuts app imports. Targets macOS 12+
and iOS 15+. Use this skill for creation, modification, reverse
engineering, and reference lookups.

## Critical upfront fact: signing

Since iOS 15 / macOS 12, **Shortcuts refuses unsigned files**. This
skill produces plist XML. Delivery to the user requires one of:

1. **macOS 12+**: run `shortcuts sign -i in.plist -o out.shortcut -m
   anyone` to produce a distributable `.shortcut`. The user
   double-clicks or runs `open -a Shortcuts out.shortcut`.
2. **macOS, manual route**: open the plist in Shortcuts.app (rename to
   `.shortcut` first), re-save — Shortcuts re-signs it.
3. **iOS, no signing toolchain**: the user must receive a signed
   `.shortcut` via iCloud share link (`https://www.icloud.com/
   shortcuts/...`), AirDrop, or Messages. Unsigned plist XML cannot be
   imported on iOS.

State this cost to the user before generating. If they lack macOS, the
deliverable is XML plus instructions; full binary signing without
macOS is a rabbit hole this skill does not enter.

See `gotchas/signing-and-sharing.md` for the full story.

## Quickstart (three steps)

### 1. Identify the action set

If you know the action by name but not its identifier:

```bash
./tools/find-action-identifier.py "send message"
```

If you need to discover an unknown third-party action on macOS:

```bash
./tools/list-app-intents.py --bundle com.example.app
```

If you need the full native action catalog:

```bash
./tools/list-native-actions.py
```

### 2. Generate the plist

Consult references in this order:

- `references/plist-format.md` for the envelope and top-level keys.
- `references/variables-and-types.md` for magic variable wiring.
- `references/actions-native-*.md` for concrete action schemas.
- `patterns/*.md` if the task matches a known pattern.
- `templates/*.plist` as starting points.

Write the plist as XML. Every action dict must carry at minimum
`WFWorkflowActionIdentifier` and `WFWorkflowActionParameters`.

### 3. Validate and deliver

```bash
./tools/validate-shortcut.py path/to/shortcut.plist
```

Fix any errors. Then either sign on macOS or instruct the user to.

## Progressive disclosure table

Load only the files your current task needs. This table maps request
types to files.

| Request contains                       | Load                                   |
| -------------------------------------- | -------------------------------------- |
| "how do I make a shortcut that..."     | `patterns/` + relevant `actions-*.md`  |
| "what's the identifier for X action"   | `actions-native-full-index.md` or find |
| "why won't my shortcut import"         | `gotchas/signing-and-sharing.md`       |
| "what does this .shortcut file do"     | `tools/inspect-shortcut.py`            |
| "call an API / fetch JSON"             | `patterns/http-api-calls.md`           |
| "show a menu to the user"              | `patterns/user-input.md`               |
| "run another shortcut"                 | `patterns/shortcuts-chaining.md`       |
| "personal automation / trigger"        | `patterns/automation-triggers.md`      |
| "use <third-party app> action"         | `third-party/<app>.md`                 |
| "variables aren't working"             | `references/variables-and-types.md`    |
| "compare two shortcuts"                | `tools/diff-actions.py`                |
| "what actions are in WorkflowKit"      | `tools/list-native-actions.py`         |

## Canonical generation workflow

1. **Detect target platform.** iOS-only, macOS-only, or cross-platform
   shapes the action set. Shell Script, AppleScript, JXA, and window
   management are macOS-only. Health, HomeKit scene execution, and
   camera actions are iOS-only.
2. **Resolve identifiers.** Every action string must be real. If an
   identifier is unverified, mark it `⚠ unverified` in your plan and
   prefer a verified alternative.
3. **Load references.** Pull in only the specific `references/*.md`
   and `third-party/*.md` you need. Do not eagerly load the full
   catalog.
4. **Generate the plist.** Emit the XML envelope, icon dict,
   `WFWorkflowActions` array. Assign a UUID to every action whose
   output is referenced later. Wire magic variables via
   `attachmentsByRange` using `{position, length}` strings and the
   `U+FFFC` object replacement character (see
   `references/variables-and-types.md`).
5. **Validate.** Run `tools/validate-shortcut.py`. Do not skip this
   step.
6. **Deliver with import instructions.** Provide the three import
   paths (macOS CLI, macOS GUI, iOS), noting the signing requirement
   explicitly.

## Minimum viable plist shape

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>WFWorkflowClientVersion</key>
  <string>2607.0.3</string>
  <key>WFWorkflowMinimumClientVersion</key>
  <integer>900</integer>
  <key>WFWorkflowMinimumClientVersionString</key>
  <string>900</string>
  <key>WFWorkflowIcon</key>
  <dict>
    <key>WFWorkflowIconGlyphNumber</key>
    <integer>59511</integer>
    <key>WFWorkflowIconStartColor</key>
    <integer>463140863</integer>
  </dict>
  <key>WFWorkflowImportQuestions</key>
  <array/>
  <key>WFWorkflowInputContentItemClasses</key>
  <array>
    <string>WFStringContentItem</string>
  </array>
  <key>WFWorkflowTypes</key>
  <array/>
  <key>WFWorkflowActions</key>
  <array>
    <dict>
      <key>WFWorkflowActionIdentifier</key>
      <string>is.workflow.actions.gettext</string>
      <key>WFWorkflowActionParameters</key>
      <dict>
        <key>WFTextActionText</key>
        <string>Hello from Claude</string>
      </dict>
    </dict>
    <dict>
      <key>WFWorkflowActionIdentifier</key>
      <string>is.workflow.actions.showresult</string>
      <key>WFWorkflowActionParameters</key>
      <dict>
        <key>Text</key>
        <string>Hello from Claude</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
```

This is `templates/minimal-shortcut.plist`. It imports after signing.

## Import methods (three paths)

### macOS, CLI (requires macOS 12+)

```bash
# Save plist with .shortcut extension
mv out.plist out.shortcut

# Sign it for public sharing
shortcuts sign -i out.shortcut -o out.signed.shortcut -m anyone

# Open in Shortcuts.app to complete import
open -a Shortcuts out.signed.shortcut
```

Signing modes:

- `anyone` — distributable via any channel; lax trust.
- `people-who-know-me` — requires recipient to be in Contacts.

### macOS, drag and drop

```bash
mv out.plist out.shortcut
open -a Shortcuts out.shortcut
```

Shortcuts.app imports, signs locally, and stores in
`~/Library/Shortcuts/`.

### iOS, iCloud / AirDrop

There is no iOS signing toolchain. The user must receive a shortcut
that was signed on macOS. Paths:

- iCloud share link — sign on macOS, upload to iCloud, share the
  `https://www.icloud.com/shortcuts/<uuid>` link. Recipient taps link,
  Shortcuts opens.
- AirDrop a signed `.shortcut` file from macOS to iOS.
- Email / Messages attachment of a signed `.shortcut` file.

If the user is iOS-only and has no macOS device, the skill cannot
fully close the loop. Deliver the plist XML and document the gap.

## Reference files inventory

- `references/plist-format.md` — envelope, top-level keys, content item
  classes, XML rules.
- `references/variables-and-types.md` — magic variables,
  `attachmentsByRange`, serialization types, coercion.
- `references/control-flow.md` — If, Repeat, Choose from Menu,
  `GroupingIdentifier`, `WFControlFlowMode`.
- `references/actions-native-core.md` — Text, Dictionary, List,
  Variables, Scripting, Device.
- `references/actions-native-web.md` — URL, Get Contents of URL, JSON
  parsing, headers, authentication.
- `references/actions-native-files.md` — Files, Photos, Documents,
  archive, hash.
- `references/actions-native-communication.md` — Messages, Mail,
  Notifications, Speak Text.
- `references/actions-native-automation.md` — Automations, triggers,
  focus, personal vs home.
- `references/actions-native-full-index.md` — Flat identifier index,
  fallback lookup.

## Third-party catalog

- `third-party/actions-app.md` — Sindre Sorhus's Actions (OSS, free,
  covers ~80% of gaps).
- `third-party/data-jar.md` — Simon Støvring's persistent key-value
  store.
- `third-party/toolbox-pro.md` — Alex Hay's advanced utilities.
- `third-party/scriptable.md` — JavaScript bridge.
- `third-party/a-shell.md` — iOS shell bridge.
- `third-party/jayson.md` — JSON manipulation.
- `third-party/pushcut.md` — Automation server, webhooks.
- `third-party/discovery-pattern.md` — Reverse engineer any unknown
  third-party app's actions.

## Patterns

- `patterns/http-api-calls.md` — REST calls, auth headers, pagination.
- `patterns/json-parsing.md` — Dictionary access, Get Dictionary Value.
- `patterns/error-handling.md` — Exit, fallback, validation.
- `patterns/user-input.md` — Ask, Choose from Menu, Show Alert.
- `patterns/shortcuts-chaining.md` — Run Shortcut with parameters,
  output passing.
- `patterns/automation-triggers.md` — Personal automation, Home,
  limits, confirmation.

## Gotchas

- `gotchas/platform-differences.md` — iOS vs macOS vs watchOS action
  availability.
- `gotchas/signing-and-sharing.md` — iOS 15+ signing requirement, share
  links, trust prompts.
- `gotchas/common-pitfalls.md` — Variable scope, UUID duplicates,
  magic variable binding bugs.
- `gotchas/performance.md` — Action limits, timeouts, Get Contents of
  URL failure modes.

## Tools

- `tools/validate-shortcut.py` — Validate a plist. Check syntax,
  required keys, identifier existence, variable referencing.
- `tools/inspect-shortcut.py` — Dump a `.shortcut` or `.plist` as
  structured JSON or human-readable list.
- `tools/list-native-actions.py` — Extract `WFWorkflowActionIdentifier`
  values from WorkflowKit.framework (macOS) or fall back to embedded
  index.
- `tools/list-app-intents.py` — Scan installed apps for App Intents
  metadata and enumerate their Shortcuts actions.
- `tools/find-action-identifier.py` — Fuzzy search for an action by
  name across native and known third-party catalogs.
- `tools/diff-actions.py` — Semantic diff between two shortcuts
  (action-by-action, reorder-aware).
- `tools/README.md` — Script inventory, usage examples, exit codes.

## Hard rules

- **No invention.** If an identifier, parameter key, or version number
  is not verified, mark it `⚠ unverified` in output and suggest the
  user confirm via `tools/list-native-actions.py` or by round-tripping
  through Shortcuts.app.
- **One source of truth per fact.** Identifier strings live in
  `actions-native-full-index.md` and `third-party/*.md`; prose
  references link there rather than re-state.
- **Templates are importable.** Every file in `templates/` passes
  `plutil -lint` and `tools/validate-shortcut.py`.
- **English-only in code and documentation.** User-facing prose in
  chat may be in the user's language; files in this skill are English.

## When the request is ambiguous

Before generating, resolve:

1. Target platform — iOS only, macOS only, or both.
2. Trigger — manual run, share sheet, personal automation, Home
   automation, menu bar (macOS).
3. Input — no input, Shortcut Input, explicit prompt (Ask for Input).
4. Output — none, Show Result, Quick Look, return to caller.
5. Third-party dependencies — any action outside
   `is.workflow.actions.*`?

Do not guess. Ask the user for any of the five that remain unclear
after reading the request.
