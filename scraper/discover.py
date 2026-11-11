#!/usr/bin/env python3
"""Détecte la plateforme de recrutement d'une entreprise à partir de sa page carrières.

    python scraper/discover.py "Lazard" https://www.lazard.com/careers/
    python scraper/discover.py "Ardian"            # essaie aussi les identifiants probables (greenhouse, lever…)

Renvoie la config à coller dans sources.yaml. Utilisé aussi automatiquement par scrape.py pour
les entreprises déclarées avec seulement `careers: <url>`.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from urllib.parse import urljoin, urlparse

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from connectors import http  # noqa: E402

# (type, regex, fabrique de config à partir du match)
SIGNATURES = [
    ("workday", r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
     lambda m: {"url": f"https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com/{m.group(3)}"}),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([a-z0-9]+)",
     lambda m: {"token": m.group(1)}),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9]+)", lambda m: {"token": m.group(1)}),
    ("lever", r"jobs\.(eu\.)?lever\.co/([A-Za-z0-9-]+)",
     lambda m: {"token": m.group(2), **({"eu": True} if m.group(1) else {})}),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9.-]+)", lambda m: {"token": m.group(1)}),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9-]+)", lambda m: {"token": m.group(1)}),
    ("oracle", r"([a-z0-9-]+\.fa(?:\.[a-z0-9-]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}/sites/([A-Za-z0-9_]+)",
     lambda m: {"host": m.group(1), "site": m.group(2)}),
    ("taleo", r"([a-z0-9-]+\.taleo\.net)/careersection/([A-Za-z0-9_]+)",
     lambda m: {"host": m.group(1), "section": m.group(2)}),
    ("workable", r"apply\.workable\.com/([a-z0-9-]+)", lambda m: {"token": m.group(1)}),
    ("personio", r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", lambda m: {"token": m.group(1)}),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com", lambda m: {"token": m.group(1)}),
    ("avature", r"(https?://[^\"'\s]+/SearchJobs)\b", lambda m: {"url": m.group(1)}),
]

IGNORE_TOKENS = {"embed", "js", "v1", "api", "static", "assets", "www"}
CAREER_LINK = re.compile(r"job|career|carri|offre|opportunit|vacanc|search|join|recrut|emploi|stellen|graduate|student",
                         re.I)


def detect(page: str, page_url: str = "") -> list[tuple[str, dict]]:
    found, seen = [], set()
    for kind, rx, make in SIGNATURES:
        for m in re.finditer(rx, page):
            cfg = make(m)
            if any(v in IGNORE_TOKENS for v in cfg.values() if isinstance(v, str)):
                continue
            key = (kind, tuple(sorted(cfg.items())))
            if key not in seen:
                seen.add(key)
                found.append((kind, cfg))
    # SAP SuccessFactors Career Site Builder : ressources rmkcdn + liens /job/ ou /go/
    if not found and ("rmkcdn.successfactors.com" in page or "jobTitle-link" in page):
        p = urlparse(page_url)
        m = re.search(r'href="(/[A-Za-z0-9_-]+)?/(?:search|go|job)/', page)
        prefix = (m.group(1) or "") if m else ""
        found.append(("successfactors", {"url": f"{p.scheme}://{p.netloc}{prefix}"}))
    return found


def slug_variants(name: str) -> list[str]:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"&", "and", n)
    words = re.findall(r"[a-z0-9]+", n)
    stop = {"and", "co", "the", "group", "sa", "plc", "inc", "llc", "ltd", "capital", "partners"}
    core = [w for w in words if w not in stop] or words
    out = ["".join(words), "".join(core), "-".join(words), "-".join(core), core[0] if core else ""]
    return list(dict.fromkeys(v for v in out if v))


def probe(name: str) -> list[tuple[str, dict]]:
    """Essaie les identifiants probables sur les API publiques."""
    hits = []
    for slug in slug_variants(name):
        tests = [
            ("greenhouse", {"token": slug}, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
             lambda d: isinstance(d, dict) and "jobs" in d),
            ("lever", {"token": slug}, f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
             lambda d: isinstance(d, list)),
            ("ashby", {"token": slug}, f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
             lambda d: isinstance(d, dict) and "jobs" in d),
            ("smartrecruiters", {"token": slug}, f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
             lambda d: isinstance(d, dict) and d.get("totalFound", 0) > 0),
            ("workable", {"token": slug}, f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
             lambda d: isinstance(d, dict) and "jobs" in d),
        ]
        for kind, cfg, url, ok in tests:
            try:
                if ok(http.get(url)):
                    hits.append((kind, cfg))
            except Exception:  # noqa: BLE001
                pass
        if hits:
            break
    return hits


def discover(name: str, careers: str | None = None, depth: int = 1) -> list[tuple[str, dict]]:
    if careers:
        try:
            page = http.text(careers)
        except Exception as e:  # noqa: BLE001
            page = ""
            print(f"  ! {careers}: {e}", file=sys.stderr)
        found = detect(page, careers)
        if found:
            return found
        if depth and page:
            host = urlparse(careers).netloc
            links = []
            for href in re.findall(r'href=["\']([^"\'#]+)["\']', page):
                u = urljoin(careers, href)
                if CAREER_LINK.search(u) and u not in links and u != careers:
                    links.append(u)
            # liens externes d'abord (souvent l'ATS), puis internes
            links.sort(key=lambda u: urlparse(u).netloc == host)
            for u in links[:15]:
                found = detect(u, u)  # l'URL elle-même peut suffire
                if found:
                    return found
                try:
                    sub = http.text(u)
                except Exception:  # noqa: BLE001
                    continue
                found = detect(sub, u)
                if found:
                    return found
    return probe(name)


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    res = discover(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    if not res:
        print("Aucune plateforme reconnue. Utilisez le connecteur `html` (voir README).")
    for kind, cfg in res:
        print(json.dumps({"name": sys.argv[1], "ats": kind, **cfg}, ensure_ascii=False))
