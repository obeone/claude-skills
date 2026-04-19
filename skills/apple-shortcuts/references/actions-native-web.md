# Web / URL / HTTP actions

Fetching, parsing, and manipulating URLs and HTTP responses. The
workhorse is `Get Contents of URL` (`downloadurl`).

## URL

See `actions-native-core.md#url-url`.

## Get Contents of URL (`downloadurl`)

**Identifier**: `is.workflow.actions.downloadurl`
**Platforms**: iOS, macOS, watchOS
**Input**: URL (via Shortcut Input) or explicit `WFURL`
**Output**: depends on response content type (Text, Dict, File, Image)

**Parameters**:

| Key                          | Type       | Notes                          |
| ---------------------------- | ---------- | ------------------------------ |
| `WFURL`                      | URL/token  | The URL to fetch               |
| `WFHTTPMethod`               | String     | `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD` |
| `WFHTTPHeaders`              | DictField  | Request headers                |
| `WFHTTPBodyType`             | String     | `JSON`, `Form`, `Multipart Form`, `File` |
| `WFJSONValues` / `WFFormValues` / `WFRequestVariable` | DictField | Body payload |
| `ShowHeaders`                | Bool       | Include response headers in output |

### GET

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.downloadurl</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFURL</key>
    <string>https://api.example.com/v1/items</string>
    <key>WFHTTPMethod</key>
    <string>GET</string>
    <key>UUID</key>
    <string>11111111-1111-1111-1111-111111111111</string>
  </dict>
</dict>
```

### POST JSON with Bearer auth

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.downloadurl</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFURL</key>
    <string>https://api.example.com/v1/items</string>
    <key>WFHTTPMethod</key>
    <string>POST</string>
    <key>WFHTTPBodyType</key>
    <string>JSON</string>
    <key>WFJSONValues</key>
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
                <key>string</key><string>title</string>
                <key>attachmentsByRange</key><dict/>
              </dict>
              <key>WFSerializationType</key>
              <string>WFTextTokenString</string>
            </dict>
            <key>WFValue</key>
            <dict>
              <key>Value</key>
              <dict>
                <key>string</key><string>New item</string>
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
                <key>string</key><string>Bearer YOUR_TOKEN</string>
                <key>attachmentsByRange</key><dict/>
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
  </dict>
</dict>
```

### POST Form

Use `WFHTTPBodyType` = `Form` and `WFFormValues` instead of
`WFJSONValues`. Same dictionary shape, encoded as
`application/x-www-form-urlencoded`.

### Multipart Form

Use `WFHTTPBodyType` = `Multipart Form` and `WFFormValues`. File
fields can have nested `WFItemType=1` (dict) values specifying file
input.

### PUT / PATCH / DELETE

Identical shape to POST, different `WFHTTPMethod`. DELETE with no
body: omit `WFHTTPBodyType`, `WFJSONValues`, `WFFormValues`.

**Gotchas**:

- Errors from HTTP (4xx, 5xx) are returned as the response body; the
  shortcut does not throw. Check status via `ShowHeaders` +
  inspecting response headers, or parse the body for an expected
  shape.
- Timeout is not user-configurable. It's ~60s per request.
- Binary responses are returned as File objects, usable by
  subsequent Save File / Base64 Encode actions.
- `ShowHeaders=true` wraps the output in a dict with `Headers` and
  `Content` keys — downstream code must be aware.
- No way to read response status code independently of headers.
  Workaround: read headers, parse `Status: XXX` or check a known
  header's presence.

## Expand URL (`url.expand`)

Follows redirects and returns the final URL.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.url.expand</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: URL. Output: URL.

## Get Headers of URL (`url.getheaders`)

HEAD-like request; returns response headers as a Dictionary.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.url.getheaders</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

## URL Encode (`urlencode`)

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.urlencode</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFEncodeMode</key>
    <string>Encode</string>
  </dict>
</dict>
```

`WFEncodeMode` values: `Encode`, `Decode`.

## Open URLs (`openurl`)

Opens one or more URLs in the default browser.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.openurl</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Input: URL(s). No output (shortcut continues with original input).

## Get URLs from Input (`detect.link`)

Parses URLs out of text, files, or rich objects.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.detect.link</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Output: list of URLs.

## Get Contents of Web Page (`getwebpagecontents`)

Scrapes the current Safari tab or a webpage input.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.getwebpagecontents</string>
  <key>WFWorkflowActionParameters</key>
  <dict/>
</dict>
```

Output: Text (HTML content) or Article.

## Run JavaScript on Web Page (`runjavascriptonwebpage`)

Safari only. See `actions-native-core.md#run-javascript-runjavascriptonwebpage`.

## Get Article (`getarticle`)

Safari Reader-style extraction.

## JSON helpers

JSON responses from `downloadurl` with `application/json` content
type auto-coerce to Dictionary. Use `getvalueforkey` to extract
fields. See `patterns/json-parsing.md` for complete flows.

## Authentication patterns

### Bearer token

Header `Authorization: Bearer <token>` via `WFHTTPHeaders`.

### Basic auth

Header `Authorization: Basic <base64>`. Build the token with a
preceding Base64 Encode action on `user:pass`:

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFTextActionText</key>
    <string>alice:secret</string>
    <key>UUID</key>
    <string>AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA</string>
  </dict>
</dict>
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.base64encode</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>WFEncodeMode</key>
    <string>Encode</string>
    <key>UUID</key>
    <string>BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB</string>
  </dict>
</dict>
<!-- Then downloadurl with header Authorization: Basic [Base64-encoded value] -->
```

### API key query param

Build the URL with Text interpolation or use URL Encode on the key
before concatenation.

## Pagination

Shortcuts lacks native iteration with state propagation across
`Repeat` boundaries for complex pagination. Patterns:

1. **Cursor in URL**: set a `cursor` variable; loop via `Repeat` a
   fixed number of iterations; break with `Exit Shortcut` when
   response has no `next_cursor`.
2. **Page number**: use `Repeat Index` as the page parameter in a
   fixed-count `Repeat`.

See `patterns/http-api-calls.md` for full examples.

## Sources

- sebj:
  `https://github.com/sebj/iOS-Shortcuts-Reference`
- Pretzel Labs HTTP shortcut tutorial (community):
  general reference for `downloadurl` parameter keys.
