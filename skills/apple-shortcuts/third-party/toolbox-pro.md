# Toolbox Pro

_Last verified: 2026-04-19_

Advanced utility actions that fill gaps in native Shortcuts. Not
free, but excellent.

- **App Store**: `https://apps.apple.com/app/toolbox-pro-for-shortcuts/
  id1476205977`
- **Developer**: Alex Hay (tinyrobot).
- **Bundle ID**: `com.tinyrobot.ToolboxPro` ⚠ widely reported;
  verify via round-trip.
- **Price**: Free tier + Premium IAP (~€10 one-time).
- **Platforms**: iOS, iPadOS.

## Action catalog (selected)

| Action                       | Purpose                               |
| ---------------------------- | ------------------------------------- |
| Present Menu                 | Rich menus with icons and detail text |
| Present Text Field           | Full-screen text input with keyboard  |
|                              | options                               |
| Present Alert                | More-customizable alerts than native  |
| Send HTTP Request            | HTTP with more options than native    |
| Write Text to File           | Direct file writing                   |
| Store Variable (Premium)     | Persistent storage                    |
| Retrieve Variable (Premium)  | Persistent read                       |
| Get Stored Text              | Pre-saved snippets                    |
| Haptic Feedback              | Fine-grained iOS haptics              |
| Change Audio Output          | Route audio programmatically          |
| Sort Files                   | By date, size, name                   |
| Get Colors from Image        | Dominant colors extraction            |
| Rotate Image                 | Rotate by degrees                     |
| Save to iCloud               | Write to iCloud-managed folders       |
| Copy to iCloud Drive         | File copy into Drive                  |
| Extract Text from Image (OCR)| OCR via Vision framework              |
| Detect Faces in Image        | Vision face count / boxes             |
| Translate Text (Premium)     | Machine translation                   |
| Regular Expression           | Full regex with named groups          |
| Format JSON                  | Pretty-print with indent options      |
| Generate QR Code             | With color / logo options             |

## Strengths over native

- **Present Menu**: native `Choose from Menu` is control flow;
  Toolbox Pro's presents a richer UI *without* being control flow,
  returning the selection as a value.
- **Send HTTP Request**: lets you read the response status code as a
  dedicated value — something native `Get Contents of URL` hides.
- **Store Variable**: similar to Data Jar; Toolbox Pro's is local-only
  by default.

## Identifier pattern

⚠ Intent identifiers not publicly documented. Discover via:

```bash
./tools/list-app-intents.py --bundle com.tinyrobot.ToolboxPro
```

## Gotchas

- Many rich actions are Premium-only; a shortcut distributed to a
  user without Premium fails at those actions with a "requires
  upgrade" error.
- Toolbox Pro has been receiving slower updates than Actions app
  (Sorhus). For OSS-only environments, prefer Actions.
- OCR / Vision actions are iOS-only; shortcuts using them break on
  macOS.

## When to reach for it

- Rich interactive menus without control flow gymnastics.
- HTTP with visible status code.
- OCR / face detection without writing JavaScript.
- Programmatic audio routing.

For everything else, try native or Actions (Sorhus) first.
