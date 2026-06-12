# Automation actions and triggers

Shortcuts distinguishes two automation kinds: **Personal** automations
(run on a device, triggered by user context) and **Home** automations
(trigger HomeKit scenes, tied to a home). Triggers are not encoded in
the shortcut's plist body — they live in the Shortcuts app's database
(`ZTRIGGER` table). The shortcut plist body contains only the action
list that runs.

This means **you cannot ship an automation trigger in a plist file**.
The user must create the automation manually in the Shortcuts app and
attach it to an imported shortcut. This file documents the trigger
options so you can give accurate setup instructions.

## Personal automation triggers

Categorized by the Shortcuts app's "New Personal Automation" screen.

### Events of the day

| Trigger              | Parameters                         | Silent on iOS 17+? |
| -------------------- | ---------------------------------- | ------------------ |
| Time of Day          | Sunrise / sunset / specific time   | Yes                |
| Alarm                | Which alarm                        | Yes                |
| Before I Sleep       | (uses Sleep schedule)              | Yes                |
| Wake                 | (on wake from Sleep Focus)         | Yes                |

### Travel

| Trigger              | Parameters                         | Silent on iOS 17+? |
| -------------------- | ---------------------------------- | ------------------ |
| Arrive               | Location, time window              | Yes                |
| Leave                | Location, time window              | Yes                |
| Before Commute       | Home, work location                | Yes                |
| CarPlay              | Connect / disconnect               | Yes                |

### Communication

| Trigger              | Parameters                | Silent on iOS 17+? |
| -------------------- | ------------------------- | ------------------ |
| Message              | Sender(s), keyword(s)     | Yes                |
| Email                | Sender(s), subject key    | Yes                |

### Settings

| Trigger              | Parameters                            | Silent on iOS 17+? |
| -------------------- | ------------------------------------- | ------------------ |
| Airplane Mode        | On / off                              | Yes                |
| Wi-Fi                | Connect / disconnect (specific SSID)  | Yes                |
| Bluetooth            | Connect / disconnect (specific)       | Yes                |
| App                  | Open / close any app                  | Yes                |
| Focus                | Enable / disable (any or specific)    | Yes                |
| Low Power Mode       | On / off                              | Yes                |
| Charger              | Connected / disconnected              | Yes                |
| NFC                  | Scan an NFC tag                       | Yes                |

### Health

| Trigger              | Parameters                            | Silent? |
| -------------------- | ------------------------------------- | ------- |
| Sleep                | Bedtime / wake                        | Yes     |

## Silent vs. confirmation execution

Until iOS 15.4, most personal automations required confirmation (a
"Run" button in a banner). In iOS 15.4, Apple added a "Run
Immediately" / "Ask Before Running" toggle for many triggers.

By iOS 17, the default is "Run Immediately" for all triggers above,
with a brief notification posted to the Lock Screen after execution.

⚠ A handful of actions are always gated:

- Actions that send a message, email, or share sheet prompt still
  require user input on iOS even when the automation is "silent".
- Actions that open an app interrupt the current foreground activity
  (by design).
- Some destructive actions (delete photos) still prompt.

## Home automations

Attached to a HomeKit Home. Triggers:

| Trigger         | Notes                                        |
| --------------- | -------------------------------------------- |
| When someone    | Arrives / leaves                             |
| A time of day   | Sunrise / sunset / specific time             |
| An accessory    | Controlled / changes state                   |
| A sensor        | Detects / stops detecting                    |
| Convert         | Convert a scene to a shortcut                |

Home automations run on the home's hub (Apple TV, HomePod, iPad in
Home role). Shortcuts executed by home automations have limited
capabilities — no UI, no interactive actions.

## Focus actions

### Set Focus

**Identifier**: ⚠ likely `is.workflow.actions.focus.set` or
`is.workflow.actions.dnd.set`. Shortcuts renamed "Do Not Disturb" to
"Focus" in iOS 15 and shipped both identifiers for backward
compatibility for several versions.

**Parameters** (observed):

| Key             | Type    | Notes                              |
| --------------- | ------- | ---------------------------------- |
| `OnValue`       | Bool    | Enable / disable                   |
| `Mode`          | String  | `Do Not Disturb`, `Work`, `Personal`, etc. |
| `Duration`      | String  | `1 hour`, `Until Turned Off`, etc. |

Round-trip from Shortcuts.app before generating.

### Set Wallpaper

iOS only. ⚠ identifier unverified. The iOS 16+ Wallpaper action has
distinct parameters for Lock Screen vs Home Screen.

## Sleep / sleep schedule

### Set Sleep Schedule

⚠ not publicly documented as an `is.workflow.actions.*` identifier.
Exposed through Health intent, often routed as
`com.apple.Health.<intent>`.

## Home actions

### Control Home (`home.control`)

⚠ identifier unverified. Invokes a HomeKit scene or toggles an
accessory.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.home.control</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFHomeAccessory</key>
    <!-- opaque HomeKit identifier; best generated via round-trip -->
  </dict>
</dict>
```

Generating Home actions from scratch is unreliable because of opaque
HomeKit identifiers. The canonical approach is to have the user
create the action interactively in Shortcuts.app, export, then edit
around it.

## System intents (not `is.workflow.actions.*`)

Apple routes many system interactions through dedicated intents:

- `com.apple.mobilephone.call` — phone call.
- `com.apple.facetime.facetime` — FaceTime.
- `com.apple.Health.*` — Health queries.
- `com.apple.Maps.*` — Maps navigation.
- `com.apple.weather.*` — Weather queries.
- `com.apple.calendar.*` — Calendar events.
- `com.apple.reminders.*` — Reminders.

These are discoverable via `tools/list-app-intents.py` targeting
`/System/Applications/`.

## Scheduling from within a shortcut

### Create Alarm (`alarm.create`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.alarm.create</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFAlarmTime</key>
    <string>07:30</string>
    <key>WFAlarmLabel</key>
    <string>Morning run</string>
    <key>WFRepeatDays</key>
    <array>
      <string>Monday</string>
      <string>Wednesday</string>
      <string>Friday</string>
    </array>
  </dict>
</dict>
```

### Toggle Alarm

⚠ identifier unverified.

### Show in Calendar (`showincalendar`)

Input: date. Opens Calendar on that day.

## Instructing a user to build an automation

When your deliverable depends on an automation trigger, output
instructions like this:

```markdown
## After importing the shortcut

1. Open Shortcuts app.
2. Tap **Automation** tab.
3. Tap **+** → **Create Personal Automation**.
4. Select trigger: **Time of Day**, 08:00, every day.
5. Tap **Next**.
6. Tap **Add Action**.
7. Search for **Run Shortcut**.
8. Select the shortcut named `<your shortcut name>`.
9. Tap **Next**.
10. Toggle **Ask Before Running** **off**.
11. Tap **Done**.
```

Shortcuts' automation UI changes each iOS version; keep instructions
generic and short.

## Sources

- Apple: Enable/disable personal automation:
  `https://support.apple.com/guide/shortcuts/
  enable-or-disable-a-personal-automation-apd602971e63/ios`
- Matthew Cassinelli (automations run immediately):
  `https://matthewcassinelli.com/
  automations-run-immediately-shortcuts-notifications/`
- iDownloadBlog (iOS 15.4 silent automations).
