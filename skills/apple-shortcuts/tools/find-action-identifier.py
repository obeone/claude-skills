#!/usr/bin/env python3
"""Fuzzy-search the action identifier catalog by human name.

Usage:
    find-action-identifier.py "send email"

Searches an embedded index of native + third-party actions using
Levenshtein distance and bag-of-words overlap. Returns top N matches
with scores.

Exit codes:
    0 — matches found.
    1 — no match above threshold.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Iterable

LOGGER = logging.getLogger(__name__)

# Embedded index. For a canonical source, see
# references/actions-native-full-index.md.
CATALOG: list[dict[str, str]] = [
    # Native (high-signal subset; full list in embedded source is larger)
    {"identifier": "is.workflow.actions.gettext", "name": "Text",
     "keywords": "text string literal content"},
    {"identifier": "is.workflow.actions.url", "name": "URL",
     "keywords": "url uri link"},
    {"identifier": "is.workflow.actions.dictionary", "name": "Dictionary",
     "keywords": "dictionary dict map object"},
    {"identifier": "is.workflow.actions.list", "name": "List",
     "keywords": "list array items"},
    {"identifier": "is.workflow.actions.number", "name": "Number",
     "keywords": "number numeric integer float"},
    {"identifier": "is.workflow.actions.date", "name": "Date",
     "keywords": "date time now current"},
    {"identifier": "is.workflow.actions.setvariable",
     "name": "Set Variable",
     "keywords": "set variable store assign"},
    {"identifier": "is.workflow.actions.getvariable",
     "name": "Get Variable",
     "keywords": "get variable read load"},
    {"identifier": "is.workflow.actions.appendvariable",
     "name": "Add to Variable",
     "keywords": "append variable push add"},
    {"identifier": "is.workflow.actions.conditional",
     "name": "If / Otherwise / End If",
     "keywords": "if condition conditional branch else otherwise"},
    {"identifier": "is.workflow.actions.repeat.count",
     "name": "Repeat",
     "keywords": "repeat loop iterate for count"},
    {"identifier": "is.workflow.actions.repeat.each",
     "name": "Repeat with Each",
     "keywords": "repeat each foreach iterate list"},
    {"identifier": "is.workflow.actions.choosefrommenu",
     "name": "Choose from Menu",
     "keywords": "menu choose pick select branch option"},
    {"identifier": "is.workflow.actions.choosefromlist",
     "name": "Choose from List",
     "keywords": "list pick choose select options"},
    {"identifier": "is.workflow.actions.delay",
     "name": "Wait",
     "keywords": "wait delay sleep pause"},
    {"identifier": "is.workflow.actions.exit",
     "name": "Exit Shortcut",
     "keywords": "exit stop terminate quit end"},
    {"identifier": "is.workflow.actions.nothing",
     "name": "Nothing",
     "keywords": "nothing noop empty pass skip"},
    {"identifier": "is.workflow.actions.comment",
     "name": "Comment",
     "keywords": "comment note annotation"},
    {"identifier": "is.workflow.actions.count",
     "name": "Count",
     "keywords": "count size length number characters words"},
    {"identifier": "is.workflow.actions.downloadurl",
     "name": "Get Contents of URL",
     "keywords": "http get post fetch request api call download url"},
    {"identifier": "is.workflow.actions.openurl",
     "name": "Open URLs",
     "keywords": "open url safari browser launch"},
    {"identifier": "is.workflow.actions.url.expand",
     "name": "Expand URL",
     "keywords": "expand url redirect resolve follow"},
    {"identifier": "is.workflow.actions.url.getheaders",
     "name": "Get Headers of URL",
     "keywords": "headers url http head"},
    {"identifier": "is.workflow.actions.urlencode",
     "name": "URL Encode / Decode",
     "keywords": "url encode decode percent escape"},
    {"identifier": "is.workflow.actions.getwebpagecontents",
     "name": "Get Contents of Web Page",
     "keywords": "web page safari scrape content"},
    {"identifier": "is.workflow.actions.runjavascriptonwebpage",
     "name": "Run JavaScript on Web Page",
     "keywords": "javascript js safari web page execute"},
    {"identifier": "is.workflow.actions.detect.link",
     "name": "Get URLs from Input",
     "keywords": "urls extract detect input links"},
    {"identifier": "is.workflow.actions.getvalueforkey",
     "name": "Get Dictionary Value",
     "keywords": "dictionary value key get json parse extract field"},
    {"identifier": "is.workflow.actions.setvalueforkey",
     "name": "Set Dictionary Value",
     "keywords": "dictionary value key set update"},
    {"identifier": "is.workflow.actions.runworkflow",
     "name": "Run Shortcut",
     "keywords": "shortcut run invoke call another"},
    {"identifier": "is.workflow.actions.hash",
     "name": "Hash",
     "keywords": "hash md5 sha sha256 sha512 digest"},
    {"identifier": "is.workflow.actions.base64encode",
     "name": "Base64 Encode / Decode",
     "keywords": "base64 encode decode"},
    {"identifier": "is.workflow.actions.math",
     "name": "Calculate",
     "keywords": "math calculate add subtract multiply divide"},
    {"identifier": "is.workflow.actions.number.random",
     "name": "Random Number",
     "keywords": "random number dice"},
    {"identifier": "is.workflow.actions.ask",
     "name": "Ask for Input",
     "keywords": "ask prompt input user text enter"},
    {"identifier": "is.workflow.actions.alert",
     "name": "Show Alert",
     "keywords": "alert dialog popup confirm ok cancel"},
    {"identifier": "is.workflow.actions.showresult",
     "name": "Show Result",
     "keywords": "show result display output"},
    {"identifier": "is.workflow.actions.notification",
     "name": "Show Notification",
     "keywords": "notification banner alert push"},
    {"identifier": "is.workflow.actions.speaktext",
     "name": "Speak Text",
     "keywords": "speak speech voice tts text to speech"},
    {"identifier": "is.workflow.actions.setbrightness",
     "name": "Set Brightness",
     "keywords": "brightness display screen"},
    {"identifier": "is.workflow.actions.setvolume",
     "name": "Set Volume",
     "keywords": "volume audio loud"},
    {"identifier": "is.workflow.actions.vibrate",
     "name": "Vibrate Device",
     "keywords": "vibrate haptic buzz"},
    {"identifier": "is.workflow.actions.wifi.set",
     "name": "Set Wi-Fi",
     "keywords": "wifi wi-fi network toggle"},
    {"identifier": "is.workflow.actions.bluetooth.set",
     "name": "Set Bluetooth",
     "keywords": "bluetooth toggle"},
    {"identifier": "is.workflow.actions.airplanemode.set",
     "name": "Set Airplane Mode",
     "keywords": "airplane mode flight"},
    {"identifier": "is.workflow.actions.cellulardata.set",
     "name": "Set Cellular Data",
     "keywords": "cellular data mobile"},
    {"identifier": "is.workflow.actions.lowpowermode.set",
     "name": "Set Low Power Mode",
     "keywords": "low power battery save"},
    {"identifier": "is.workflow.actions.flashlight",
     "name": "Set Flashlight",
     "keywords": "flashlight torch light"},
    {"identifier": "is.workflow.actions.getbatterylevel",
     "name": "Get Battery Level",
     "keywords": "battery level power"},
    {"identifier": "is.workflow.actions.getdevicedetails",
     "name": "Get Device Details",
     "keywords": "device info details name model"},
    {"identifier": "is.workflow.actions.makezip",
     "name": "Make Archive",
     "keywords": "zip archive compress tar"},
    {"identifier": "is.workflow.actions.unzip",
     "name": "Extract Archive",
     "keywords": "unzip extract decompress archive"},
    {"identifier": "is.workflow.actions.getlastphoto",
     "name": "Get Latest Photos",
     "keywords": "photos latest recent camera roll"},
    {"identifier": "is.workflow.actions.scanbarcode",
     "name": "Scan QR/Barcode",
     "keywords": "qr barcode scan code"},
    {"identifier": "is.workflow.actions.share",
     "name": "Share",
     "keywords": "share sheet system"},
    {"identifier": "is.workflow.actions.airdropdocument",
     "name": "AirDrop",
     "keywords": "airdrop send transfer"},
    {"identifier": "is.workflow.actions.readinglist",
     "name": "Add to Reading List",
     "keywords": "reading list safari save"},
    {"identifier": "is.workflow.actions.sendmessage",
     "name": "Send Message",
     "keywords": "send message text sms imessage"},
    {"identifier": "is.workflow.actions.sendemail",
     "name": "Send Email",
     "keywords": "send email mail compose"},
    {"identifier": "is.workflow.actions.detect.contacts",
     "name": "Get Contacts from Input",
     "keywords": "contacts detect extract input"},
    {"identifier": "is.workflow.actions.format.date",
     "name": "Format Date",
     "keywords": "format date time custom"},
    {"identifier": "is.workflow.actions.text.changecase",
     "name": "Change Case",
     "keywords": "case uppercase lowercase capitalize"},
    {"identifier": "is.workflow.actions.text.match",
     "name": "Match Text",
     "keywords": "regex match pattern"},
    {"identifier": "is.workflow.actions.text.replace",
     "name": "Replace Text",
     "keywords": "replace substitute find"},
    {"identifier": "is.workflow.actions.text.split",
     "name": "Split Text",
     "keywords": "split divide separator lines spaces"},
    {"identifier": "is.workflow.actions.text.combine",
     "name": "Combine Text",
     "keywords": "combine join concatenate merge"},
    {"identifier": "is.workflow.actions.getitemfromlist",
     "name": "Get Item from List",
     "keywords": "first last index item list"},
    {"identifier": "is.workflow.actions.getclipboard",
     "name": "Get Clipboard",
     "keywords": "clipboard paste copy"},
    {"identifier": "is.workflow.actions.setclipboard",
     "name": "Set Clipboard",
     "keywords": "clipboard copy set"},
    {"identifier": "is.workflow.actions.getcurrentsong",
     "name": "Get Current Song",
     "keywords": "song music playing now"},
    {"identifier": "is.workflow.actions.pausemusic",
     "name": "Play/Pause Music",
     "keywords": "play pause music"},
    # Third-party entry points
    {"identifier": "com.sindresorhus.Actions.GenerateUUIDIntent",
     "name": "Generate UUID (Actions app)",
     "keywords": "uuid guid generate random unique sorhus"},
    {"identifier": "com.sindresorhus.Actions.FormatCurrencyIntent",
     "name": "Format Currency (Actions app)",
     "keywords": "currency format money usd eur sorhus"},
    {"identifier": "com.sindresorhus.Actions.ParseJSON5Intent",
     "name": "Parse JSON5 (Actions app)",
     "keywords": "json json5 parse sorhus"},
    {"identifier": "com.sindresorhus.Actions.AuthenticateIntent",
     "name": "Authenticate (Actions app)",
     "keywords": "authenticate faceid touchid gate sorhus"},
    {"identifier": "dk.simonbs.datajar.GetValueIntent",
     "name": "Data Jar: Get Value",
     "keywords": "data jar persistent get key"},
    {"identifier": "dk.simonbs.datajar.SetValueIntent",
     "name": "Data Jar: Set Value",
     "keywords": "data jar persistent set key store"},
    {"identifier": "dk.simonbs.Scriptable.RunScriptIntent",
     "name": "Scriptable: Run Script",
     "keywords": "scriptable javascript run script"},
    {"identifier": "dk.simonbs.Scriptable.RunInlineScriptIntent",
     "name": "Scriptable: Run Inline Script",
     "keywords": "scriptable javascript inline execute"},
    {"identifier": "de.sostudio.Pushcut.SendNotificationIntent",
     "name": "Pushcut: Send Notification",
     "keywords": "pushcut notification webhook"},
    {"identifier": "AsheKube.app.a-Shell.ExecuteCommandIntent",
     "name": "a-Shell: Execute command",
     "keywords": "a-shell shell bash unix command execute"},
]


@dataclass
class Match:
    """One search result."""

    identifier: str
    name: str
    score: float


def normalize(s: str) -> str:
    """Lowercase, strip whitespace."""
    return " ".join(s.lower().split())


def bag_of_words(s: str) -> set[str]:
    """Tokenize a string into a lowercased word set."""
    return {w for w in "".join(
        c if c.isalnum() or c.isspace() else " " for c in s.lower()
    ).split() if w}


def levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]


def score_entry(query: str, entry: dict[str, str]) -> float:
    """Combine Levenshtein (on name) with word overlap (on name+keywords).

    Higher is better. Range [0, ~2].
    """
    norm_query = normalize(query)
    norm_name = normalize(entry["name"])
    distance = levenshtein(norm_query, norm_name)
    max_len = max(len(norm_query), len(norm_name), 1)
    lev_score = 1.0 - distance / max_len

    query_words = bag_of_words(query)
    entry_words = bag_of_words(entry["name"] + " " + entry.get("keywords", ""))
    if query_words:
        overlap = len(query_words & entry_words)
        overlap_score = overlap / len(query_words)
    else:
        overlap_score = 0.0

    return lev_score * 0.4 + overlap_score * 1.0


def search(
    query: str,
    entries: Iterable[dict[str, str]],
    top_n: int,
    min_score: float,
) -> list[Match]:
    """Return top-N matches with score > min_score."""
    scored = [
        Match(
            identifier=e["identifier"],
            name=e["name"],
            score=score_entry(query, e),
        )
        for e in entries
    ]
    scored.sort(key=lambda m: m.score, reverse=True)
    return [m for m in scored[:top_n] if m.score >= min_score]


def emit_human(matches: list[Match]) -> None:
    """Print a human-readable table."""
    if not matches:
        print("No matches.")
        return
    for m in matches:
        print(f"  {m.score:.2f}  {m.identifier:<55} {m.name}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Fuzzy-search action identifiers by human name.",
    )
    parser.add_argument("query", help="Natural-language search query")
    parser.add_argument(
        "-n",
        "--top",
        type=int,
        default=5,
        help="Max matches (default: 5)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.15,
        help="Minimum combined score (default: 0.15)",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Python log level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    matches = search(args.query, CATALOG, args.top, args.min_score)

    if args.human:
        emit_human(matches)
    else:
        json.dump({
            "query": args.query,
            "matches": [
                {
                    "identifier": m.identifier,
                    "name": m.name,
                    "score": round(m.score, 4),
                }
                for m in matches
            ],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0 if matches else 1


if __name__ == "__main__":
    sys.exit(main())
