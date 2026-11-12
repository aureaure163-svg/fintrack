"""Connecteurs vers les plateformes de recrutement (ATS).

Chaque connecteur est un générateur qui reçoit la config d'une entreprise (dict venant de
sources.yaml) et produit des offres brutes via `raw(...)`. Toutes les requêtes passent par
`http` (session partagée, retries, respect de robots.txt pour le HTML).
"""
from __future__ import annotations

import html as htmllib
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests

UA = "Mozilla/5.0 (compatible; FinTrackBot/1.0; +https://github.com/)"
NOW = datetime.now(timezone.utc)
SEARCH_TERMS = ["intern", "internship", "analyst", "graduate", "associate", "trader", "stage", "stagiaire", "VIE",
                "alternance", "apprentice", "summer", "off-cycle", "spring"]


# --------------------------------------------------------------------------- HTTP

class Http:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                               "Accept-Language": "en-US,en;q=0.9,fr;q=0.8"})
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def request(self, method, url, *, as_json=True, **kw):
        last = None
        for attempt in range(3):
            try:
                r = self.s.request(method, url, timeout=20, **kw)
                if r.status_code in (429, 503):
                    time.sleep(4 * (attempt + 1))
                    continue
                if 400 <= r.status_code < 500:  # introuvable / refusé : inutile de réessayer
                    r.raise_for_status()
                r.raise_for_status()
                return r.json() if as_json else r.text
            except requests.HTTPError as e:
                if e.response is not None and 400 <= e.response.status_code < 500:
                    raise
                last = e
                time.sleep(1.5 * (attempt + 1))
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise last or RuntimeError(f"échec {url}")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def text(self, url, **kw):
        self.check_robots(url)
        return self.request("GET", url, as_json=False, **kw)

    def check_robots(self, url):
        """Refuse de lire une page HTML interdite par le robots.txt du site."""
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(root + "/robots.txt", timeout=15)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[root] = rp
        if not self._robots[root].can_fetch(UA, url):
            raise PermissionError(f"robots.txt interdit {url}")


http = Http()


# --------------------------------------------------------------------------- helpers

def raw(company, ctype, title, location, url, posted="", source="", hint="", forced=None, start="", extra=""):
    return dict(company=company, company_type=ctype, title=clean(title), location=clean(location or ""), url=url,
                posted=posted or "", source=source, hint=hint or "", forced=forced, start=start, extra=extra or "")


def clean(s) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    return re.sub(r"\s+", " ", s).strip()


def ago_to_iso(text: str) -> str:
    t = (text or "").lower()
    if "today" in t or "aujourd" in t:
        days = 0
    elif "yesterday" in t or "hier" in t:
        days = 1
    else:
        m = re.search(r"(\d+)\+?\s*(day|jour)", t)
        days = int(m.group(1)) if m else 30
    return (NOW - timedelta(days=days)).isoformat(timespec="seconds")


def slug_to_title(url: str) -> str:
    seg = [s for s in urlparse(url).path.split("/") if s and not s.isdigit()]
    s = seg[-1] if seg else url
    s = re.sub(r"[-_]+", " ", re.sub(r"\.\w+$", "", s))
    return s[:1].upper() + s[1:]


def anchors(page: str, link_re: str, base: str):
    """(url, texte du lien, texte qui suit) pour chaque lien qui matche link_re."""
    pat = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
    lr = re.compile(link_re)
    for m in pat.finditer(page):
        href = htmllib.unescape(m.group(1))
        if not lr.search(href):
            continue
        after = clean(page[m.end(): m.end() + 1500])[:300]
        yield urljoin(base, href), clean(m.group(2)), after


# --------------------------------------------------------------------------- API JSON

def greenhouse(c):
    data = http.get(f"https://boards-api.greenhouse.io/v1/boards/{c['token']}/jobs")
    for j in data.get("jobs", []):
        yield raw(c["name"], c["type"], j.get("title"), (j.get("location") or {}).get("name"), j.get("absolute_url"),
                  j.get("first_published") or j.get("updated_at"), "Greenhouse")


def lever(c):
    host = "api.eu.lever.co" if c.get("eu") else "api.lever.co"
    for j in http.get(f"https://{host}/v0/postings/{c['token']}?mode=json"):
        cat = j.get("categories") or {}
        loc = cat.get("location") or ", ".join(cat.get("allLocations") or [])
        yield raw(c["name"], c["type"], j.get("text"), loc, j.get("hostedUrl"), j.get("createdAt"), "Lever",
                  hint=cat.get("commitment", ""), extra=cat.get("team", ""))


def ashby(c):
    data = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{c['token']}")
    for j in data.get("jobs", []):
        loc = j.get("location") or ""
        if j.get("secondaryLocations"):
            loc += "; " + "; ".join(s.get("location", "") for s in j["secondaryLocations"])
        yield raw(c["name"], c["type"], j.get("title"), loc, j.get("jobUrl"), j.get("publishedAt"), "Ashby",
                  hint=j.get("employmentType", ""), extra=j.get("department", ""))


def smartrecruiters(c):
    offset = 0
    while offset <= 3000:
        data = http.get(f"https://api.smartrecruiters.com/v1/companies/{c['token']}/postings?limit=100&offset={offset}")
        content = data.get("content", [])
        for j in content:
            loc = j.get("location") or {}
            yield raw(c["name"], c["type"], j.get("name"), f"{loc.get('city', '')}, {loc.get('country', '')}",
                      f"https://jobs.smartrecruiters.com/{c['token']}/{j.get('id')}", j.get("releasedDate"),
                      "SmartRecruiters", hint=(j.get("typeOfEmployment") or {}).get("label", ""),
                      extra=(j.get("function") or {}).get("label", ""))
        offset += 100
        if not content or offset >= data.get("totalFound", 0):
            break


# Cache des lieux détaillés Workday (« 3 Locations » → vraies villes), conservé d'un passage à l'autre
import json as _json  # noqa: E402
import threading as _threading  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

WD_CACHE_FILE = _Path(__file__).resolve().parent.parent / "site" / "data" / "wd_locations.json"
_wd_lock = _threading.Lock()
try:
    WD_CACHE = _json.loads(WD_CACHE_FILE.read_text())
except (FileNotFoundError, ValueError):
    WD_CACHE = {}


def save_wd_cache():
    with _wd_lock:
        WD_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        WD_CACHE_FILE.write_text(_json.dumps(WD_CACHE, ensure_ascii=False, separators=(",", ":")))


def workday_detail(host, tenant, site, path):
    """Lieux complets d'une offre Workday (une requête, mise en cache)."""
    url = f"https://{host}/{site}{path}"
    if url in WD_CACHE:
        return WD_CACHE[url]
    info = http.get(f"https://{host}/wday/cxs/{tenant}/{site}{path}").get("jobPostingInfo", {})
    locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
    country = (info.get("country") or {}).get("descriptor", "")
    val = "; ".join(x for x in locs if x) + (f"; {country}" if country else "")
    with _wd_lock:
        WD_CACHE[url] = val
    return val


def workday(c):
    m = re.match(r"https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", c["url"])
    host, site = m.group(1), m.group(2)
    tenant = host.split(".")[0]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    seen = set()
    details = 0
    for q in c.get("search", SEARCH_TERMS):
        offset = 0
        while offset < c.get("max_per_term", 200):
            data = http.post(api, json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q})
            posts = data.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                loc = j.get("locationsText") or ""
                if (not loc or re.search(r"\d+\s+Locations?", loc)) and details < c.get("max_details", 200):
                    try:
                        before = len(WD_CACHE)
                        loc = workday_detail(host, tenant, site, path) or loc
                        details += len(WD_CACHE) - before
                    except Exception:  # noqa: BLE001 — on garde « N Locations »
                        pass
                yield raw(c["name"], c["type"], j.get("title"), loc, f"https://{host}/{site}{path}",
                          ago_to_iso(j.get("postedOn")), "Workday")
            offset += 20
            if len(posts) < 20:
                break


def oracle(c):
    """Oracle Recruiting Cloud (ex. JPMorgan : jpmc.fa.oraclecloud.com, site CX_1001)."""
    host, site = c["host"], c["site"]
    seen = set()
    for q in [""] + c.get("search", SEARCH_TERMS[:6]):
        offset = 0
        while offset < (1500 if not q else 400):
            kw = f",keyword=%22{q}%22" if q else ""
            url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                   f"&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},limit=100,"
                   f"offset={offset},sortBy=POSTING_DATES_DESC{kw}")
            data = http.get(url)
            items = (data.get("items") or [{}])[0]
            reqs = items.get("requisitionList", [])
            for j in reqs:
                if j.get("Id") in seen:
                    continue
                seen.add(j.get("Id"))
                locs = [j.get("PrimaryLocation", "")] + [s.get("Name", "") for s in j.get("secondaryLocations") or []]
                yield raw(c["name"], c["type"], j.get("Title"), "; ".join(filter(None, locs)),
                          f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{j.get('Id')}",
                          j.get("PostedDate"), "Oracle", hint=j.get("WorkerType", "") or "",
                          extra=j.get("JobFamily", "") or "")
            offset += 100
            if len(reqs) < 100:
                break


def workable(c):
    data = http.get(f"https://apply.workable.com/api/v1/widget/accounts/{c['token']}")
    for j in data.get("jobs", []):
        yield raw(c["name"], c["type"], j.get("title"), f"{j.get('city', '')}, {j.get('country', '')}",
                  j.get("url") or f"https://apply.workable.com/{c['token']}/j/{j.get('shortcode')}/",
                  j.get("published_on") or j.get("created_at"), "Workable", hint=j.get("employment_type", ""))


def recruitee(c):
    data = http.get(f"https://{c['token']}.recruitee.com/api/offers/")
    for j in data.get("offers", []):
        yield raw(c["name"], c["type"], j.get("title"), f"{j.get('city', '')}, {j.get('country', '')}",
                  j.get("careers_url"), j.get("published_at"), "Recruitee", hint=j.get("employment_type_code", ""))


def personio(c):
    xml = http.request("GET", f"https://{c['token']}.jobs.personio.de/xml", as_json=False)
    for p in ET.fromstring(xml).iter("position"):
        g = lambda k: (p.findtext(k) or "").strip()  # noqa: E731
        yield raw(c["name"], c["type"], g("name"), g("office"), f"https://{c['token']}.jobs.personio.de/job/{g('id')}",
                  g("createdAt"), "Personio", hint=f"{g('employmentType')} {g('schedule')}", extra=g("department"))


def taleo(c):
    """Oracle Taleo (ex. Société Générale : socgen.taleo.net, section sgcareers)."""
    host, section = c["host"], c["section"]
    page = http.request("GET", f"https://{host}/careersection/{section}/jobsearch.ftl?lang=en", as_json=False)
    m = re.search(r"portal=(\d+)", page) or re.search(r'"portal"\s*:\s*"?(\d+)', page)
    if not m:
        raise RuntimeError("identifiant de portail Taleo introuvable")
    api = f"https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={m.group(1)}"
    for n in range(1, c.get("max_pages", 60) + 1):
        body = {"multilineEnabled": False, "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
                "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
                "filterSelectionParam": {"searchFilterSelections": []}, "advancedSearchFiltersSelectionParam": {
                    "searchFilterSelections": []}, "pageNo": n}
        data = http.post(api, json=body, headers={"tz": "GMT+01:00", "Content-Type": "application/json"})
        reqs = data.get("requisitionList", [])
        for j in reqs:
            col = j.get("column") or []
            title = col[0] if col else ""
            loc = clean(col[1]) if len(col) > 1 else ""
            date = col[2] if len(col) > 2 else ""
            try:
                posted = datetime.strptime(date, "%b %d, %Y").replace(tzinfo=timezone.utc).isoformat()
            except (ValueError, TypeError):
                posted = ""
            yield raw(c["name"], c["type"], title, re.sub(r'[\[\]"]', "", loc),
                      f"https://{host}/careersection/{section}/jobdetail.ftl?job={j.get('contestNo') or j.get('jobId')}&lang=en",
                      posted, "Taleo")
        if not reqs:
            break


# --------------------------------------------------------------------------- HTML

def successfactors(c):
    """SAP SuccessFactors Career Site Builder (ex. careers.ey.com/ey)."""
    base = c["url"].rstrip("/")
    seen = set()
    row = re.compile(r'<tr[^>]*class="[^"]*data-row[^"]*"[^>]*>(.*?)</tr>', re.S)
    for q in c.get("search", SEARCH_TERMS[:8]):
        for start in range(0, c.get("max_rows", 500), 25):
            page = http.text(f"{base}/search/?q={q}&sortColumn=referencedate&sortDirection=desc&startrow={start}")
            rows = row.findall(page)
            for r in rows:
                a = re.search(r'<a[^>]*class="[^"]*jobTitle-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r, re.S)
                if not a:
                    continue
                url = urljoin(base + "/", a.group(1))
                if url in seen:
                    continue
                seen.add(url)
                loc = re.search(r'class="[^"]*jobLocation[^"]*"[^>]*>(.*?)</span>', r, re.S)
                date = re.search(r'class="[^"]*jobDate[^"]*"[^>]*>(.*?)</span>', r, re.S)
                posted = ""
                if date:
                    for fmt in ("%b %d, %Y", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
                        try:
                            posted = datetime.strptime(clean(date.group(1)), fmt).replace(tzinfo=timezone.utc).isoformat()
                            break
                        except ValueError:
                            pass
                yield raw(c["name"], c["type"], a.group(2), loc.group(1) if loc else "", url, posted, "SuccessFactors")
            if len(rows) < 25:
                break


def avature(c):
    """Portails Avature (ex. HSBC : mycareer.hsbc.com/en_GB/external/SearchJobs)."""
    base = c["url"].split("?")[0]
    seen = set()
    for offset in range(0, c.get("max_rows", 3000), 50):
        page = http.text(f"{base}?jobRecordsPerPage=50&jobOffset={offset}")
        new = 0
        for url, title, after in anchors(page, r"/JobDetail/", base):
            if url in seen or not title:
                continue
            seen.add(url)
            new += 1
            yield raw(c["name"], c["type"], title, after, url, "", "Avature", hint=after)
        if new == 0:
            break


def html(c):
    """Page de liste générique : `pages` (avec {page} ou {offset}) + `link` (regex des liens d'offres)."""
    seen = set()
    for tpl in ([c["pages"]] if isinstance(c["pages"], str) else c["pages"]):
        for n in range(c.get("first_page", 1), c.get("first_page", 1) + c.get("max_pages", 30)):
            url = tpl.format(page=n, offset=(n - c.get("first_page", 1)) * c.get("page_size", 20))
            page = http.text(url)
            new = 0
            for job_url, title, after in anchors(page, c["link"], url):
                if job_url in seen:
                    continue
                seen.add(job_url)
                new += 1
                yield raw(c["name"], c["type"], title or slug_to_title(job_url), after, job_url, "", "Site carrières",
                          hint=after)
            if new == 0 or "{" not in tpl:
                break


def sitemap(c):
    """Sitemap XML : chaque <loc> qui matche `link` devient une offre (titre et lieu déduits de l'URL)."""
    xml = http.text(c["url"])
    lr = re.compile(c["link"])
    for m in re.finditer(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>(.*?)</loc>", m.group(1))
        if not loc or not lr.search(loc.group(1)):
            continue
        u = htmllib.unescape(loc.group(1).strip())
        lastmod = re.search(r"<lastmod>(.*?)</lastmod>", m.group(1))
        title = slug_to_title(u)
        yield raw(c["name"], c["type"], title, title, u, lastmod.group(1) if lastmod else "", "Site carrières")


CONNECTORS = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
    "workday": workday, "oracle": oracle, "workable": workable, "recruitee": recruitee, "personio": personio,
    "taleo": taleo, "successfactors": successfactors, "avature": avature, "html": html, "sitemap": sitemap,
}


# --------------------------------------------------------------------------- agrégateurs (sitemaps publics)
# Welcome to the Jungle et Jobteaser publient toutes leurs offres dans des sitemaps XML destinés aux
# robots (autorisés par leurs robots.txt). On lit ces sitemaps, sans charger les pages d'offres.

import gzip  # noqa: E402
import unicodedata  # noqa: E402

GENDER = re.compile(r"[-_ ](h-?f|f-?h|m-?f|f-?m|m-?w-?d|w-?m-?d|m-?f-?d|f-?h-?x|h-?f-?x|x-?f-?h|hf|fh|mfd|wmd|e)$")


def fetch_bytes(url: str) -> bytes:
    http.check_robots(url)
    r = http.s.get(url, timeout=60, headers={"Accept": "application/xml, text/xml, application/gzip, */*"})
    r.raise_for_status()
    data = r.content
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def sitemap_entries(url: str):
    xml = fetch_bytes(url).decode("utf-8", "replace")
    for m in re.finditer(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", m.group(1))
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", m.group(1))
        if loc:
            yield htmllib.unescape(loc.group(1)), (mod.group(1) if mod else "")


def slug_title(slug: str) -> str:
    s = slug.strip("-")
    for _ in range(2):
        s = GENDER.sub("", s)
    s = s.replace("-", " ").strip()
    s = re.sub(r"(?<![a-z])m a(?![a-z])", "M&A", s)
    return s[:1].upper() + s[1:]


def norm_slug(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\(.*?\)", "", n).replace("&", " ")
    return "-".join(re.findall(r"[a-z0-9]+", n))


def recent(lastmod: str, days: int) -> bool:
    try:
        d = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
        return d >= NOW - timedelta(days=days)
    except ValueError:
        return True


def wttj(c):
    """Welcome to the Jungle : /{lang}/companies/{entreprise}/jobs/{titre}_{ville}[_{id}]"""
    index = fetch_bytes("https://www.welcometothejungle.com/sitemaps/index.xml.gz").decode("utf-8", "replace")
    maps = re.findall(r"<loc>\s*(\S*job-listings\.\d+\.xml\.gz)\s*</loc>", index)
    pat = re.compile(r"welcometothejungle\.com/(fr|en|es|cs|sk)/companies/([^/]+)/jobs/([^/?#]+)")
    seen = set()
    for sm in maps:
        for url, mod in sitemap_entries(sm):
            m = pat.search(url)
            if not m or not recent(mod, c.get("days", 45)):
                continue
            lang, comp, rest = m.groups()
            key = (comp, rest)
            if key in seen:
                continue
            seen.add(key)
            parts = rest.split("_")
            title = slug_title(parts[0])
            city = parts[1].replace("-", " ").title() if len(parts) > 1 else ""
            yield {"company_slug": re.sub(r"-\d+$", "", comp), "title": title, "location": city, "url": url,
                   "posted": mod, "source": "Welcome to the Jungle"}


def jobteaser(c):
    """Jobteaser : /{lang}/job-offers/{uuid}-{entreprise}-{titre} (entreprise et titre fusionnés dans le slug)."""
    index = fetch_bytes("https://assets-cf.jobteaser.com/sitemaps/sitemap.xml").decode("utf-8", "replace")
    maps = re.findall(r"<loc>\s*(\S*job_ads_sitemap\d*\.xml)\s*</loc>", index)
    pat = re.compile(r"jobteaser\.com/([a-z]{2})/job-offers/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-([^/?#]+)")
    best = {}
    for sm in maps:
        for url, mod in sitemap_entries(sm):
            m = pat.search(url)
            if not m or not recent(mod, c.get("days", 45)):
                continue
            lang, uid, slug = m.groups()
            if uid in best and best[uid]["lang"] == "fr":
                continue
            best[uid] = {"lang": lang, "slug": slug, "url": url, "posted": mod}
    for b in best.values():
        yield {"slug": b["slug"], "url": b["url"], "posted": b["posted"], "source": "Jobteaser"}


# --------------------------------------------------------------------------- LinkedIn (via tes alertes emploi par email)
# LinkedIn interdit la collecte automatique de son site. À la place, on lit les emails d'alerte emploi que
# LinkedIn t'envoie (jobalerts-noreply@linkedin.com) dans ta boîte mail, via IMAP.
# Identifiants lus dans les variables d'environnement (secrets GitHub) : IMAP_USER, IMAP_PASSWORD, IMAP_HOST.

import email as _email  # noqa: E402
import imaplib  # noqa: E402
import os  # noqa: E402
from email.utils import parsedate_to_datetime  # noqa: E402

LI_JOB = re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d{6,})")


def _parts(msg):
    text, html_ = "", ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        s = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/plain":
            text += s
        else:
            html_ += s
    return text, html_


def parse_linkedin_alert(text: str, html_: str) -> list[dict]:
    """Extrait (titre, entreprise, lieu, id) des emails d'alerte LinkedIn (version texte, sinon HTML)."""
    jobs, seen = [], set()
    if text:
        lines = [ln.strip() for ln in text.splitlines()]
        for i, ln in enumerate(lines):
            m = LI_JOB.search(ln)
            if not m or m.group(1) in seen:
                continue
            prev = [x for x in lines[max(0, i - 6):i] if x and not LI_JOB.search(x)
                    and not re.match(r"^(view job|voir l.offre|-+|apply|postuler|actively recruiting|.*connections?$)", x, re.I)]
            if len(prev) >= 3:
                title, company, loc = prev[-3], prev[-2], prev[-1]
            elif len(prev) == 2:
                title, company, loc = prev[0], prev[1], ""
            else:
                continue
            if "·" in company and not loc:
                company, loc = [x.strip() for x in company.split("·", 1)]
            seen.add(m.group(1))
            jobs.append({"id": m.group(1), "title": title, "company": company, "location": loc})
    if not jobs and html_:
        for url, title, after in anchors(html_, LI_JOB.pattern, "https://www.linkedin.com/"):
            jid = LI_JOB.search(url).group(1)
            if jid in seen or not title or len(title) < 4 or re.match(r"(?i)^(view|voir|see|apply)", title):
                continue
            bits = [b.strip() for b in re.split(r"·|\|", after) if b.strip()]
            seen.add(jid)
            jobs.append({"id": jid, "title": title, "company": bits[0] if bits else "",
                         "location": bits[1] if len(bits) > 1 else ""})
    return jobs


def linkedin_alerts(c):
    user, pwd = os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    if not user or not pwd:
        raise RuntimeError("secrets IMAP_USER / IMAP_PASSWORD absents (voir README, section LinkedIn)")
    box = imaplib.IMAP4_SSL(os.environ.get("IMAP_HOST", "imap.gmail.com"))
    try:
        box.login(user, pwd)
        box.select("INBOX", readonly=True)
        since = (NOW - timedelta(days=c.get("days", 21))).strftime("%d-%b-%Y")
        _, data = box.search(None, f'(FROM "linkedin.com" SINCE {since})')
        for num in (data[0].split() if data and data[0] else [])[-400:]:
            _, msg_data = box.fetch(num, "(RFC822)")
            msg = _email.message_from_bytes(msg_data[0][1])
            sender = (msg.get("From") or "").lower()
            if "jobalerts" not in sender and "jobs-listings" not in sender and "jobs-noreply" not in sender:
                continue
            try:
                posted = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                posted = ""
            for j in parse_linkedin_alert(*_parts(msg)):
                yield {"company": j["company"], "title": j["title"], "location": j["location"],
                       "url": f"https://www.linkedin.com/jobs/view/{j['id']}/", "posted": posted, "source": "LinkedIn"}
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
