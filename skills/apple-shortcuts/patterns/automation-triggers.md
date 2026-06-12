# Pattern: Automation triggers

## Problem

Make a shortcut run automatically in response to a time, location,
app, or system event — rather than manual invocation.

## Solution

Personal automations (in the Shortcuts app → Automation tab) bind a
trigger to an existing shortcut. Triggers are NOT encoded in the
plist; they live in the app's database. You ship the shortcut, the
user creates the automation.

See `references/actions-native-automation.md` for the full list of
available triggers per category.

## What you can ship vs. what the user must set up

### You ship

The shortcut containing the action sequence (as a `.shortcut` or
signed plist).

### User sets up

The trigger binding:

1. Open Shortcuts → Automation tab.
2. + → Create Personal Automation.
3. Pick trigger.
4. Add Action → Run Shortcut → select your shortcut.
5. Toggle "Ask Before Running" off (iOS 15.4+).
6. Done.

## Instructing the user — template

When your deliverable includes an automation, append this to your
reply:

```markdown
## Setting up the automation

1. Import the shortcut (see import instructions above).
2. Open the **Shortcuts** app.
3. Go to the **Automation** tab (or **Automations** in the sidebar
   on macOS).
4. Tap **+** → **Create Personal Automation**.
5. Select **<TRIGGER TYPE>** and configure it:
   - <trigger-specific settings>
6. Tap **Next**.
7. Tap **Add Action**.
8. Search for **Run Shortcut**.
9. Tap the action, then tap "Shortcut" and select
   **<your shortcut name>**.
10. Tap **Next**.
11. Toggle **Ask Before Running** to OFF (requires iOS 15.4+).
12. Tap **Done**.
```

## Choosing a trigger

| Want to run on                       | Trigger                     |
| ------------------------------------ | --------------------------- |
| Specific time of day                 | Time of Day                 |
| Arriving/leaving a location          | Arrive / Leave              |
| Alarm going off                      | Alarm                       |
| Receiving a message                  | Message                     |
| Receiving an email                   | Email                       |
| Opening / closing an app             | App                         |
| Connecting a Wi-Fi network           | Wi-Fi                       |
| Charger plugged in                   | Charger                     |
| Focus mode toggled                   | Focus                       |
| Low battery                          | Low Power Mode              |
| NFC tag tapped                       | NFC                         |
| CarPlay connect                      | CarPlay                     |
| Sleep starts / wake                  | Sleep / Wake                |

## Silent vs confirmation

- iOS 13–15.3: most triggers required tap-to-run confirmation.
- iOS 15.4+: added toggle "Run Immediately" / "Ask Before Running"
  for most triggers.
- iOS 17+: most triggers default to Run Immediately. A banner
  notification is posted after execution.

Triggers that still require a tap (as of iOS 17):

- None for most flows, but actions inside the shortcut that need
  user input (Ask for Input, Send Message, etc.) still require
  interaction at that step.

## Limitations

- **One trigger per automation.** No multi-trigger automations.
- **No trigger on shortcut completion** (chaining via trigger is
  not supported; use `runworkflow` instead).
- **Not all apps can be App triggers.** The trigger picker lists
  installed apps, but some system apps are missing.
- **Location triggers need Always Location permission** for the
  Shortcuts app. The system prompts on first automation save.
- **Home automations run on the home hub** (Apple TV / HomePod /
  iPad). Shortcuts invoked by a home automation can't present UI.

## Example — Automate by Wi-Fi

Use case: when joining "Home Wi-Fi", run a shortcut that turns off
work Focus and starts "Morning" playlist.

```text
Shortcut body (what you ship):
  1. Set Focus: Work → Off
  2. Run Shortcut: "Start Morning Playlist"

User automation setup:
  - Trigger: Wi-Fi → Network: Home Wi-Fi → Join
  - Action: Run Shortcut → <your shortcut name>
  - Ask Before Running: Off
```

## Pushcut alternatives

For triggers outside the native set (webhooks, complex schedules,
cross-device), use Pushcut. See `third-party/pushcut.md`.

Pushcut supports:

- Webhook triggers (any HTTP POST from anywhere).
- Reliable scheduled automations independent of device wake state.
- Remote triggers from a Pushcut-registered device.

## Gotchas

- **Personal automations are device-local.** Setting up on iPhone
  doesn't auto-propagate to iPad even when iCloud sync is on.
  Automations must be created per-device.
- **Time of Day** triggers require the device to be on and unlocked
  for action sequences that include interactive steps.
- **App triggers** fire on app launch but not on reopen from
  background.
- **The automation can silently fail.** If the shortcut has an
  error, personal automations show a small red badge in the
  Shortcuts UI but no OS-level notification. Add a `Show
  Notification` as the last action to confirm it ran.
- **Testing is hard.** You can tap "Run" in the automation's detail
  view to test, but conditions (location, Wi-Fi, etc.) are
  simulated.
