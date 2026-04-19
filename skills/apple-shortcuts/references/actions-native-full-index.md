# Native actions — full identifier index

Flat index. Every row is an `is.workflow.actions.*` identifier.
Prefix assumed — don't repeat `is.workflow.actions.` in every row.

Legend for **Documented?**:

- ✅ — covered in detail in `actions-native-*.md`.
- `idx` — listed here only (signatures not expanded in reference
  files; round-trip or inspect a real shortcut to confirm parameter
  keys).
- ⚠ — identifier plausible but unverified against a primary source.

Use this as a fallback lookup and as input to
`tools/find-action-identifier.py`.

## Data / content

| Identifier        | Human name                | Category      | Documented? |
| ----------------- | ------------------------- | ------------- | ----------- |
| `gettext`         | Text                      | content       | ✅          |
| `text`            | Text (legacy alias)       | content       | idx         |
| `url`             | URL                       | content       | ✅          |
| `dictionary`      | Dictionary                | content       | ✅          |
| `list`            | List                      | content       | ✅          |
| `number`          | Number                    | content       | ✅          |
| `date`            | Date                      | content       | ✅          |

## Variables

| Identifier         | Human name          | Category    | Documented? |
| ------------------ | ------------------- | ----------- | ----------- |
| `setvariable`      | Set Variable        | variables   | ✅          |
| `getvariable`      | Get Variable        | variables   | ✅          |
| `appendvariable`   | Add to Variable     | variables   | ✅          |

## Control flow

| Identifier            | Human name           | Category  | Documented? |
| --------------------- | -------------------- | --------- | ----------- |
| `conditional`         | If / Otherwise / End | control   | ✅          |
| `repeat.count`        | Repeat               | control   | ✅          |
| `repeat.each`         | Repeat with Each     | control   | ✅          |
| `choosefrommenu`      | Choose from Menu     | control   | ✅          |
| `delay`               | Wait                 | control   | ✅          |
| `exit`                | Exit Shortcut        | control   | ✅          |
| `nothing`             | Nothing              | utility   | ✅          |
| `comment`             | Comment              | utility   | ✅          |
| `count`               | Count                | utility   | ✅          |
| `waittoreturn`        | Wait to Return       | control   | idx         |

## Web / URL

| Identifier                | Human name                | Category | Documented? |
| ------------------------- | ------------------------- | -------- | ----------- |
| `downloadurl`             | Get Contents of URL       | web      | ✅          |
| `openurl`                 | Open URLs                 | web      | ✅          |
| `url.expand`              | Expand URL                | web      | ✅          |
| `url.getheaders`          | Get Headers of URL        | web      | ✅          |
| `urlencode`               | URL Encode / Decode       | web      | ✅          |
| `getwebpagecontents`      | Get Contents of Web Page  | web      | ✅          |
| `runjavascriptonwebpage`  | Run JavaScript on Web Page| web      | ✅          |
| `detect.link`             | Get URLs from Input       | web      | ✅          |
| `getvalueforkey`          | Get Dictionary Value      | dict     | ✅          |
| `setvalueforkey`          | Set Dictionary Value      | dict     | ✅          |
| `detect.dictionary`       | Get Dictionary from Input | dict     | idx         |

## Scripting

| Identifier                       | Human name                | Category | Documented? |
| -------------------------------- | ------------------------- | -------- | ----------- |
| `runsshscript`                   | Run Script over SSH       | script   | idx         |
| `runshellscript`                 | Run Shell Script (macOS)  | script   | ⚠          |
| `runapplescript`                 | Run AppleScript (macOS)   | script   | ⚠          |
| `runjavascriptforautomation`     | JXA (macOS)               | script   | ⚠          |
| `runworkflow`                    | Run Shortcut              | script   | ✅          |
| `runextension`                   | Run App Extension         | script   | idx         |
| `hash`                           | Hash                      | crypto   | ✅          |
| `base64encode`                   | Base64 Encode             | encoding | ✅          |
| `math`                           | Calculate                 | math     | ✅          |
| `statistics`                     | Calculate Statistics      | math     | idx         |
| `number.random`                  | Random Number             | math     | ✅          |

## User input / UI

| Identifier             | Human name            | Category | Documented? |
| ---------------------- | --------------------- | -------- | ----------- |
| `ask`                  | Ask for Input         | UI       | ✅          |
| `alert`                | Show Alert            | UI       | ✅          |
| `showresult`           | Show Result           | UI       | ✅          |
| `viewresult`           | Quick Look (data)     | UI       | ✅          |
| `notification`         | Show Notification     | UI       | ✅          |
| `speaktext`            | Speak Text            | speech   | ✅          |
| `dictatetext`          | Dictate Text          | speech   | ⚠          |
| `showdefinition`       | Show Definition       | UI       | ✅          |
| `choosefromlist`       | Choose from List      | UI       | ⚠          |

## Device

| Identifier             | Human name                  | Category | Documented? |
| ---------------------- | --------------------------- | -------- | ----------- |
| `setbrightness`        | Set Brightness              | device   | ✅          |
| `setvolume`            | Set Volume                  | device   | ✅          |
| `vibrate`              | Vibrate Device              | device   | ✅          |
| `airplanemode.set`     | Set Airplane Mode           | device   | ✅          |
| `bluetooth.set`        | Set Bluetooth               | device   | ✅          |
| `wifi.set`             | Set Wi-Fi                   | device   | ✅          |
| `cellulardata.set`     | Set Cellular Data           | device   | ✅          |
| `lowpowermode.set`     | Set Low Power Mode          | device   | ✅          |
| `dnd.set`              | Set Do Not Disturb (legacy) | device   | idx         |
| `focus.set`            | Set Focus                   | device   | ⚠          |
| `flashlight`           | Set Flashlight              | device   | ✅          |
| `getbatterylevel`      | Get Battery Level           | device   | ✅          |
| `getdevicedetails`     | Get Device Details          | device   | ✅          |
| `getipaddress`         | Get IP Address              | device   | idx         |
| `getwifi`              | Get Network Details         | device   | idx         |

## Files / documents

| Identifier                    | Human name          | Category | Documented? |
| ----------------------------- | ------------------- | -------- | ----------- |
| `documentpicker.open`         | Get File            | files    | ⚠          |
| `documentpicker.save`         | Save File           | files    | ⚠          |
| `file.append`                 | Append to File      | files    | ⚠          |
| `file.read`                   | Read File           | files    | ⚠          |
| `file.createfolder`           | Make Folder         | files    | ⚠          |
| `file.getlink`                | Get Link to File    | files    | ✅          |
| `makezip`                     | Make Archive        | files    | ✅          |
| `unzip`                       | Extract Archive     | files    | ✅          |
| `print`                       | Print               | output   | ✅          |
| `previewdocument`             | Quick Look          | UI       | ✅          |

## Media

| Identifier                       | Human name               | Category | Documented? |
| -------------------------------- | ------------------------ | -------- | ----------- |
| `takephoto`                      | Take Photo               | camera   | ⚠          |
| `getlastphoto`                   | Get Latest Photos        | photos   | ✅          |
| `getlastvideo`                   | Get Latest Video         | photos   | ✅          |
| `getlastscreenshot`              | Get Latest Screenshot    | photos   | ✅          |
| `getlatestbursts`                | Get Latest Bursts        | photos   | idx         |
| `getlatestlivephotos`            | Get Latest Live Photos   | photos   | idx         |
| `deletephotos`                   | Delete Photos            | photos   | ✅          |
| `avairyeditphoto`                | Edit Image (Aviary)      | photos   | idx         |
| `trimvideo`                      | Trim Media               | media    | ✅          |
| `playsound`                      | Play Sound               | media    | ✅          |
| `scanbarcode`                    | Scan QR/Barcode          | camera   | ✅          |
| `encodemedia`                    | Encode Media             | media    | ⚠          |
| `getframesfromimage`             | Get Frames from Image    | images   | idx         |
| `image.resize`                   | Resize Image             | images   | ⚠          |

## Music / audio

| Identifier            | Human name             | Category | Documented? |
| --------------------- | ---------------------- | -------- | ----------- |
| `pausemusic`          | Play/Pause             | music    | ✅          |
| `skipback`            | Skip Back              | music    | ✅          |
| `skipforward`         | Skip Forward           | music    | ✅          |
| `clearupnext`         | Clear Up Next          | music    | ✅          |
| `getcurrentsong`      | Get Current Song       | music    | ✅          |

## Communication

| Identifier        | Human name          | Category | Documented? |
| ----------------- | ------------------- | -------- | ----------- |
| `sendmessage`     | Send Message        | comms    | ⚠          |
| `sendemail`       | Send Email          | comms    | ⚠          |
| `share`           | Share               | comms    | ✅          |
| `airdropdocument` | AirDrop             | comms    | ✅          |
| `readinglist`    | Add to Reading List | comms    | ✅          |
| `postonfacebook` | Post on Facebook    | legacy   | ✅          |
| `tweet`           | Tweet (legacy)      | legacy   | ✅          |
| `tumblr.post`     | Post to Tumblr      | legacy   | ✅          |
| `wordpress.post` | Post to WordPress   | legacy   | ✅          |

## Contacts / detection

| Identifier                | Human name                      | Category | Documented? |
| ------------------------- | ------------------------------- | -------- | ----------- |
| `detect.contacts`         | Get Contacts from Input         | detect   | ✅          |
| `detect.emailaddress`     | Get Email Addresses from Input  | detect   | ✅          |
| `detect.phonenumber`      | Get Phone Numbers from Input    | detect   | ✅          |
| `detect.date`             | Get Dates from Input            | detect   | idx         |
| `detect.text`             | Get Text from Input             | detect   | idx         |
| `detect.images`           | Get Images from Input           | detect   | ✅          |
| `detect.address`          | Get Addresses from Input        | detect   | idx         |

## Location / maps

| Identifier              | Human name          | Category | Documented? |
| ----------------------- | ------------------- | -------- | ----------- |
| `getcurrentlocation`    | Get Current Location| location | idx         |
| `searchmaps`            | Search in Maps      | maps     | idx         |
| `getmapslink`           | Get Maps Link       | maps     | idx         |
| `getdistance`           | Get Distance        | location | ⚠          |

## Time / date

| Identifier            | Human name          | Category | Documented? |
| --------------------- | ------------------- | -------- | ----------- |
| `format.date`         | Format Date         | date     | ✅          |
| `gettimebetweendates` | Time Between Dates  | date     | idx         |

## Text processing

| Identifier                   | Human name                    | Category | Documented? |
| ---------------------------- | ----------------------------- | -------- | ----------- |
| `text.changecase`            | Change Case                   | text     | ✅          |
| `text.match`                 | Match Text                    | text     | ✅          |
| `text.match.getgroup`        | Get Group from Matched Text   | text     | idx         |
| `text.replace`               | Replace Text                  | text     | ✅          |
| `text.split`                 | Split Text                    | text     | ✅          |
| `text.combine`               | Combine Text                  | text     | ✅          |
| `correctspelling`            | Correct Spelling              | text     | idx         |
| `detectlanguage`             | Detect Language               | text     | idx         |
| `getmarkdownfromrichtext`    | Markdown from Rich Text       | text     | idx         |
| `getrichtextfromhtml`        | Rich Text from HTML           | text     | idx         |
| `getrichtextfrommarkdown`    | Rich Text from Markdown       | text     | idx         |
| `gettextfrommessage`         | Get Text from Message         | text     | ⚠          |

## List helpers

| Identifier              | Human name             | Category | Documented? |
| ----------------------- | ---------------------- | -------- | ----------- |
| `getitemfromlist`       | Get Item from List     | list     | ✅          |
| `filter.files`          | Filter Files           | list     | ⚠          |
| `filter.photos`         | Filter Photos          | list     | ⚠          |

## Dictionary / clipboard

| Identifier           | Human name                | Category   | Documented? |
| -------------------- | ------------------------- | ---------- | ----------- |
| `getclipboard`       | Get Clipboard             | clipboard  | ✅          |
| `setclipboard`       | Set Clipboard             | clipboard  | ⚠          |

## Shortcuts meta

| Identifier          | Human name           | Category    | Documented? |
| ------------------- | -------------------- | ----------- | ----------- |
| `runworkflow`       | Run Shortcut         | shortcut    | ✅          |
| `getmyworkflows`    | Get My Shortcuts     | shortcut    | idx         |
| `openapp`           | Open App             | app         | idx         |
| `handoff`           | Handoff to iPhone    | handoff     | idx         |

## Scheduling

| Identifier         | Human name         | Category   | Documented? |
| ------------------ | ------------------ | ---------- | ----------- |
| `alarm.create`     | Create Alarm       | alarm      | ✅          |
| `removereminders`  | Remove Reminders   | reminders  | idx         |
| `showincalendar`   | Show in Calendar   | calendar   | ✅          |

## Store / app

| Identifier          | Human name          | Category | Documented? |
| ------------------- | ------------------- | -------- | ----------- |
| `showinstore`       | Show in App Store   | store    | idx         |
| `getarticle`        | Get Article         | reader   | ✅          |
| `getnameofemoji`    | Get Name of Emoji   | text     | idx         |
| `getitemname`       | Get Name            | utility  | ✅          |
| `setitemname`       | Set Name            | utility  | ✅          |
| `getitemtype`       | Get Type            | utility  | ✅          |

## Health (⚠ all unverified as `is.workflow.actions.*`)

Apple Health actions are typically routed via `com.apple.Health.*`
intents, not `is.workflow.actions.*`. Discover via
`tools/list-app-intents.py` targeting the Health app.

## Home / HomeKit (⚠ see automation reference)

Most Home actions are routed via intents; the few observed
`is.workflow.actions.home.*` identifiers are inconsistent between
iOS releases. Round-trip before generating.

## Maps / navigation

| Identifier              | Human name          | Category | Documented? |
| ----------------------- | ------------------- | -------- | ----------- |
| `gettraveltime`         | Get Travel Time     | maps     | ⚠          |
| `showdirections`        | Show Directions     | maps     | ⚠          |

## Weather (⚠ routed via intents)

Most Weather queries go through `com.apple.weather.*` intents.

## Third-party prefix reference

For third-party app actions, the identifier is the app's bundle ID
plus an action suffix. Examples:

| App prefix                               | See                              |
| ---------------------------------------- | -------------------------------- |
| `com.sindresorhus.Actions.*`             | `third-party/actions-app.md`     |
| `dk.simonbs.datajar.*`                   | `third-party/data-jar.md`        |
| `com.tinyrobot.ToolboxPro.*`             | `third-party/toolbox-pro.md`     |
| `dk.simonbs.Scriptable.*`                | `third-party/scriptable.md`      |
| `AsheKube.app.a-Shell.*`                 | `third-party/a-shell.md`         |
| `dk.simonbs.Jayson.*`                    | `third-party/jayson.md`          |
| `de.sostudio.Pushcut.*`                  | `third-party/pushcut.md`         |
| `com.omz-software.Pythonista3.*`         | (Pythonista; legacy)             |

## Sources

- joshfarrant/shortcuts-js action identifier enum:
  `https://github.com/joshfarrant/shortcuts-js/blob/master/src/
  interfaces/WF/WFWorkflowActionIdentifier.ts`
- sebj iOS-Shortcuts-Reference:
  `https://github.com/sebj/iOS-Shortcuts-Reference`
- openclaw shortcuts-skill (modern additions):
  `https://github.com/openclaw/skills`
