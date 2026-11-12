#!/usr/bin/env python3
"""Collecteur d'offres finance.

Pour chaque entreprise de sources.yaml : appelle le connecteur de sa plateforme de recrutement
(ou détecte la plateforme à partir de sa page carrières), garde les métiers finance, classe
chaque offre, puis écrit :
  site/data/jobs.json   - toutes les offres actives
  site/data/feed.xml    - flux RSS des 100 offres les plus récentes

Usage :
  python scraper/scrape.py                   # collecte complète
  python scraper/scrape.py --check           # teste chaque source sans rien écrire
  python scraper/scrape.py --only "BNP,Citi" # ne collecte que ces entreprises (debug)
  python scraper/scrape.py --seed FILE       # importe un fichier "entreprise | titre | lieu | date | url"
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from classify import (classify_contract, classify_specialisation, parse_location,  # noqa: E402
                      parse_start)
from connectors import (CONNECTORS, SEARCH_TERMS, http, jobteaser, linkedin_alerts, norm_slug, raw,  # noqa: E402
                        save_wd_cache, wttj)
from discover import discover  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "site" / "data"
CONFIG = Path(__file__).parent / "sources.yaml"
RESOLVED = Path(__file__).parent / "resolved_v2.json"  # v2 : ignore les détections erronées du premier passage
NOW = datetime.now(timezone.utc)
REDISCOVER_AFTER = timedelta(days=7)
TIME_BUDGET = timedelta(minutes=80)   # au-delà, les entreprises restantes sont reportées au passage suivant
MAX_DISCOVER = 350                   # détections de plateforme maximum par passage
_START = time.monotonic()
_discovered = [0]
_lock = __import__("threading").Lock()


def out_of_time() -> bool:
    return time.monotonic() - _START > TIME_BUDGET.total_seconds()

log = logging.getLogger("fintrack")


# --------------------------------------------------------------------------- dates

def iso(value) -> str:
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            d = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
        else:
            v = re.sub(r"\s*(UTC|GMT)$", "", str(value).strip()).replace("Z", "+00:00")
            try:
                d = datetime.fromisoformat(v)
            except ValueError:
                d = None
                for fmt in ("%b %d, %Y", "%d %b %Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y"):
                    try:
                        d = datetime.strptime(v, fmt)
                        break
                    except ValueError:
                        pass
                if d is None:
                    return ""
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OSError):
        return ""


# --------------------------------------------------------------------------- VIE

def src_vie(c):
    """Toutes les offres VIE de Business France (API utilisée par mon-vie-via.businessfrance.fr)."""
    api = "https://civiweb-api-prd.azurewebsites.net/api/Offers/search"
    skip = 0
    while skip <= 6000:
        body = {"limit": 100, "skip": skip, "query": "", "activitySectorId": [], "missionsTypesIds": [],
                "missionsDurations": [], "gerographicZones": [], "countriesIds": [], "studiesLevelId": [],
                "companiesSizes": [], "specializationsIds": [], "entreprisesIds": [0], "missionStartDate": None}
        data = http.post(api, json=body)
        items = data.get("result", [])
        for j in items:
            start = (j.get("missionStartDate") or "")[:10]
            try:
                start = datetime.fromisoformat(start).strftime("%m/%Y") if start else ""
            except ValueError:
                start = ""
            dur = j.get("missionDuration")
            yield raw(j.get("organizationName") or "Entreprise française", "VIE (Business France)", j.get("missionTitle"),
                      f"{j.get('cityNameEn') or j.get('cityName', '')}, {j.get('countryNameEn') or j.get('countryName', '')}",
                      f"https://mon-vie-via.businessfrance.fr/offres/{j.get('id')}",
                      j.get("creationDate") or j.get("startBroadcastDate"), "Business France", forced="VIE", start=start,
                      extra=f"{j.get('activitySectorN1', '')} {(j.get('missionDescription') or '')[:300]}"
                      + (f" | {dur} mois" if dur else ""))
        skip += 100
        if not items or skip >= data.get("count", 0):
            break


# --------------------------------------------------------------------------- agrégateurs

SLUG_STOP = {"group", "groupe", "the", "co", "company", "sa", "sas", "ag", "gmbh", "plc", "ltd", "llc", "inc", "spa",
             "management", "partners", "capital", "bank", "asset", "investments", "france"}


def company_index(companies: list[dict]) -> dict[str, dict]:
    idx = {}
    for c in companies:
        full = norm_slug(c["name"])
        core = "-".join(w for w in full.split("-") if w not in SLUG_STOP)
        for v in {full, core}:
            if len(v.replace("-", "")) >= 3 and v not in idx:
                idx[v] = c
    return idx


def match_company(slug: str, idx: dict, prefix: bool = False):
    """Entreprise suivie correspondant au slug (exact pour WTTJ, préfixe pour Jobteaser)."""
    s = re.sub(r"^groupe?-", "", slug)
    if not prefix:
        return idx.get(slug) or idx.get(s)
    best = None
    for cand in (slug, s):
        parts = cand.split("-")
        for n in range(min(6, len(parts) - 1), 0, -1):
            v = "-".join(parts[:n])
            c = idx.get(v)
            if c and (len(v) >= 5 or n >= 2):
                return c, "-".join(parts[n:])
    return best


def src_aggregators(companies: list[dict], which: str):
    idx = company_index(companies)
    if which == "wttj":
        for j in wttj({}):
            c = match_company(j["company_slug"], idx)
            if c:
                yield raw(c["name"], c["type"], j["title"], j["location"], j["url"], j["posted"], j["source"])
            else:  # entreprise non suivie : on ne garde que les métiers front office (M&A, PE, marchés…)
                spec = classify_specialisation(j["title"])
                is_vie = bool(re.search(r"(?<![a-z])v\.?i\.?e(?![a-z])", j["title"], re.I))
                if spec and (is_vie or (spec[1] == "Front office" and spec[0] != "Programmes multi-métiers")):
                    name = j["company_slug"].replace("-", " ").title()
                    yield raw(name, "Autre", j["title"], j["location"], j["url"], j["posted"], j["source"])
    elif which == "linkedin":
        for j in linkedin_alerts({}):
            c = idx.get(norm_slug(j["company"])) or match_company(norm_slug(j["company"]), idx)
            name, ctype = (c["name"], c["type"]) if c else (j["company"] or "Entreprise", "Autre")
            yield raw(name, ctype, j["title"], j["location"], j["url"], j["posted"], j["source"])
    else:
        for j in jobteaser({}):
            m = match_company(j["slug"], idx, prefix=True)
            if m:
                c, rest = m
                title = rest.replace("-", " ").strip()
                yield raw(c["name"], c["type"], title[:1].upper() + title[1:], title, j["url"], j["posted"], j["source"])


# --------------------------------------------------------------------------- résolution des sources

def load_resolved() -> dict:
    try:
        return json.loads(RESOLVED.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def resolve(c: dict, resolved: dict) -> list[dict]:
    """Renvoie la (ou les) config(s) de connecteur à utiliser pour une entreprise."""
    if c.get("ats"):
        return [c]
    r = resolved.get(c["name"])
    fresh = r and datetime.fromisoformat(r["at"]) > NOW - REDISCOVER_AFTER
    if r and (r.get("configs") or fresh):
        return [{**c, **cfg} for cfg in r.get("configs", [])]
    with _lock:
        if _discovered[0] >= MAX_DISCOVER:
            raise TimeoutError("détection reportée au prochain passage")
        _discovered[0] += 1
    found = discover(c["name"], c.get("careers"))
    resolved[c["name"]] = {"at": NOW.isoformat(timespec="seconds"),
                           "configs": [{"ats": k, **cfg} for k, cfg in found[:3]]}
    return [{**c, "ats": k, **cfg} for k, cfg in found[:3]]


def expand(cfg: dict) -> list[dict]:
    for key in ("url", "token"):
        if isinstance(cfg.get(key), list):
            return [{**cfg, key: v} for v in cfg[key]]
    return [cfg]


def run_company(c: dict, defaults: dict, resolved: dict):
    """Collecte une entreprise. Renvoie (offres brutes, méthode utilisée, erreur)."""
    if c.get("skip"):
        return [], "ignorée", c["skip"]
    if out_of_time():
        return [], "reportée", "temps écoulé : reportée au prochain passage"
    errors = []
    try:
        configs = resolve(c, resolved)
    except TimeoutError as e:
        return [], "reportée", str(e)
    except Exception as e:  # noqa: BLE001
        return [], "détection", f"{type(e).__name__}: {e}"[:200]
    if not configs:
        return [], "détection", "plateforme non reconnue — ajoutez un connecteur `html` (voir README)"
    for cfg in configs:
        cfg = {"search": defaults.get("search", SEARCH_TERMS), **cfg}
        fn = CONNECTORS.get(cfg["ats"])
        if not fn:
            errors.append(f"connecteur inconnu {cfg['ats']}")
            continue
        rows, ok = [], False
        for sub in expand(cfg):  # plusieurs sites/tokens pour une même entreprise
            try:
                rows += list(fn(sub))
                ok = True
            except Exception as e:  # noqa: BLE001
                errors.append(f"{cfg['ats']}: {type(e).__name__}: {e}"[:200])
        if ok and rows:
            return rows, cfg["ats"], None
        if ok and len(configs) == 1 and c.get("ats"):
            return rows, cfg["ats"], None
    # le connecteur explicite a échoué : on tente la détection depuis la page carrières
    if c.get("ats") and c.get("careers"):
        try:
            for k, found in discover(c["name"], c["careers"]):
                if k == c["ats"] and all(found.get(x) == c.get(x) for x in found):
                    continue
                rows = list(CONNECTORS[k]({**c, "search": defaults.get("search", SEARCH_TERMS), "ats": k, **found}))
                resolved[c["name"]] = {"at": NOW.isoformat(timespec="seconds"), "configs": [{"ats": k, **found}],
                                       "note": "remplace le connecteur de sources.yaml"}
                return rows, f"{k} (détecté)", None
        except Exception as e:  # noqa: BLE001
            errors.append(f"détection: {type(e).__name__}: {e}"[:200])
    if not c.get("ats"):
        # plateforme détectée vide ou en panne : on ne réessaie pas avant 7 jours
        resolved[c["name"]] = {"at": NOW.isoformat(timespec="seconds"), "configs": [], "note": "aucune offre"}
    return [], configs[0]["ats"], " | ".join(errors) or "aucune offre"


# --------------------------------------------------------------------------- pipeline

def job_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def enrich(r: dict) -> dict | None:
    if not r.get("title") or not r.get("url"):
        return None
    spec = classify_specialisation(r["title"], r.get("extra", "") if r.get("forced") == "VIE" else "")
    if spec is None and r.get("forced") == "VIE" and re.search(r"financ|banque|bank|account|audit|contr", r["title"], re.I):
        spec = ("Corporate Finance & Contrôle", "Middle / Back office")
    if spec is None:
        return None
    loc = parse_location(r["location"])
    if not loc["country"]:  # dernier recours : le lieu figure parfois dans le titre
        loc = parse_location(r["title"])
    return {
        "id": job_id(r["url"]),
        "title": r["title"],
        "company": r["company"],
        "company_type": r["company_type"],
        "contract": classify_contract(r["title"], r.get("hint", ""), r.get("forced")),
        "specialisation": spec[0],
        "family": spec[1],
        "city": loc["city"],
        "country": loc["country"],
        "countries": loc["countries"],
        "region": loc["region"],
        "location_raw": r["location"][:120],
        "start": parse_start(r["title"], r.get("start", "")),
        "posted": iso(r["posted"]),
        "source": r["source"],
        "url": r["url"],
    }


def merge_with_previous(jobs: list[dict], failed_feeds: set[str]) -> list[dict]:
    """Conserve first_seen ; garde les offres des sources en échec pour ne pas les perdre."""
    prev = {}
    try:
        prev = {j["id"]: j for j in json.loads((OUT_DIR / "jobs.json").read_text())["jobs"]}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    now = NOW.isoformat(timespec="seconds")
    out = {}
    for j in jobs:
        j["first_seen"] = prev.get(j["id"], {}).get("first_seen", now)
        if not j["posted"]:
            j["posted"] = j["first_seen"]
        out[j["id"]] = j
    for jid, j in prev.items():
        if jid not in out and j.get("feed", j["company"]) in failed_feeds:
            out[jid] = j
    return sorted(out.values(), key=lambda j: j["posted"], reverse=True)


def write_outputs(jobs: list[dict], status: list[dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": NOW.isoformat(timespec="seconds"), "count": len(jobs), "sources": status, "jobs": jobs}
    (OUT_DIR / "jobs.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    items = []
    for j in jobs[:100]:
        loc = ", ".join(x for x in (j["city"], j["country"]) if x)
        items.append(
            f"<item><title>{escape(j['company'])} · {escape(j['title'])} ({escape(j['contract'])})</title>"
            f"<link>{escape(j['url'])}</link><guid isPermaLink=\"false\">{j['id']}</guid>"
            f"<description>{escape(j['specialisation'])} · {escape(loc)}</description>"
            f"<pubDate>{datetime.fromisoformat(j['posted']).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>")
    (OUT_DIR / "feed.xml").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><rss version=\"2.0\"><channel><title>FinTrack — nouvelles offres"
        "</title><link>https://github.com/</link><description>Stages, graduate programmes, CDI et VIE en finance"
        f"</description>{''.join(items)}</channel></rss>")
    log.info("%d offres écrites dans %s", len(jobs), OUT_DIR)


def collect(check=False, only: set[str] | None = None):
    cfg = yaml.safe_load(CONFIG.read_text())
    defaults = cfg.get("defaults", {})
    companies = [c for c in cfg.get("companies", []) if not only or any(o.lower() in c["name"].lower() for o in only)]
    resolved = load_resolved()
    tasks = [(c["name"], lambda c=c: run_company(c, defaults, resolved)) for c in companies]
    for flag, label in (("welcome_to_the_jungle", "wttj"), ("jobteaser", "jobteaser"), ("linkedin_alerts", "linkedin")):
        if cfg.get(flag) and not only:
            def agg(label=label, comps=companies):
                try:
                    return list(src_aggregators(comps, label)), label, None
                except Exception as e:  # noqa: BLE001
                    return [], label, f"{type(e).__name__}: {e}"[:200]
            tasks.append(({"wttj": "Welcome to the Jungle", "jobteaser": "Jobteaser", "linkedin": "LinkedIn (alertes email)"}[label], agg))
    if cfg.get("vie_businessfrance") and not only:
        def vie():
            try:
                return list(src_vie({})), "businessfrance", None
            except Exception as e:  # noqa: BLE001
                return [], "businessfrance", f"{type(e).__name__}: {e}"[:200]
        tasks.append(("Business France (VIE)", vie))

    rows, status, failed = [], [], set()
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks}
        for fut in cf.as_completed(futures):
            name = futures[fut]
            res, method, err = fut.result()
            kept = [e for e in (enrich(r) for r in res) if e]
            for j in kept:
                j["feed"] = name
            ok = err is None and bool(res)
            status.append({"name": name, "source": method, "fetched": len(res), "kept": len(kept), "ok": ok,
                           "error": err})
            log.info("%s %-30s %-16s %5d offres, %4d finance %s", "OK " if ok else "ERR", name[:30], method[:16],
                     len(res), len(kept), err or "")
            if not ok:
                failed.add(name)
            rows.extend(kept)
    status.sort(key=lambda s: (not s["ok"], -s["kept"]))
    ok_n = sum(s["ok"] for s in status)
    log.info("\n%d/%d sources OK — %d offres finance", ok_n, len(status), len(rows))
    RESOLVED.write_text(json.dumps(resolved, ensure_ascii=False, indent=1, sort_keys=True))
    save_wd_cache()
    if check:
        return
    uniq = {j["id"]: j for j in rows}
    write_outputs(merge_with_previous(list(uniq.values()), failed), status)


def import_seed(path: Path):
    cfg = yaml.safe_load(CONFIG.read_text())
    types = {c["name"]: c["type"] for c in cfg.get("companies", [])}
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        company, title, location, date, url = [p.strip() for p in line.split(" | ")]
        is_vie = bool(re.search(r"\bv\.?i\.?e\b", title, re.I))
        ctype = "VIE (Business France)" if is_vie else types.get(company, "Corporate & Investment Bank")
        source = "Business France" if is_vie else ("Greenhouse" if "greenhouse" in url else "Web")
        rows.append(raw(company, ctype, title, location, url, date, source))
    jobs = [e for e in (enrich(r) for r in rows) if e]
    for j in jobs:
        j["feed"] = j["company"]
    jobs = merge_with_previous(jobs, set())
    log.info("seed : %d lignes, %d offres finance", len(rows), len(jobs))
    write_outputs(jobs, [{"name": "Instantané initial", "source": "seed", "fetched": len(rows), "kept": len(jobs),
                          "ok": True, "error": None}])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--seed", type=Path)
    a = ap.parse_args()
    if a.seed:
        import_seed(a.seed)
    else:
        collect(check=a.check, only=set(a.only.split(",")) if a.only else None)
