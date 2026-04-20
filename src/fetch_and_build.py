"""
nasa-events-ics: fetch_and_build.py
Fetches upcoming NASA-related launches and space events from
the Launch Library 2 API and writes a valid .ics calendar file.

Sources:
  - https://ll2.thespacedevs.com/2.3.0/launches/upcoming/
    (filtered to NASA and NASA-affiliated missions)
  - https://ll2.thespacedevs.com/2.3.0/events/upcoming/
    (spacewalks, briefings, dockings, etc.)

Output: calendar/nasa-events.ics
"""

import os
import sys
import logging
import hashlib
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timezone, timedelta
from icalendar import Calendar, Event, vText, vDatetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://ll2.thespacedevs.com/2.3.0"

LAUNCHES_ENDPOINT = f"{BASE_URL}/launches/upcoming/"
EVENTS_ENDPOINT   = f"{BASE_URL}/events/upcoming/"

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "calendar", "nasa-events.ics"
)

# Fetch this many months ahead
LOOKAHEAD_MONTHS = 6

# NASA agency IDs in LL2 (44 = NASA)
NASA_AGENCY_IDS = {44}

# Keywords to catch NASA-affiliated missions by name when agency filter misses
NASA_KEYWORDS = {"nasa", "artemis", "orion", "gateway", "iss", "international space station"}

# Request headers — identify our app politely
HEADERS = {
    "User-Agent": "nasa-events-ics/1.0 (github.com/schema-syntax/nasa-events-ics)"
}

TIMEOUT = 20  # seconds per request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_paginated(url: str, params: dict) -> list[dict]:
    """Walk through paginated LL2 results, return all items."""
    results = []
    next_url = url
    page = 1

    while next_url:
        log.info(f"  GET page {page}: {next_url}")
        try:
            resp = requests.get(
                next_url,
                params=params if page == 1 else None,
                headers=HEADERS,
                timeout=TIMEOUT,
                verify=False,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error(f"Request failed: {exc}")
            sys.exit(1)

        data = resp.json()
        results.extend(data.get("results", []))
        next_url = data.get("next")
        page += 1

    return results


def fetch_launches(window_end: str) -> list[dict]:
    """Fetch upcoming launches associated with NASA."""
    log.info("Fetching launches...")

    now = datetime.now(timezone.utc).isoformat()

    # Pass 1: NASA as launch service provider (lsp__id is the correct v2.3 param)
    params_lsp = {
        "format": "json",
        "limit": 100,
        "net__gte": now,
        "net__lte": window_end,
        "lsp__id": 44,
    }
    lsp_launches = fetch_paginated(LAUNCHES_ENDPOINT, params_lsp)

    # Pass 2: broader fetch, keyword-filter client-side — catches commercial
    # crew, CLPS, etc. where NASA is mission agency but not launch provider
    params_broad = {
        "format": "json",
        "limit": 100,
        "net__gte": now,
        "net__lte": window_end,
    }
    broad = fetch_paginated(LAUNCHES_ENDPOINT, params_broad)
    nasa_broad = [l for l in broad if _is_nasa_related(l)]

    # Merge, deduplicate by id
    seen = set()
    merged = []
    for item in lsp_launches + nasa_broad:
        if item["id"] not in seen:
            seen.add(item["id"])
            merged.append(item)

    log.info(f"  {len(merged)} NASA-related launches found")
    return merged


def fetch_events(window_end: str) -> list[dict]:
    """Fetch upcoming space events (EVAs, dockings, briefings, etc.)."""
    log.info("Fetching events...")
    params = {
        "format": "json",
        "limit": 100,
        "date__gte": datetime.now(timezone.utc).isoformat(),
        "date__lte": window_end,
    }
    events = fetch_paginated(EVENTS_ENDPOINT, params)

    # Filter to NASA-relevant events
    nasa_events = [e for e in events if _is_nasa_event(e)]
    log.info(f"  {len(nasa_events)} NASA-relevant events found")
    return nasa_events


def _is_nasa_related(launch: dict) -> bool:
    """Return True if a launch is NASA-related by agency or keyword."""
    # Check launch service provider
    lsp = launch.get("launch_service_provider") or {}
    if lsp.get("id") in NASA_AGENCY_IDS:
        return True

    # Check mission agencies
    mission = launch.get("mission") or {}
    for agency in mission.get("agencies", []):
        if agency.get("id") in NASA_AGENCY_IDS:
            return True

    # Keyword match on name
    name = (launch.get("name") or "").lower()
    return any(kw in name for kw in NASA_KEYWORDS)


def _is_nasa_event(event: dict) -> bool:
    """Return True if a space event involves NASA."""
    name = (event.get("name") or "").lower()
    desc = (event.get("description") or "").lower()
    text = name + " " + desc
    return any(kw in text for kw in NASA_KEYWORDS)


# ---------------------------------------------------------------------------
# iCal generation
# ---------------------------------------------------------------------------

def stable_uid(source: str, item_id: str) -> str:
    """
    Generate a stable UID for a calendar event so that calendar clients
    treat refreshed entries as updates, not duplicates.
    Format: <hash>-<source>@nasa-events-ics
    """
    digest = hashlib.md5(f"{source}:{item_id}".encode()).hexdigest()[:8]
    return f"{digest}-{source}@nasa-events-ics"


def launch_to_vevent(launch: dict) -> Event:
    """Convert a LL2 launch object to an icalendar Event."""
    ev = Event()

    ev.add("uid", stable_uid("launch", launch["id"]))

    # Title
    name = launch.get("name") or "NASA Launch"
    status = (launch.get("status") or {}).get("name", "")
    title = f"🚀 {name}" + (f" [{status}]" if status else "")
    ev.add("summary", title)

    # Timing — prefer window_start/window_end, fall back to net
    dtstart_raw = launch.get("window_start") or launch.get("net")
    dtend_raw   = launch.get("window_end")   or launch.get("net")

    if dtstart_raw:
        dtstart = datetime.fromisoformat(dtstart_raw.replace("Z", "+00:00"))
        ev.add("dtstart", dtstart)
    if dtend_raw:
        dtend = datetime.fromisoformat(dtend_raw.replace("Z", "+00:00"))
        # If window is zero-length (NET only), give it a 1-hour block
        if dtend == dtstart:
            dtend = dtstart + timedelta(hours=1)
        ev.add("dtend", dtend)

    # Description
    mission  = launch.get("mission") or {}
    pad      = launch.get("pad") or {}
    location = (pad.get("location") or {}).get("name", "")
    provider = (launch.get("launch_service_provider") or {}).get("name", "")
    mission_desc = mission.get("description") or ""
    url      = launch.get("url") or ""

    desc_parts = []
    if provider:
        desc_parts.append(f"Provider: {provider}")
    if location:
        desc_parts.append(f"Launch site: {location}")
    if mission_desc:
        desc_parts.append(f"\n{mission_desc}")
    if url:
        desc_parts.append(f"\nDetails: {url}")

    ev.add("description", "\n".join(desc_parts))

    if location:
        ev.add("location", location)

    if url:
        ev.add("url", url)

    ev.add("dtstamp", datetime.now(timezone.utc))

    return ev


def space_event_to_vevent(event: dict) -> Event:
    """Convert a LL2 event object to an icalendar Event."""
    ev = Event()

    ev.add("uid", stable_uid("event", str(event["id"])))

    # Title — use type name as prefix if available
    event_type = (event.get("type") or {}).get("name", "")
    name = event.get("name") or "NASA Event"
    prefix = {
        "EVA": "🧑‍🚀",
        "Docking": "🛸",
        "Landing": "🛬",
        "Undocking": "🛸",
        "Press Conference": "🎙",
    }.get(event_type, "📡")
    ev.add("summary", f"{prefix} {name}")

    # Timing — events have a single `date` field
    date_raw = event.get("date")
    if date_raw:
        dtstart = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        ev.add("dtstart", dtstart)
        # Duration unknown — block 2 hours as a reasonable default
        ev.add("dtend", dtstart + timedelta(hours=2))

    # Description
    desc = event.get("description") or ""
    url  = event.get("url") or ""
    desc_parts = []
    if event_type:
        desc_parts.append(f"Type: {event_type}")
    if desc:
        desc_parts.append(f"\n{desc}")
    if url:
        desc_parts.append(f"\nDetails: {url}")

    ev.add("description", "\n".join(desc_parts))

    if url:
        ev.add("url", url)

    ev.add("dtstamp", datetime.now(timezone.utc))

    return ev


def build_calendar(launches: list[dict], events: list[dict]) -> Calendar:
    """Assemble the full iCal Calendar object."""
    cal = Calendar()
    cal.add("prodid", "-//schema-syntax//nasa-events-ics//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "NASA Events")
    cal.add("x-wr-caldesc",
            "Upcoming NASA launches and space events. "
            "Auto-generated daily from Launch Library 2. "
            "github.com/schema-syntax/nasa-events-ics")
    cal.add("x-wr-timezone", "UTC")
    cal.add("refresh-interval;value=duration", "PT12H")
    cal.add("x-published-ttl", "PT12H")

    for launch in launches:
        try:
            cal.add_component(launch_to_vevent(launch))
        except Exception as exc:
            log.warning(f"Skipping launch {launch.get('id')}: {exc}")

    for event in events:
        try:
            cal.add_component(space_event_to_vevent(event))
        except Exception as exc:
            log.warning(f"Skipping event {event.get('id')}: {exc}")

    return cal


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(timezone.utc)
    window_end = (now + timedelta(days=LOOKAHEAD_MONTHS * 30)).isoformat()

    log.info(f"Building NASA events calendar — window: now → {window_end[:10]}")

    launches = fetch_launches(window_end)
    events   = fetch_events(window_end)

    if not launches and not events:
        log.warning("No events fetched — calendar will be empty. Check API connectivity.")

    cal = build_calendar(launches, events)

    out_path = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "wb") as f:
        f.write(cal.to_ical())

    total = len(launches) + len(events)
    log.info(f"Written {total} events ({len(launches)} launches, {len(events)} space events) → {out_path}")


if __name__ == "__main__":
    main()
