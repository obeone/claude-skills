# Reverse-engineering an unknown third-party app

When the user wants to use an action from an app this skill doesn't
document, follow this protocol.

## Goal

Determine the literal `WFWorkflowActionIdentifier` string and the
parameter key layout for an unknown action.

## Prerequisite

macOS access. iOS-only users cannot run this procedure; they must
have a macOS-owning friend or use an iOS shortcut that performs the
action once, then sync it to iCloud for later inspection.

## Procedure A — round-trip via Shortcuts app (most reliable)

1. Install the target app on macOS.
2. Open Shortcuts.app. Create a new shortcut containing only the
   action you want to document.
3. Fill in the action's parameters with **distinctive sentinel
   values** you'll recognize in the dump (e.g.
   `__USER__=alice_sentinel__`, `__KEY__=sentinel_key_xyz`).
4. Save the shortcut with a known name.
5. Export on CLI:

   ```bash
   shortcuts export "<Your Shortcut Name>" \
     --output-path /tmp/discovery.shortcut
   ```

6. Convert to XML plist:

   ```bash
   plutil -convert xml1 /tmp/discovery.shortcut -o /tmp/discovery.xml
   ```

7. Inspect:

   ```bash
   ./tools/inspect-shortcut.py /tmp/discovery.shortcut
   ```

   Or manually:

   ```bash
   grep -A 20 WFWorkflowActionIdentifier /tmp/discovery.xml
   ```

Look for the identifier string (not `is.workflow.actions.*`) and the
parameter dictionary. Find your sentinels — the keys wrapping them
are the parameter names you need.

## Procedure B — App Intents metadata (no round-trip)

If you want the full action catalog of an app without creating one
shortcut per action:

```bash
./tools/list-app-intents.py --bundle <bundle-id>
```

This reads:

```text
/Applications/<AppName>.app/Contents/Resources/Metadata.appintents/extract.actionsdata
```

On iOS, the same file lives inside the app bundle under
`Metadata.appintents/`, but there's no standard way to read iOS app
bundles without jailbreak.

Output includes intent names, parameter names, parameter types, enum
cases, and defaults. This is **the** authoritative source — it's
Apple's own build-time extraction.

⚠ `extract.actionsdata` is a Foundation-encoded binary plist. Some
apps' files are non-trivial to parse. `list-app-intents.py` does
best-effort extraction and reports `parseable: false` when a file
resists.

## Procedure C — inspect WorkflowKit directly

For native actions (when the flat index doesn't cover what you need):

```bash
./tools/list-native-actions.py
```

Parses WorkflowKit.framework's App Intents metadata (macOS 12+) to
produce a full native catalog.

On older macOS or when WorkflowKit doesn't expose a clean bundle,
the tool falls back to its embedded index (from
`actions-native-full-index.md`).

## What to record

When you find an action, add to notes:

- Literal `WFWorkflowActionIdentifier`.
- Parameter key → type → sample value mapping.
- Any `WFSerializationType` wrappers observed.
- Platform availability (you'll infer from the app itself).

If you're updating the skill: propose an edit to the relevant
`third-party/*.md` or `actions-native-*.md` with the verified
identifier and a minimal plist example.

## Ethical note

App developers generally accept reverse-engineering their public
App Intents for Shortcuts use — that's what they're published for.
Do not redistribute entire paid apps' intent catalogs verbatim
without attribution.

## When rediscovery fails

Some apps use custom intent classes that don't fit the standard App
Intents bucket (older apps using legacy Intents framework / Siri
shortcuts). Those show up as `WFWorkflowActionIdentifier` values
that are opaque GUIDs or legacy strings. In that case:

1. Round-trip via Procedure A is the only way.
2. Document the finding with a `⚠ legacy intent, may change between
   app versions` note.
