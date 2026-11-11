"""Tests hors-ligne : chaque connecteur reçoit une réponse au format de la vraie plateforme."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import connectors  # noqa: E402
import discover as disc  # noqa: E402
import scrape  # noqa: E402

JSON = {
    "boards-api.greenhouse.io/v1/boards/": {"jobs": [{"title": "Summer Analyst 2027 - M&A", "location": {"name": "Paris, France"},
        "absolute_url": "https://x/gh/1", "updated_at": "2026-11-09T10:00:00-04:00", "first_published": "2026-11-08T10:00:00-04:00"}]},
    "api.lever.co": [{"text": "Off-cycle Intern - Sales & Trading", "categories": {"location": "London", "commitment": "Internship"},
        "hostedUrl": "https://x/lv/1", "createdAt": 1762700000000}],
    "api.ashbyhq.com": {"jobs": [{"title": "Finance Analyst", "location": "New York", "jobUrl": "https://x/ab/1",
        "publishedAt": "2026-11-01T00:00:00Z", "employmentType": "FullTime"}]},
    "api.smartrecruiters.com": {"totalFound": 1, "content": [{"id": "9", "name": "Stagiaire Gestion d'actifs",
        "location": {"city": "Paris", "country": "fr"}, "releasedDate": "2026-11-02T00:00:00Z", "typeOfEmployment": {"label": "Stage"}}]},
    "myworkdayjobs.com": {"jobPostings": [{"title": "Graduate Programme - Global Markets", "externalPath": "/job/London/X_1",
        "locationsText": "London", "postedOn": "Posted 3 Days Ago"}]},
    "oraclecloud.com": {"items": [{"TotalJobsCount": 1, "requisitionList": [{"Id": "210", "Title": "2027 Investment Banking Summer Analyst",
        "PostedDate": "2026-11-05", "PrimaryLocation": "New York, NY, United States", "secondaryLocations": [{"Name": "London, United Kingdom"}]}]}]},
    "apply.workable.com": {"jobs": [{"title": "Private Equity Analyst", "city": "Paris", "country": "France", "shortcode": "AB1",
        "published_on": "2026-11-03"}]},
    "recruitee.com": {"offers": [{"title": "Stage M&A", "city": "Lyon", "country": "France", "careers_url": "https://x/rc/1",
        "published_at": "2026-11-03 10:00:00 UTC"}]},
    "taleo.net/careersection/rest": {"requisitionList": [{"contestNo": "250001", "column": ["Stage - Analyste Risque de crédit",
        "[\"France-Paris\"]", "Nov 6, 2026"]}]},
    "civiweb": {"count": 1, "result": [{"id": 123, "missionTitle": "VIE Analyste M&A", "organizationName": "BNP Paribas",
        "cityNameEn": "Singapore", "countryNameEn": "Singapore", "missionStartDate": "2027-03-01T00:00:00", "missionDuration": 12,
        "creationDate": "2026-11-05T00:00:00"}]},
}
TEXT = {
    "personio.de/xml": "<workzag-jobs><position><id>7</id><name>Werkstudent Corporate Finance</name><office>Frankfurt</office>"
                       "<createdAt>2026-11-01T09:00:00+00:00</createdAt><employmentType>intern</employmentType></position></workzag-jobs>",
    "taleo.net/careersection/sg/jobsearch": "<script>var x = 'portal=101430233';</script>",
    "careers.ex.com/ex/search": '<table><tr class="data-row"><td><a class="jobTitle-link" href="/ex/job/Paris-Analyste/1/">Analyste Transaction Services'
                                '</a></td><td><span class="jobLocation">Paris, FR</span></td><td><span class="jobDate">Nov 4, 2026</span></td></tr></table>',
    "mycareer.ex.com": '<ul><li><a href="https://mycareer.ex.com/en_GB/external/JobDetail/Global-Markets-Analyst/123">Global Markets Analyst Programme'
                       '</a><span>Hong Kong · Graduate</span></li></ul>',
    "bank.ex.com/careers?page=0": '<div><a href="/careers/job-offer/m-a-analyst-intern">M&amp;A Analyst Intern</a> <span>Internship · Paris, France</span></div>',
    "bank.ex.com/careers?page=1": '<div></div>',
    "fund.ex.com/career-sitemap.xml": '<urlset><url><loc>https://fund.ex.com/careers/details/quantitative-researcher-london/</loc>'
                                      '<lastmod>2026-11-02T10:00:00+00:00</lastmod></url><url><loc>https://fund.ex.com/about/</loc></url></urlset>',
}


def fake_get(url, **kw):
    if "absent" in url:
        raise RuntimeError("404")
    for k, v in JSON.items():
        if k in url:
            return v
    raise RuntimeError(f"404 {url}")


def fake_text(url, **kw):
    for k, v in TEXT.items():
        if k in url:
            return v
    raise RuntimeError(f"404 {url}")


connectors.http.get = fake_get
connectors.http.post = lambda url, **kw: fake_get(url)
connectors.http.text = fake_text
connectors.http.request = lambda m, url, as_json=True, **kw: (fake_get(url) if as_json else fake_text(url))

T = "Corporate & Investment Bank"
cases = [
    ("greenhouse", {"token": "acme"}), ("lever", {"token": "acme"}), ("ashby", {"token": "acme"}),
    ("smartrecruiters", {"token": "acme"}), ("workday", {"url": "https://ms.wd5.myworkdayjobs.com/External", "search": ["analyst"]}),
    ("oracle", {"host": "jpmc.fa.oraclecloud.com", "site": "CX_1001", "search": []}), ("workable", {"token": "acme"}),
    ("recruitee", {"token": "acme"}), ("personio", {"token": "acme"}), ("taleo", {"host": "ex.taleo.net", "section": "sg", "max_pages": 1}),
    ("successfactors", {"url": "https://careers.ex.com/ex", "search": ["analyst"]}),
    ("avature", {"url": "https://mycareer.ex.com/en_GB/external/SearchJobs", "max_rows": 50}),
    ("html", {"pages": "https://bank.ex.com/careers?page={page}", "first_page": 0, "link": "/careers/job-offer/"}),
    ("sitemap", {"url": "https://fund.ex.com/career-sitemap.xml", "link": "/careers/details/"}),
]
print(f"{'connecteur':15} {'contrat':10} {'métier':28} {'ville':10} {'pays':12} {'début':9} publié")
for kind, cfg in cases:
    rows = list(connectors.CONNECTORS[kind]({"name": "Test", "type": T, **cfg}))
    assert rows, f"{kind}: aucune offre"
    j = scrape.enrich(rows[0])
    assert j, f"{kind}: offre rejetée ({rows[0]['title']})"
    print(f"{kind:15} {j['contract']:10} {j['specialisation']:28} {j['city']:10} {j['country']:12} {j['start']:9} {j['posted'][:10]}")
vie = [scrape.enrich(r) for r in scrape.src_vie({})]
assert vie[0]["contract"] == "VIE" and vie[0]["specialisation"] == "M&A"
print("VIE Business France OK")

# --- détection de plateforme
pages = {
    "workday": '<a href="https://mufgub.wd3.myworkdayjobs.com/en-US/MUFG-Careers/job/x">Apply</a>',
    "greenhouse": '<script src="https://boards.greenhouse.io/embed/job_board/js?for=squarepointcapital"></script>',
    "lever": '<a href="https://jobs.lever.co/qube-rt/abc">Job</a>',
    "oracle": '<a href="https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions">Jobs</a>',
    "taleo": '<a href="https://socgen.taleo.net/careersection/sgcareers/profile.ftl?lang=en">Profil</a>',
    "smartrecruiters": '<a href="https://careers.smartrecruiters.com/Natixis">Offres</a>',
    "personio": '<iframe src="https://falkensteg.jobs.personio.de/"></iframe>',
    "successfactors": '<link href="https://rmkcdn.successfactors.com/x.css"><a href="/ey/search/?q=">Search</a>',
}
for kind, page in pages.items():
    found = disc.detect(page, "https://careers.example.com/x")
    assert found and found[0][0] == kind, (kind, found)
    print(f"détection {kind:15} -> {json.dumps(found[0][1])}")
assert disc.slug_variants("Rothschild & Co")[:2] == ["rothschildandco", "rothschild"]

# --- repli : connecteur explicite en panne -> détection depuis la page carrières
disc.http.text = lambda url, **kw: pages["greenhouse"]
scrape.discover = disc.discover
rows, method, err = scrape.run_company({"name": "X", "type": T, "ats": "lever", "token": "absent",
                                        "careers": "https://x.com/careers"}, {}, {})
print("repli:", method, len(rows), "offre(s)", err)
assert method == "greenhouse (détecté)" and rows
print("TOUS LES TESTS OK")
