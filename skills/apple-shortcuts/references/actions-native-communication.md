# Communication actions

Messages, Mail, Notifications, Speech, sharing.

## User-facing UI

### Show Result (`showresult`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.showresult</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>Text</key>
    <string>Done</string>
  </dict>
</dict>
```

Input: passthrough. Displays the value or text in a modal. On iOS,
blocks until dismissed; on macOS, appears as a notification-like
popup.

### Show Alert (`alert`)

Modal alert with OK / Cancel buttons. User cancel terminates shortcut.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.alert</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAlertActionTitle</key>
    <string>Are you sure?</string>
    <key>WFAlertActionMessage</key>
    <string>This will delete the file.</string>
    <key>WFAlertActionCancelButtonShown</key>
    <true/>
  </dict>
</dict>
```

### Show Notification (`notification`)

Non-interactive banner notification.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.notification</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFNotificationActionTitle</key>
    <string>Build complete</string>
    <key>WFNotificationActionBody</key>
    <string>Artifacts ready in ~/builds/</string>
    <key>WFNotificationActionSound</key>
    <true/>
  </dict>
</dict>
```

Does not block. Can carry a `WFAttachments` parameter for images.

### Quick Look (`viewresult`)

See `actions-native-files.md#quick-look-previewdocument`.

### Ask for Input (`ask`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.ask</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAskActionPrompt</key>
    <string>Enter your name</string>
    <key>WFInputType</key>
    <string>Text</string>
    <key>WFAskActionDefaultAnswer</key>
    <string>Alice</string>
  </dict>
</dict>
```

`WFInputType` values: `Text`, `Number`, `URL`, `Date`, `Time`,
`Date and Time`.

Output: user input of the specified type.

### Choose from List (`choosefromlist`)

⚠ identifier unverified; commonly seen.

```xml
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

Input: list. Output: selected item(s).

### Choose from Menu

See `control-flow.md#choose-from-menu`.

## Speech

### Speak Text (`speaktext`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.speaktext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFSpeakTextRate</key>
    <real>0.5</real>
    <key>WFSpeakTextPitch</key>
    <real>1.0</real>
    <key>WFSpeakTextLanguage</key>
    <string>en-US</string>
    <key>WFSpeakTextWaitUntilFinished</key>
    <true/>
  </dict>
</dict>
```

Input: text. `WFSpeakTextRate` range 0.0–1.0, `WFSpeakTextPitch` 0.5–2.0.

### Dictate Text (`dictatetext`)

⚠ identifier unverified; widely observed.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.dictatetext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFDictateTextLanguage</key>
    <string>en-US</string>
    <key>WFDictateTextStopListening</key>
    <string>After Short Pause</string>
  </dict>
</dict>
```

Output: text (user's dictated speech).

### Show Definition (`showdefinition`)

Looks up a word in the system dictionary.

## Messages and mail

### Send Message (`sendmessage`)

⚠ identifier unverified (widely observed). iOS + macOS.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.sendmessage</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFSendMessageContent</key>
    <string>Hello from a shortcut</string>
    <key>WFSendMessageRecipients</key>
    <array>
      <string>+15551234567</string>
    </array>
  </dict>
</dict>
```

Behavior: on iOS, presents the Messages UI pre-filled, requires a
tap to send. Silent send is not available without user consent.
Automations running in the background can send silently if
pre-authorized; see `actions-native-automation.md`.

### Send Email (`sendemail`)

⚠ identifier unverified.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.sendemail</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFSendEmailActionRecipients</key>
    <array>
      <string>alice@example.com</string>
    </array>
    <key>WFSendEmailActionSubject</key>
    <string>Report</string>
    <key>WFSendEmailActionInputAttachments</key>
    <dict/>
    <key>WFSendEmailActionBody</key>
    <string>See attached.</string>
  </dict>
</dict>
```

Opens Mail compose UI. Same silent-send caveat as messages.

### Make Phone Call

Not an `is.workflow.actions.*` action. Use the system Phone:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>com.apple.mobilephone.call</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>entities</key>
    <array>
      <!-- phone entity ref -->
    </array>
  </dict>
</dict>
```

⚠ The exact parameter shape varies by iOS version and is
intent-based. Round-trip a working example before generating.

### FaceTime

Identifier: `com.apple.facetime.facetime`. ⚠ same caveat.

## Contacts detection

### Get Contacts from Input (`detect.contacts`)

### Get Email Addresses from Input (`detect.emailaddress`)

### Get Phone Numbers from Input (`detect.phonenumber`)

All three: no parameters. Input: any. Output: list of detected items.

## Sharing

### Share (`share`)

Presents the system share sheet.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.share</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: any shareable content (text, URL, file).

### AirDrop (`airdropdocument`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.airdropdocument</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Presents AirDrop sheet.

## Legacy social posting

These work but target retired or deprecated networks. Documented for
reverse-engineering old shortcuts.

- `postonfacebook` — Post on Facebook.
- `tweet` — Post to X / Twitter (Twitter integration removed from
  iOS 11+; action fails on modern OS).
- `tumblr.post` — Post to Tumblr.
- `wordpress.post` — Post to WordPress.

Avoid in new shortcuts.

## Clipboard

### Get Clipboard (`getclipboard`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getclipboard</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Output: current clipboard content (as a content item).

### Set Clipboard

**Identifier**: ⚠ unverified (likely `is.workflow.actions.setclipboard`).

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.setclipboard</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFLocalOnly</key>
    <false/>
    <key>WFExpirationDate</key>
    <dict/>
  </dict>
</dict>
```

Input: the value to place on clipboard.

## Reading list

### Add to Reading List (`readinglist`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.readinglist</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: URL.

## Sources

- joshfarrant/shortcuts-js
- sebj iOS-Shortcuts-Reference
