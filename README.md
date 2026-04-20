# nasa-events-ics

A self-updating iCal feed of upcoming NASA launches and space events.

Subscribe once — your calendar client polls for updates automatically.

---

## Subscribe

Paste this URL into any calendar app that supports iCal subscriptions:

```
https://schema-syntax.github.io/nasa-events-ics/calendar/nasa-events.ics
```

| App | How to subscribe |
|---|---|
| **Proton Calendar** | Settings → Add calendar → From URL |
| **Google Calendar** | + Other calendars → From URL |
| **Apple Calendar** | File → New Calendar Subscription |
| **Thunderbird** | New Calendar → On the Network → iCal |

> Calendar clients vary in how often they poll for updates. Most check every 24 hours. The feed itself refreshes daily at ~06:00 UTC.

---

## What's included

Events are sourced from the [Launch Library 2 API](https://thespacedevs.com/llapi) (The Space Devs):

- **Launches** — all upcoming missions where NASA is the launch provider or a primary mission agency, plus commercial crew and CLPS missions
- **Space events** — EVAs (spacewalks), ISS dockings/undockings, press conferences, and other non-launch milestones

The lookahead window is **6 months**.

---

## How it works

```
GitHub Actions cron (daily 06:00 UTC)
    └── src/fetch_and_build.py
            ├── GET /launches/upcoming/   (Launch Library 2 v2.3)
            ├── GET /events/upcoming/     (Launch Library 2 v2.3)
            ├── filter to NASA-related entries
            ├── normalize → VEVENT objects with stable UIDs
            └── write calendar/nasa-events.ics → commit → push
```

GitHub Pages serves `calendar/nasa-events.ics` at a stable public URL.

Stable UIDs mean your calendar client treats refreshed entries as **updates**, not duplicates.

---

## Local development

```bash
git clone https://github.com/schema-syntax/nasa-events-ics.git
cd nasa-events-ics
pip install -r requirements.txt
python src/fetch_and_build.py
# Output: calendar/nasa-events.ics
```

---

## Data source

All event data is provided by [The Space Devs](https://thespacedevs.com/) via the Launch Library 2 API, free and open to the public. Rate limits apply to unauthenticated requests; this pipeline runs once daily and stays well within them.

---

## Extending

Want to add a second source (NOAA satellite ops, ESA events, rocket lab manifests)? The architecture is additive:

1. Add a `fetch_<source>()` function in `src/fetch_and_build.py`
2. Add a `<source>_to_vevent()` normalizer
3. Call both from `main()` and pass to `build_calendar()`

Each source gets its own UID namespace via `stable_uid("<source>", id)` so there are no collisions.

---

*Part of [schema-syntax](https://github.com/schema-syntax) — a collection of self-contained data and utility tools.*
