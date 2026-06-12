# Gotcha: Signing and sharing

### Unsigned .shortcut files fail to import on iOS 15+ / macOS 12+

**Symptom**: Double-tapping the file on iOS shows "Couldn't add
shortcut". On macOS, `open -a Shortcuts file.shortcut` opens
Shortcuts.app with an error banner.

**Cause**: Apple introduced CMS-signed `.shortcut` format with iOS
15. Unsigned payloads — including pure XML plist renamed to
`.shortcut` — are rejected by the import pipeline.

**Fix**: On macOS 12+, sign before distributing:

```bash
shortcuts sign -i unsigned.plist -o signed.shortcut -m anyone
```

`-m anyone` (public) or `-m people-who-know-me` (Contacts-only).
There is no known way to sign on iOS.

### No CLI to import on macOS

**Symptom**: `shortcuts import file.shortcut` fails — no such
subcommand.

**Cause**: The `shortcuts` CLI (macOS 12+) never had an import
subcommand. Running `shortcuts import …` errors with "Unknown
option".

**Fix**: Import via the GUI:

```bash
open -a Shortcuts signed.shortcut
```

Shortcuts.app shows the import dialog. No headless import.

### "Allow Untrusted Shortcuts" toggle is gone on iOS 15+

**Symptom**: User asks "where do I enable untrusted shortcuts on
iOS 16?". Not in Settings → Shortcuts.

**Cause**: Apple removed the toggle in iOS 15. The signing model
replaced it. Unsigned shortcuts aren't a separate trust tier — they
simply don't import.

**Fix**: Sign the shortcut. There is no user-toggleable escape
hatch on iOS 15+. iOS 13–14 devices still have the old toggle at
Settings → Shortcuts → Allow Untrusted Shortcuts.

### Share via iCloud Drive link

**Symptom**: "How do I send this to someone remotely?"

**Fix**: Use the iCloud share flow:

1. On macOS, sign the shortcut with `-m anyone`.
2. In Shortcuts.app, right-click your shortcut → Share → Copy
   iCloud Link.
3. Shortcuts uploads to iCloud and returns a URL of the form
   `https://www.icloud.com/shortcuts/<uuid>`.
4. Send the URL. Recipient taps → Shortcuts.app opens → Add
   Shortcut.

Recipients on iOS 15+ do NOT need "Allow Untrusted"; the iCloud
share flow is the sanctioned path.

### Signing modes — anyone vs people-who-know-me

**Symptom**: A shortcut signed with `people-who-know-me` imports
fine for the author but not for others.

**Cause**: `people-who-know-me` mode requires the recipient's
Contacts to include the signer. The signer is embedded as an Apple
ID.

**Fix**: Re-sign with `-m anyone` for public sharing.

### Plist XML vs binary plist

**Symptom**: Generated XML plist "works" until you try to sign or
run it on newer OS.

**Cause**: `shortcuts sign` accepts XML plist as input and produces
a signed binary `.shortcut`. Importing a non-signed binary plist
or XML plist renamed to `.shortcut` on modern OS fails.

**Fix**: Always sign on macOS. Treat "XML plist + signing" as the
canonical delivery pipeline for modern OS.

### No signing on iOS

**Symptom**: User has no Mac. Wants to build and share shortcuts.

**Fix paths**:

1. **Best**: Find a macOS-owning collaborator. They run
   `shortcuts sign`.
2. **TestFlight / open-source signing tool**:
   `https://github.com/0xilis/shortcut-sign` claims cross-platform
   (Linux + macOS) signing via reverse-engineered Apple CMS. ⚠ Not
   Apple-sanctioned; use at own risk.
3. **Cloud macOS rental**: MacinCloud / Scaleway Apple Silicon /
   GitHub Actions macOS runners. Sign there.

This skill does not implement signing. We ship XML plist + clear
instructions. If the user cannot reach a signing environment, be
honest about the gap.

### iCloud sync delay

**Symptom**: A shortcut imported on Mac doesn't appear on iPhone.

**Cause**: iCloud sync of Shortcuts is eventual, not synchronous.
Latency varies from seconds to minutes.

**Fix**: Wait a few minutes. Force iCloud refresh by toggling
Shortcuts in Settings → iCloud → Show All → Shortcuts. If still
missing, the signed file must be AirDropped / emailed directly.

### Shortcut breaks when called from another shortcut after update

**Symptom**: `Run Shortcut "Foo"` fails silently after updating the
called shortcut.

**Cause**: The called shortcut's display name or internal UUID
changed. Run Shortcut matches by display name only.

**Fix**: Keep display names stable when updating. Rename
intentionally, not incidentally.

### Custom icons don't persist through iCloud share

**Symptom**: `WFWorkflowIconImageData` icon is intact locally but
reverts to a glyph when the recipient imports from iCloud.

**Cause**: ⚠ Not fully documented. Community reports indicate
iCloud share strips custom image data in some cases; glyph +
color survive.

**Fix**: Prefer glyph-based icons (`WFWorkflowIconGlyphNumber` +
`WFWorkflowIconStartColor`) for shortcuts destined for sharing.
