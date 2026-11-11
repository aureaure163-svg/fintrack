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
                r = self.s.request(method, url, timeout=30, **kw)
                if r.status_code in (429, 503):
                    time.sleep(4 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json() if as_json else r.text
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


def workday(c):
    m = re.match(r"https://([^/]+)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", c["url"])
    host, site = m.group(1), m.group(2)
    tenant = host.split(".")[0]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    seen = set()
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
                yield raw(c["name"], c["type"], j.get("title"), j.get("locationsText"), f"https://{host}/{site}{path}",
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
