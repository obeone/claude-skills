# Files, photos, media actions

Reading, writing, archiving, hashing, and media operations.

## Files and documents

### Get File (`documentpicker.open`)

⚠ identifier unverified; widely seen. Presents a document picker.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.documentpicker.open</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFShowFilePicker</key>
    <true/>
    <key>WFFileType</key>
    <string>public.text</string>
  </dict>
</dict>
```

`WFFileType` is a UTType identifier. Common values:

| UTType                    | Meaning                |
| ------------------------- | ---------------------- |
| `public.text`             | Any text file          |
| `public.plain-text`       | Plain text             |
| `public.image`            | Any image              |
| `public.json`             | JSON                   |
| `com.adobe.pdf`           | PDF                    |
| `public.audio`            | Audio                  |
| `public.movie`            | Video                  |
| `public.zip-archive`      | ZIP                    |
| `public.folder`           | Folder                 |

### Save File (`documentpicker.save`)

⚠ identifier unverified; widely seen.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.documentpicker.save</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAskWhereToSave</key>
    <false/>
    <key>WFFileDestinationPath</key>
    <string>/Shortcuts/output/</string>
    <key>WFFileName</key>
    <string>result.txt</string>
    <key>WFOverwriteFile</key>
    <true/>
  </dict>
</dict>
```

Input is the file content to save. `WFFileDestinationPath` is
relative to iCloud Drive's `Shortcuts/` folder by default (iOS +
macOS).

### Append to File

**Identifier**: ⚠ unverified.

Round-trip an example from Shortcuts.app (see
`third-party/discovery-pattern.md`).

### Make Folder

**Identifier**: ⚠ unverified (likely `is.workflow.actions.file.createfolder`).

Same caveat.

### Get Link to File (`file.getlink`)

Returns a file:// URL for a file.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.file.getlink</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

## Archives

### Make Archive (`makezip`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.makezip</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFArchiveFormat</key>
    <string>Zip</string>
    <key>WFZIPName</key>
    <string>archive.zip</string>
  </dict>
</dict>
```

`WFArchiveFormat` values: `Zip`, `Tar`, `iOS App Archive`, `Gzip`,
`Cpio`, `Bzip2`, `Tar Gzip`, `Tar Bzip2`, `Tar Xz`. Availability
varies per OS version.

Input: one or more files.

### Extract Archive (`unzip`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.unzip</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: archive file. Output: list of extracted files.

## Encoding

### Base64 Encode (`base64encode`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.base64encode</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFEncodeMode</key>
    <string>Encode</string>
  </dict>
</dict>
```

`WFEncodeMode` values: `Encode`, `Decode`.

### Hash (`hash`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.hash</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFHashType</key>
    <string>SHA-256</string>
  </dict>
</dict>
```

`WFHashType` values: `MD5`, `SHA-1`, `SHA-256`, `SHA-512`.

## Photos

### Take Photo

**Identifier**: ⚠ unverified (likely `is.workflow.actions.takephoto`).
iOS only.

### Get Latest Photos (`getlastphoto`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getlastphoto</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFGetLatestPhotoCount</key>
    <integer>1</integer>
    <key>WFGetLatestPhotosActionIncludeScreenshots</key>
    <false/>
  </dict>
</dict>
```

### Get Latest Screenshot (`getlastscreenshot`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getlastscreenshot</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

### Get Latest Video (`getlastvideo`)

Same shape as Get Latest Photos.

### Get Latest Bursts (`getlatestbursts`)

### Get Latest Live Photos (`getlatestlivephotos`)

### Delete Photos (`deletephotos`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.deletephotos</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: photo(s). Prompts user on iOS.

## Images

### Get Image from Input (`detect.images`)

Pulls images out of mixed input.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.detect.images</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

### Get Frames from Image (`getframesfromimage`)

For animated GIFs / Live Photos.

### Resize Image

**Identifier**: ⚠ unverified; commonly seen as
`is.workflow.actions.image.resize`. Round-trip.

### Edit Image (`avairyeditphoto`)

Legacy Aviary integration. Presents an image editor.

### Scan QR/Barcode (`scanbarcode`)

iOS only. Opens camera.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.scanbarcode</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Output: Text (the decoded content).

## Video and audio

### Trim Media (`trimvideo`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.trimvideo</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Presents a trim UI. Input: video. Output: trimmed video.

### Play Sound (`playsound`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.playsound</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: audio file.

### Encode Media

**Identifier**: ⚠ unverified; seen as
`is.workflow.actions.encodemedia`. Transcodes.

### Get Current Song (`getcurrentsong`)

Returns metadata of currently-playing Apple Music track.

### Play/Pause (`pausemusic`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.pausemusic</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFPlayPauseBehavior</key>
    <string>Toggle</string>
  </dict>
</dict>
```

`WFPlayPauseBehavior` values: `Play`, `Pause`, `Toggle`.

### Skip Forward / Back (`skipforward`, `skipback`)

### Clear Up Next (`clearupnext`)

## Preview

### Quick Look (`previewdocument`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.previewdocument</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: file. Displays the system Quick Look preview.

### View Result (`viewresult`)

Similar to Quick Look but for the shortcut's own data types.

## Print

### Print (`print`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.print</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

iOS: AirPrint UI. macOS: system print dialog.

## iCloud Drive

Most iCloud operations run through the `documentpicker.*` path with
paths relative to `Shortcuts/` by default. Full filesystem access on
iOS requires the Files app picker.

## Common gotchas

- **Path encoding**: `WFFileDestinationPath` uses forward slashes on
  both platforms. Trailing slash optional.
- **Overwrite semantics**: default is to prompt. Set
  `WFOverwriteFile=true` for silent overwrite.
- **File types are UTType strings**, not extensions. `public.text`
  not `.txt`.
- **Get File's document picker blocks execution**; a non-interactive
  shortcut (e.g. personal automation) can't reliably invoke it.
- **Photos actions require photo library permission**. First run on
  iOS prompts.

## Sources

- joshfarrant/shortcuts-js:
  `https://github.com/joshfarrant/shortcuts-js`
- Apple UTType reference:
  `https://developer.apple.com/documentation/uniformtypeidentifiers`
