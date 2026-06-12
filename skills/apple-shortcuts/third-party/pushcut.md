# Pushcut

_Last verified: 2026-04-19_

Automation server with webhook triggers, notification actions, and
scheduled runners. The heavyweight for automation beyond what
personal automations allow.

- **Site**: `https://www.pushcut.io`
- **App Store**: `https://apps.apple.com/app/pushcut/id1269531490`
- **Developer**: simianarmy UG (so.studio).
- **Bundle ID prefix**: `de.sostudio.Pushcut` ⚠ unverified literal.
- **Price**: Free tier with limits; subscription for heavy use
  (~€5/month).
- **Platforms**: iOS + web dashboard + optional macOS "Automation
  Server" on a dedicated iPad/iPhone.

## What it does

Native personal automations:

- Limited trigger set (time, location, app open, etc.).
- One automation per trigger.
- Tied to one device.
- Require Focus / NFC / Charger to run silently pre-iOS 15.4.

Pushcut extends this with:

- **Webhooks** — HTTP endpoints that trigger shortcuts. Standard way
  to bridge iOS shortcuts to a server, Home Assistant, Zapier, etc.
- **Scheduled automations** — actually-reliable scheduling that
  doesn't require the device to be awake.
- **Notifications with actions** — rich banner notifications that
  trigger other shortcuts on tap.
- **Automation Server** — a dedicated iOS device acts as an
  always-on runner for shortcuts triggered remotely.

## Actions exposed to Shortcuts

Official list:
`https://www.pushcut.io/shortcuts_actions`

| Action                             | Purpose                          |
| ---------------------------------- | -------------------------------- |
| Send Notification                  | Trigger a Pushcut notification   |
|                                    | (with actions, image, sound)     |
| Execute Online Automation          | Run a Pushcut-hosted automation  |
| Register Webhook Response          | Reply to a webhook request       |
| Schedule Automation                | Future-schedule a Pushcut automation |
| Cancel Scheduled Automation        | Cancel a scheduled run           |
| Home Assistant — Call Service      | Home Assistant bridge            |

## Identifier pattern

⚠ Not publicly documented. Discover via
`tools/list-app-intents.py --bundle de.sostudio.Pushcut`.

## Usage — webhook trigger

Pushcut generates a URL like:

```text
https://api.pushcut.io/v1/notifications/ShortcutA/abc123
```

Call it from any HTTP client to trigger the associated shortcut.
Within Shortcuts, use native `Get Contents of URL` (POST). No
Pushcut action required for the caller — only for receiving.

## Usage — respond to an incoming webhook

Pushcut-triggered shortcuts can respond to the caller by using
"Register Webhook Response" as the last action. The response is
HTTP-returned synchronously to the caller.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>de.sostudio.Pushcut.RegisterWebhookResponseIntent</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>status</key>
    <integer>200</integer>
    <key>body</key>
    <string>ok</string>
  </dict>
</dict>
```

⚠ Literal identifier unverified.

## When to prefer over alternatives

- Integrating with non-Apple ecosystems (Home Assistant, IFTTT
  replacement).
- Scheduled shortcuts with reliability guarantees.
- Remote shortcut triggering from a server.

## Costs

Free tier: limited notifications per month. Full use requires Pro
subscription.

## Gotchas

- Privacy: Pushcut's webhook URLs include a secret token. Don't
  commit them to version control.
- Automation Server requires a spare iOS device running 24/7.
- Scheduled shortcuts running via Pushcut run on *Pushcut's*
  servers (for server-side automations) or on the Automation Server
  device — they don't run on the user's primary phone.
