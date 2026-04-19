# Pattern: HTTP API calls

## Problem

Call a REST API from a shortcut, parse the JSON response, and use
values from it.

## Solution

Use `is.workflow.actions.downloadurl` (Get Contents of URL) to send
the request. The response auto-coerces to Dictionary for
`application/json` responses; use `getvalueforkey` (Get Dictionary
Value) to extract fields.

## Plist — GET with bearer auth and JSON parsing

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>WFWorkflowMinimumClientVersion</key>
  <integer>900</integer>
  <key>WFWorkflowMinimumClientVersionString</key>
  <string>900</string>
  <key>WFWorkflowIcon</key>
  <dict>
    <key>WFWorkflowIconGlyphNumber</key>
    <integer>59412</integer>
    <key>WFWorkflowIconStartColor</key>
    <integer>463140863</integer>
  </dict>
  <key>WFWorkflowImportQuestions</key>
  <array>
    <dict>
      <key>ActionIndex</key><integer>0</integer>
      <key>Category</key><string>Parameter</string>
      <key>ParameterKey</key><string>WFTextActionText</string>
      <key>Text</key><string>Paste your API token</string>
    </dict>
  </array>
  <key>WFWorkflowInputContentItemClasses</key>
  <array/>
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
        <string>REPLACE_WITH_API_TOKEN</string>
        <key>UUID</key>
        <string>11111111-1111-1111-1111-111111111111</string>
        <key>CustomOutputName</key>
        <string>API Token</string>
      </dict>
    </dict>
    <dict>
      <key>WFWorkflowActionIdentifier</key>
      <string>is.workflow.actions.downloadurl</string>
      <key>WFWorkflowActionParameters</key>
      <dict>
        <key>WFURL</key>
        <string>https://api.github.com/user</string>
        <key>WFHTTPMethod</key>
        <string>GET</string>
        <key>WFHTTPHeaders</key>
        <dict>
          <key>Value</key>
          <dict>
            <key>WFDictionaryFieldValueItems</key>
            <array>
              <dict>
                <key>WFItemType</key><integer>0</integer>
                <key>WFKey</key>
                <dict>
                  <key>Value</key>
                  <dict>
                    <key>string</key><string>Authorization</string>
                    <key>attachmentsByRange</key><dict/>
                  </dict>
                  <key>WFSerializationType</key>
                  <string>WFTextTokenString</string>
                </dict>
                <key>WFValue</key>
                <dict>
                  <key>Value</key>
                  <dict>
                    <key>string</key>
                    <string>Bearer &#xFFFC;</string>
                    <key>attachmentsByRange</key>
                    <dict>
                      <key>{7, 1}</key>
                      <dict>
                        <key>Type</key><string>ActionOutput</string>
                        <key>OutputName</key><string>API Token</string>
                        <key>OutputUUID</key>
                        <string>11111111-1111-1111-1111-111111111111</string>
                        <key>Aggrandizements</key><array/>
                      </dict>
                    </dict>
                  </dict>
                  <key>WFSerializationType</key>
                  <string>WFTextTokenString</string>
                </dict>
              </dict>
              <dict>
                <key>WFItemType</key><integer>0</integer>
                <key>WFKey</key>
                <dict>
                  <key>Value</key>
                  <dict>
                    <key>string</key><string>Accept</string>
                    <key>attachmentsByRange</key><dict/>
                  </dict>
                  <key>WFSerializationType</key>
                  <string>WFTextTokenString</string>
                </dict>
                <key>WFValue</key>
                <dict>
                  <key>Value</key>
                  <dict>
                    <key>string</key><string>application/json</string>
                    <key>attachmentsByRange</key><dict/>
                  </dict>
                  <key>WFSerializationType</key>
                  <string>WFTextTokenString</string>
                </dict>
              </dict>
            </array>
          </dict>
          <key>WFSerializationType</key>
          <string>WFDictionaryFieldValue</string>
        </dict>
        <key>UUID</key>
        <string>22222222-2222-2222-2222-222222222222</string>
        <key>CustomOutputName</key>
        <string>API Response</string>
      </dict>
    </dict>
    <dict>
      <key>WFWorkflowActionIdentifier</key>
      <string>is.workflow.actions.getvalueforkey</string>
      <key>WFWorkflowActionParameters</key>
      <dict>
        <key>WFGetDictionaryValueType</key>
        <string>Value</string>
        <key>WFDictionaryKey</key>
        <string>login</string>
      </dict>
    </dict>
    <dict>
      <key>WFWorkflowActionIdentifier</key>
      <string>is.workflow.actions.showresult</string>
      <key>WFWorkflowActionParameters</key>
      <dict>
        <key>Text</key>
        <string>Logged in as the returned username</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
```

## Variations

- **POST JSON**: set `WFHTTPMethod=POST`, `WFHTTPBodyType=JSON`, and
  populate `WFJSONValues` with a `WFDictionaryFieldValue` of the
  payload. See `references/actions-native-web.md`.
- **Query parameters**: build the URL with Text interpolation and
  URL Encode on the values. Or use the Actions app's Modify URL for
  cleaner code.
- **File upload**: `WFHTTPBodyType=Multipart Form`, and include a
  file field via `WFItemType=1` with a file value.
- **Basic auth**: preceed the request with a
  `is.workflow.actions.gettext` containing `user:pass` then a
  `is.workflow.actions.base64encode` (Encode mode) to get the token,
  then header `Authorization: Basic <token>`.
- **Response status**: native Get Contents of URL does not expose the
  status code separately. If you need it, use Toolbox Pro's
  `Send HTTP Request`.

## Pagination — cursor

```text
1. Get Variable: cursor (defaulting to "")
2. Get Contents of URL: {base}/items?cursor={cursor}
3. Get Dictionary Value: items → append to results variable
4. Get Dictionary Value: next_cursor
5. If has value: Set Variable cursor to next_cursor; loop with Repeat
6. Otherwise: Exit Repeat; return results
```

Repeat loops without a clean break are done with a fixed-count
`Repeat` (e.g. 100 iterations) plus an `Exit Shortcut` inside an
`If` that breaks when the cursor is empty.

## Pagination — page number

```text
1. Repeat 10 times
2.   URL: {base}/items?page={Repeat Index}
3.   Get Contents of URL → response
4.   Get Dictionary Value: items
5.   If empty: Exit Shortcut
6.   Add to Variable: results
7. End Repeat
```

## Gotchas

- JSON auto-coercion requires the response's `Content-Type` header to
  contain `application/json`. APIs returning `text/plain` JSON
  require a follow-up `is.workflow.actions.getvalueforkey` anyway,
  but Shortcuts may display the response as text in the UI.
- Redirects are followed automatically. If you need the final URL,
  chain `is.workflow.actions.url.expand` — but note Expand URL uses
  HEAD by default, not GET.
- Large responses (> ~50MB) can crash the shortcut on iOS due to
  extension memory limits. Use Scriptable or move processing
  server-side.
- No way to inspect per-request timing or cancel mid-request.
- Cookies are session-scoped to the Shortcuts app, not shared with
  Safari.
