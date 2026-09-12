"""
analysis/realtime_sensing.py — real-time sensing layer for SylvaSense
=====================================================================

Lets a user type a location name and get a live environmental picture of that
place: a nearby green-cover survey (OpenStreetMap via Overpass), today's
satellite imagery (NASA GIBS), current weather + air quality (Open-Meteo),
nearby geotagged photos (Wikipedia), optional active-fire hotspots (NASA
FIRMS, needs a free MAP_KEY), and an auto-written summary report.

Design notes
------------
- Everything is REAL data from free, keyless public APIs — nothing mocked —
  so this page keeps working on Streamlit Community Cloud with zero secrets.
- Every fetcher is defensive: short timeout, single retry, and a graceful
  miss ("(no data)") instead of an exception. One dead endpoint must never
  take down the report.
- Overpass is rate-limited, so results are cached on disk under
  outputs/realtime_cache/ keyed by a normalized query.
- Mirrors the repo's mock/demo conventions (datetime, dataclasses, Path).
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows console (cp1252) can't print Δ/·/— glyphs; demo_run.py handles the
# same issue by reconfiguring stdout, so follow that repo convention.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "outputs" / "realtime_cache"

DEFAULT_TIMEOUT = 12  # seconds per HTTP attempt
USER_AGENT = "ArborPulse-SylvaSense/1.0 (educational hackathon demo)"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_TIMEOUT = 25  # seconds per mirror attempt (mirrors are raced, not summed)

# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------


def _http_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 1,
):
    """Fetch JSON with a UA header, timeout, and one silent retry."""
    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("User-Agent", USER_AGENT)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001 — deliberate: degrade, don't crash
            last_err = e
    raise ConnectionError(f"{url[:80]}... failed: {last_err}")


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# 1. Geocoding — typed location → coordinates + display name
# ---------------------------------------------------------------------------


@dataclass
class GeoResult:
    """A resolved location from the geocoder."""

    name: str
    lat: float
    lon: float
    country: str | None = None
    admin1: str | None = None
    source: str = "open-meteo"

    @property
    def display(self) -> str:
        parts = [self.name]
        if self.admin1:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


def geocode(query: str, count: int = 5) -> list[GeoResult]:
    """Resolve a typed location to candidate coordinates (Open-Meteo geocoder).

    Falls back to Nominatim (OSM) if Open-Meteo returns nothing, so unusual
    POI-style queries still resolve.
    """
    query = (query or "").strip()
    if not query:
        return []
    try:
        payload = _http_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": query, "count": count, "language": "en", "format": "json"})
        )
        results = [
            GeoResult(
                name=r.get("name", query),
                lat=float(r["latitude"]),
                lon=float(r["longitude"]),
                country=r.get("country"),
                admin1=r.get("admin1"),
                source="open-meteo",
            )
            for r in payload.get("results", [])
        ]
        if results:
            return results
    except Exception:  # noqa: BLE001 — fall through to Nominatim
        pass

    try:
        payload = _http_json(
            "https://nominatim.openstreetmap.org/search?"
            + urllib.parse.urlencode({"q": query, "format": "json", "limit": count})
        )
        names = r.get("display_name", "").split(",")
        return [
            GeoResult(
                name=r.get("name") or (names[0].strip() or query),
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                admin1=names[-3].strip() if len(names) >= 3 else None,
                country=(names[-1].strip() or None),
                source="nominatim",
            )
            for r in payload
        ]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# 2. Nearby survey — OpenStreetMap green-cover census via Overpass
# ---------------------------------------------------------------------------

SURVEY_KEYS = (
    ("natural", ("wood", "scrub", "heath", "grassland", "wetland", "tree", "tree_row")),
    ("landuse", ("forest", "grass", "meadow", "orchard", "farmland", "village_green", "recreation_ground")),
    ("leisure", ("park", "garden", "golf_course", "nature_reserve", "pitch")),
    ("boundary", ("national_park", "protected_area")),
)


@dataclass
class SurveyFeature:
    """One green/land feature found near the location."""

    osm_type: str  # node | way | relation
    osm_id: int
    name: str | None
    category: str  # e.g. "forest", "park"
    lat: float | None
    lon: float | None
    distance_km: float | None

    def to_row(self) -> dict:
        return {
            "Name": self.name or "(unnamed)",
            "Category": self.category,
            "Type": self.osm_type,
            "Distance (km)": round(self.distance_km, 2) if self.distance_km is not None else None,
            "Lat": round(self.lat, 5) if self.lat is not None else None,
            "Lon": round(self.lon, 5) if self.lon is not None else None,
        }


@dataclass
class SurveyResult:
    """Aggregated OSM green-cover survey around a point."""

    center: GeoResult
    radius_m: int
    features: list[SurveyFeature] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    named_count: int = 0
    total: int = 0
    source: str | None = None
    note: str | None = None

    @property
    def green_score(self) -> float | None:
        """0-1 proxy for local green-cover density (heuristic, survey-sized)."""
        if not self.total:
            return None
        # Heavy weight for true forest/woodland, medium for protected areas,
        # light for urban greenery; squashed with a saturating curve.
        heavy = self.counts.get("forest", 0) + self.counts.get("wood", 0)
        medium = (
            self.counts.get("national_park", 0)
            + self.counts.get("protected_area", 0)
            + self.counts.get("nature_reserve", 0)
            + self.counts.get("wetland", 0)
        )
        light = self.total - heavy - medium
        weighted = 3.0 * heavy + 2.0 * medium + 1.0 * max(light, 0)
        return _clip(1.0 - math.exp(-weighted / 12.0))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    """One Overpass query covering every SURVEY_KEYS filter at once.

    Overpass can't OR values inside a single tag filter, so emit one `nwr`
    clause per key with a regex alternation over that key's values.
    """
    parts = [
        f'nwr["{k}"~"^({"|".join(re.escape(v) for v in values)})$"](around:{radius_m},{lat:.5f},{lon:.5f});'
        for k, values in SURVEY_KEYS
    ]
    return "[out:json][timeout:25];(" + "".join(parts) + ");out center 400;"


def _survey_cache_file(lat: float, lon: float, radius_m: int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"survey_{lat:.3f}_{lon:.3f}_{radius_m}.json"


def _survey_from_cache(path: Path) -> SurveyResult | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    feats = [SurveyFeature(**f) for f in raw.get("features", [])]
    return SurveyResult(
        center=None,
        radius_m=raw.get("radius_m", 5000),
        features=feats,
        counts=raw.get("counts", {}),
        named_count=raw.get("named_count", 0),
        total=raw.get("total", len(feats)),
        source=raw.get("source"),
        note="served from local cache (Overpass was rate-limiting at request time).",
    )


def _survey_to_cache(path: Path, result: SurveyResult) -> None:
    try:
        path.write_text(
            json.dumps(
                {
                    "radius_m": result.radius_m,
                    "features": [vars(f) for f in result.features],
                    "counts": result.counts,
                    "named_count": result.named_count,
                    "total": result.total,
                    "source": result.source,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def fetch_nearby_survey(lat: float, lon: float, radius_m: int = 5000) -> SurveyResult:
    """Census of green/land features around a point from OpenStreetMap.

    Both Overpass mirrors are raced concurrently and the first valid response
    wins, so a rate-limited primary can't stall the report. Successful surveys
    are cached on disk, so a later rate-limited attempt still returns the last
    good census instead of an empty report.
    """
    q = _build_overpass_query(lat, lon, radius_m)

    def _try(endpoint: str):
        if endpoint.endswith("kumi.systems/api/interpreter"):
            url = endpoint + "?" + urllib.parse.urlencode({"data": q})
            return _http_json(url, timeout=OVERPASS_TIMEOUT, retries=0)
        return _http_json(
            endpoint,
            method="POST",
            data=urllib.parse.urlencode({"data": q}).encode("utf-8"),
            timeout=OVERPASS_TIMEOUT,
            retries=0,
        )

    data = None
    used = None
    with ThreadPoolExecutor(max_workers=len(OVERPASS_ENDPOINTS)) as pool:
        futures = {pool.submit(_try, ep): ep for ep in OVERPASS_ENDPOINTS}
        for fut in futures:
            try:
                data = fut.result()
                used = futures[fut]
                break  # first mirror to return valid JSON wins
            except Exception:  # noqa: BLE001 — another mirror may still succeed
                continue
    if data is None:
        cached = _survey_from_cache(_survey_cache_file(lat, lon, radius_m))
        if cached is not None:
            return cached
        return SurveyResult(
            center=None,
            radius_m=radius_m,
            note="OpenStreetMap Overpass is rate-limiting right now — survey unavailable (try again in a minute)",
        )

    center = GeoResult(name="(survey center)", lat=lat, lon=lon)
    feats: list[SurveyFeature] = []
    counts: dict[str, int] = {}
    for el in data.get("elements", [])[:400]:
        tags = el.get("tags", {}) or {}
        category = None
        for key, values in SURVEY_KEYS:
            v = tags.get(key)
            if v and v in values:
                category = v
                break
        if category is None:
            continue
        el_type = el.get("type", "node")
        el_id = el.get("id", 0)
        elat = el.get("lat") or (el.get("center") or {}).get("lat")
        elon = el.get("lon") or (el.get("center") or {}).get("lon")
        dist = _haversine_km(lat, lon, elat, elon) if elat is not None else None
        feats.append(
            SurveyFeature(
                osm_type=el_type,
                osm_id=el_id,
                name=tags.get("name"),
                category=category,
                lat=elat,
                lon=elon,
                distance_km=dist,
            )
        )
        counts[category] = counts.get(category, 0) + 1
    feats.sort(key=lambda f: (f.distance_km is None, f.distance_km))
    named = sum(1 for f in feats if f.name)
    result = SurveyResult(
        center=center,
        radius_m=radius_m,
        features=feats,
        counts=counts,
        named_count=named,
        total=len(feats),
        source=used,
    )
    _survey_to_cache(_survey_cache_file(lat, lon, radius_m), result)
    return result


# ---------------------------------------------------------------------------
# 3. Satellite imagery — today's NASA GIBS true-color tiles
# ---------------------------------------------------------------------------


def _deg2num(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


GIBS_MAX_ZOOM = 9  # MODIS products cap at Level 9


def satellite_image_url(lat: float, lon: float, zoom: int = 8, date: str | None = None) -> str:
    """URL of today's (or a given day's) MODIS Terra true-color tile around lat/lon."""
    zoom = min(zoom, GIBS_MAX_ZOOM)
    x, y = _deg2num(lat, lon, zoom)
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
        f"MODIS_Terra_CorrectedReflectance_TrueColor/default/{day}/"
        f"GoogleMapsCompatible_Level9/{zoom}/{y}/{x}.jpg"
    )


def satellite_dates_fallback(lat: float, lon: float, days_back: int = 6) -> list[str]:
    """Recent candidate dates so a cloudy day can be swapped for a clearer one."""
    base = datetime.now(timezone.utc)
    return [(base - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back)]


def fetch_satellite_tile(lat: float, lon: float, zoom: int = 8, date: str | None = None) -> tuple[str, str] | None:
    """Return (url, date) for the first recent date whose tile actually exists."""
    for day in satellite_dates_fallback(lat, lon, days_back=6):
        url = satellite_image_url(lat, lon, zoom=zoom, date=day)
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", USER_AGENT)
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                if resp.status == 200:
                    return url, day
        except Exception:  # noqa: BLE001 — try the previous day
            continue
    return None


# ---------------------------------------------------------------------------
# 4. Weather + air quality — Open-Meteo (current conditions)
# ---------------------------------------------------------------------------

WEATHER_VARS = "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,cloud_cover"
AQ_VARS = "pm10,pm2_5,carbon_monoxide,aerosol_optical_depth"


@dataclass
class ConditionsResult:
    """Current weather + air-quality snapshot."""

    temperature_c: float | None = None
    humidity_pct: float | None = None
    precipitation_mm: float | None = None
    wind_ms: float | None = None
    cloud_pct: float | None = None
    pm10: float | None = None
    pm2_5: float | None = None
    co: float | None = None
    aod: float | None = None
    note: str | None = None


def fetch_conditions(lat: float, lon: float) -> ConditionsResult:
    """Current weather and air quality. Each half degrades independently."""
    out = ConditionsResult()
    try:
        w = _http_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {"latitude": lat, "longitude": lon, "current": WEATHER_VARS, "wind_speed_unit": "ms"}
            )
        )["current"]
        out.temperature_c = w.get("temperature_2m")
        out.humidity_pct = w.get("relative_humidity_2m")
        out.precipitation_mm = w.get("precipitation")
        out.wind_ms = w.get("wind_speed_10m")
        out.cloud_pct = w.get("cloud_cover")
    except Exception as e:  # noqa: BLE001
        out.note = f"weather unavailable ({e})"
    try:
        a = _http_json(
            "https://air-quality-api.open-meteo.com/v1/air-quality?"
            + urllib.parse.urlencode({"latitude": lat, "longitude": lon, "current": AQ_VARS})
        )["current"]
        out.pm10 = a.get("pm10")
        out.pm2_5 = a.get("pm2_5")
        out.co = a.get("carbon_monoxide")
        out.aod = a.get("aerosol_optical_depth")
    except Exception as e:  # noqa: BLE001
        note = f"air quality unavailable ({e})"
        out.note = f"{out.note}; {note}" if out.note else note
    return out


# ---------------------------------------------------------------------------
# 5. Nearby images — Wikipedia geosearch thumbnails
# ---------------------------------------------------------------------------


@dataclass
class NearbyImage:
    title: str
    thumb_url: str
    lat: float | None
    lon: float | None
    page_url: str | None

    def to_row(self) -> dict:
        return {"Title": self.title, "Lat": self.lat, "Lon": self.lon}


def fetch_nearby_images(lat: float, lon: float, radius_m: int = 10000, limit: int = 8) -> list[NearbyImage]:
    """Geotagged Wikipedia photos within a radius (great human-ground-truth proxy)."""
    try:
        payload = _http_json(
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "query",
                    "format": "json",
                    "generator": "geosearch",
                    "ggscoord": f"{lat}|{lon}",
                    "ggsradius": min(radius_m, 10000),
                    "ggslimit": limit,
                    "prop": "pageimages|coordinates",
                    "piprop": "thumbnail",
                    "pithumbsize": 400,
                }
            )
        )
    except Exception:  # noqa: BLE001
        return []
    pages = payload.get("query", {}).get("pages", {})
    images: list[NearbyImage] = []
    for p in pages.values():
        thumb = (p.get("thumbnail") or {}).get("source")
        coords = (p.get("coordinates") or [{}])[0]
        images.append(
            NearbyImage(
                title=p.get("title", "(untitled)"),
                thumb_url=thumb,
                lat=coords.get("lat"),
                lon=coords.get("lon"),
                page_url=f"https://en.wikipedia.org/?curid={p.get('pageid')}" if p.get("pageid") else None,
            )
        )
    images.sort(key=lambda im: im.title.lower())
    return images


# ---------------------------------------------------------------------------
# 6. Fire hotspots — NASA FIRMS (optional MAP_KEY, free registration)
# ---------------------------------------------------------------------------

FIRMS_KEY_FILE = REPO_ROOT / "outputs" / "firms_map_key.txt"


def get_firms_key() -> str | None:
    """Read the optional FIRMS MAP_KEY from env or outputs/firms_map_key.txt."""
    import os

    key = os.environ.get("FIRMS_MAP_KEY")
    if key:
        return key.strip()
    try:
        return FIRMS_KEY_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def fetch_fire_hotspots(lat: float, lon: float, radius_deg: float = 0.5, days: int = 2):
    """Active-fire hotspots (VIIRS) via FIRMS. Returns (rows, note)."""
    key = get_firms_key()
    if not key:
        return [], "FIRMS MAP_KEY not configured (free at firms.modaps.eosdis.nasa.gov) — fire layer disabled."
    url = (
        f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/"
        f"{lat - radius_deg},{lon - radius_deg},{lat + radius_deg},{lon + radius_deg}/{days}"
    )
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", USER_AGENT)
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
    except Exception as e:  # noqa: BLE001
        return [], f"FIRMS request failed: {e}"
    if text.lower().startswith("invalid"):
        return [], "FIRMS rejected the MAP_KEY — fire layer disabled."
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return [], f"No active fire hotspots within ~{radius_deg * 111:.0f} km in the last {days} days."
    rows = []
    for ln in lines[1:201]:
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "lat": float(parts[0]),
                "lon": float(parts[1]),
                "confidence": parts[8] if len(parts) > 8 else "?",
                "acq_time": f"{parts[5]} {parts[6]}" if len(parts) > 6 else "?",
            }
        )
    return rows, f"{len(rows)} active-fire hotspot(s) in the last {days} days (VIIRS S-NPP, NRT)."


# ---------------------------------------------------------------------------
# 7. Summary report — the auto-written narrative the user asked for
# ---------------------------------------------------------------------------


@dataclass
class RealtimeReport:
    """Everything the dashboard needs for one location, plus the written report."""

    place: GeoResult | None
    survey: SurveyResult | None
    satellite: tuple[str, str] | None  # (url, date)
    conditions: ConditionsResult | None
    images: list[NearbyImage]
    fires: list[dict]
    fires_note: str | None
    summary_text: str
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "place": {"name": self.place.display, "lat": self.place.lat, "lon": self.place.lon} if self.place else None,
            "survey": {
                "radius_m": self.survey.radius_m,
                "total_features": self.survey.total,
                "named": self.survey.named_count,
                "counts": self.survey.counts,
            }
            if self.survey
            else None,
            "satellite_date": self.satellite[1] if self.satellite else None,
            "conditions": vars(self.conditions) if self.conditions else None,
            "images": [vars(im) for im in self.images],
            "fires": self.fires,
            "fires_note": self.fires_note,
            "summary": self.summary_text,
            "generated_at": self.generated_at,
        }


def _gaze(categories: dict[str, int]) -> str:
    """One-line OSM category summary, e.g. '6 parks, 2 forests, 1 garden'."""
    if not categories:
        return "no tagged green/land features found"
    nice = {
        "forest": "forest tracts", "wood": "woodlands", "park": "parks",
        "garden": "gardens", "grassland": "grasslands", "grass": "grass areas",
        "meadow": "meadows", "orchard": "orchards", "nature_reserve": "nature reserves",
        "national_park": "national parks", "protected_area": "protected areas",
        "wetland": "wetlands", "scrub": "scrubland", "heath": "heathland",
        "tree": "recorded trees", "tree_row": "tree rows",
        "golf_course": "golf courses", "pitch": "sports pitches",
        "farmland": "farmland", "village_green": "village greens",
        "recreation_ground": "recreation grounds", "boundary": "boundary areas",
    }
    bits = [f"{n} {nice.get(cat, cat)}" for cat, n in sorted(categories.items(), key=lambda kv: -kv[1])]
    return ", ".join(bits[:6])


def build_report(place: GeoResult, radius_m: int = 5000, firms: bool = True) -> RealtimeReport:
    """Fetch everything for one location and write the summary narrative.

    All sensors run concurrently (ThreadPoolExecutor), so the report waits for
    the *slowest* source rather than the sum of all of them — and each source
    degrades independently to a graceful miss instead of killing the report.
    """

    def _safe(fn, *args, default=None):
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001 — one failed sensor must not kill the report
            return default

    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_survey = pool.submit(_safe, fetch_nearby_survey, place.lat, place.lon, radius_m)
        fut_sat = pool.submit(_safe, fetch_satellite_tile, place.lat, place.lon, 8)
        fut_conditions = pool.submit(_safe, fetch_conditions, place.lat, place.lon)
        fut_images = pool.submit(_safe, fetch_nearby_images, place.lat, place.lon)
        fut_fires = pool.submit(_safe, fetch_fire_hotspots, place.lat, place.lon) if firms else None

    survey = fut_survey.result()
    sat = fut_sat.result()
    conditions = fut_conditions.result()
    images = fut_images.result() or []
    fires_res = fut_fires.result() if fut_fires is not None else None
    if fires_res is not None:
        fires, fires_note = fires_res
    else:
        fires, fires_note = [], "fire layer skipped." if fut_fires is None else "fire hotspots unavailable."

    lines: list[str] = []
    lines.append(
        f"Real-time environmental snapshot for {place.display} "
        f"(lat {place.lat:.4f}, lon {place.lon:.4f}), generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."
    )

    # Survey narrative
    if survey and survey.total:
        lines.append(
            f"Nearby survey (OpenStreetMap, {survey.radius_m / 1000:.0f} km radius): {survey.total} green/land features, "
            f"{survey.named_count} named — {_gaze(survey.counts)}."
        )
    elif survey:
        note = (survey.note or "no tagged green/land features found in radius").rstrip(".")
        lines.append(f"Nearby survey: {note}.")
    else:
        lines.append("Nearby survey unavailable right now.")

    # Satellite narrative
    if sat:
        lines.append(f"Satellite imagery: NASA GIBS MODIS Terra true color, latest clear composite dated {sat[1]}.")
    else:
        lines.append("Satellite imagery: no tile available for the last 6 days (check network).")

    # Conditions narrative
    if conditions:
        bits = []
        if conditions.temperature_c is not None:
            bits.append(f"{conditions.temperature_c:.1f} °C")
        if conditions.humidity_pct is not None:
            bits.append(f"{conditions.humidity_pct:.0f}% humidity")
        if conditions.precipitation_mm is not None:
            bits.append(f"{conditions.precipitation_mm:.1f} mm precipitation")
        if conditions.wind_ms is not None:
            bits.append(f"wind {conditions.wind_ms:.1f} m/s")
        if conditions.cloud_pct is not None:
            bits.append(f"{conditions.cloud_pct:.0f}% cloud cover")
        aq_bits = []
        if conditions.pm2_5 is not None:
            aq_bits.append(f"PM2.5 {conditions.pm2_5:.0f}")
        if conditions.pm10 is not None:
            aq_bits.append(f"PM10 {conditions.pm10:.0f} µg/m³")
        if conditions.aod is not None:
            aq_bits.append(f"aerosol optical depth {conditions.aod:.2f}")
        cond_line = "Current conditions: " + ", ".join(bits) + "." if bits else "Current conditions: unavailable."
        if aq_bits:
            cond_line += " Air quality: " + ", ".join(aq_bits) + "."
        if conditions.note:
            cond_line += f" ({conditions.note})"
        lines.append(cond_line)

    # Fire narrative
    if fires:
        lines.append(f"🔥 {fires_note} Fire near forest edge is the leading near-real-time deforestation signal.")
    else:
        lines.append(f"Fire: {fires_note}")

    # Synthesis
    n_feats = survey.total if survey else 0
    heavy = (survey.counts.get("forest", 0) + survey.counts.get("wood", 0) + survey.counts.get("national_park", 0)) if survey else 0
    if n_feats == 0:
        cover_phrase = "little tagged green cover in OSM"
    elif heavy >= 3 or n_feats >= 40:
        cover_phrase = "a rich local green footprint — " + _gaze(survey.counts)
    elif n_feats >= 8:
        cover_phrase = "substantial green cover — " + _gaze(survey.counts)
    else:
        cover_phrase = "sparse OSM-mapped green cover — " + _gaze(survey.counts)
    lines.append(
        f"Summary: {place.display} currently shows {cover_phrase}. "
        f"Satellite composite is from {sat[1] if sat else 'n/a'}; "
        f"conditions are {f'{conditions.temperature_c:.0f} °C with {conditions.cloud_pct:.0f}% cloud' if conditions and conditions.temperature_c is not None else 'unavailable'}. "
        + ("Consider the fire hotspots when weighing recent disturbance." if fires else "No near-real-time fire signal above threshold.")
    )

    return RealtimeReport(
        place=place,
        survey=survey,
        satellite=sat,
        conditions=conditions,
        images=images,
        fires=fires,
        fires_note=fires_note,
        summary_text="\n\n".join(lines),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# CLI sanity check: python -m analysis.realtime_sensing "Manaus"
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "Manaus"
    candidates = geocode(query)
    if not candidates:
        print(f"No geocode results for {query!r}.")
        raise SystemExit(1)
    place = candidates[0]
    print(f"Geocoded: {place.display} ({place.lat:.4f}, {place.lon:.4f}) via {place.source}")
    report = build_report(place)
    print(report.summary_text)
    print(f"\nNearby images: {len(report.images)}")
    for im in report.images[:3]:
        print(f"  - {im.title}: {im.thumb_url[:80] if im.thumb_url else '(no thumb)'}")
