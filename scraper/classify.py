"""Classification des offres : type de contrat, métier finance, localisation, date de début."""
from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- utils

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.I)


# --------------------------------------------------------------------------- contrat

CONTRACTS = ["Stage", "Graduate", "CDI", "VIE", "Alternance", "Spring week"]

_VIE = rx(r"\bv\.?\s?i\.?\s?e\.?\b", r"volontariat international")
_ALT = rx(r"apprenti", r"alternan", r"\bapprenticeship", r"duales? stud", r"ausbildung", r"work[- ]study")
_INSIGHT = rx(r"spring (week|insight)", r"insight (programme|program|week|day)", r"discovery (day|week)", r"open day")
_STAGE = rx(r"\bintern\b", r"\binterns\b", r"internship", r"\bstage\b", r"stagiaire", r"summer (analyst|associate)",
            r"off[- ]cycle", r"placement", r"praktik", r"werkstudent", r"working student", r"\bco-?op\b",
            r"micro-intern", r"pr[aá]cticas", r"tirocinio", r"stagista")
_GRAD = rx(r"graduate", r"\bgrad\b", r"campus", r"new grad", r"early careers?", r"analyst program",
           r"associate program", r"\btrainee", r"rotational", r"\bacademy\b", r"class of 20\d\d", r"\bjunior analyst program")
_EXPERIENCED = rx(r"experienced professional", r"\bsenior\b", r"\blead\b", r"\bhead of\b")


def classify_contract(title: str, hint: str = "", forced: str | None = None) -> str:
    if forced:
        return forced
    t = f"{title} {hint}"
    if _VIE.search(t):
        return "VIE"
    if _ALT.search(t):
        return "Alternance"
    if _INSIGHT.search(t):
        return "Spring week"
    if _STAGE.search(t) or re.search(r"\bintern", hint or "", re.I):
        return "Stage"
    if _GRAD.search(t) and not _EXPERIENCED.search(t):
        return "Graduate"
    return "CDI"


# --------------------------------------------------------------------------- métier

FRONT = "Front office"
SUPPORT = "Middle / Back office"

# L'ordre compte : la première règle qui matche gagne.
SPECIALISATIONS: list[tuple[str, str, re.Pattern]] = [
    ("M&A", FRONT, rx(r"\bm&a\b", r"\bm ?& ?a\b", r"(?<![a-z])m a(?![a-z])", r"\bm-a\b", r"mergers", r"fusions", r"acquisitions")),
    ("Private Equity & VC", FRONT, rx(r"private equity", r"buy-?out", r"growth equity", r"venture capital", r"\bvc\b",
                                       r"capital[- ]investissement", r"infrastructure invest")),
    ("Investment Banking", FRONT, rx(r"investment bank", r"\bibd\b", r"coverage", r"\becm\b", r"\bdcm\b", r"leveraged finance",
                                      r"lev ?fin", r"corporate finance advisory", r"financial institutions group", r"\bfig\b",
                                      r"banque d'affaires", r"capital markets", r"origination")),
    ("Compliance", SUPPORT, rx(r"compliance", r"\baml\b", r"\bkyc\b", r"surveillance", r"regulatory", r"conformit",
                               r"financial crime", r"sanctions")),
    ("Risk", SUPPORT, rx(r"\brisk\b", r"risque", r"\balm\b", r"asset liability", r"credit risk", r"market risk")),
    ("Opérations", SUPPORT, rx(r"middle[- ]office", r"back[- ]office", r"mid office", r"trade support", r"operations analyst",
                               r"settlement", r"reconciliation", r"fund accounting", r"onboarding", r"trade capture",
                               r"\bops\b", r"operations associate")),
    ("Quant", FRONT, rx(r"\bquant", r"alpha research", r"systematic", r"statistical arbitrage", r"strat\b")),
    ("Sales & Trading", FRONT, rx(r"\btrader\b", r"\btrading\b", r"sales[- ]trad", r"institutional sales", r"structur",
                                   r"market[- ]mak", r"\bbroker\b", r"\bdesk\b", r"delta one", r"\bfx\b", r"rates", r"global markets", r"march[eé]s financiers",
                                   r"\bsales\b.*(equit|fixed income|credit|derivat)", r"salle des march")),
    ("Research", FRONT, rx(r"research analyst", r"equity research", r"sector analyst", r"macro analyst", r"credit research",
                           r"fundamental research", r"investment analyst", r"commodit(y|ies) analyst", r"equity analyst",
                           r"economist", r"strategist", r"recherche")),
    ("Wealth Management", FRONT, rx(r"wealth", r"private bank", r"relationship manager", r"family office",
                                     r"gestion de patrimoine", r"banque priv")),
    ("Asset Management", FRONT, rx(r"asset management", r"portfolio manag", r"\bfunds?\b", r"investment services",
                                    r"investment (team|professional)", r"gestion d'actifs", r"real estate invest",
                                    r"product strategist", r"\binvestment\b")),
    ("Crédit & Financement", FRONT, rx(r"credit analyst", r"\bcredit\b", r"lending", r"structured finance",
                                        r"mortgage", r"high yield", r"distressed", r"project finance", r"\bloans?\b",
                                        r"financement")),
    ("Audit & Transaction Services", SUPPORT, rx(r"\baudit", r"transaction services", r"due diligence", r"valuation",
                                                  r"\bdeals?\b", r"advisory")),
    ("Corporate Finance & Contrôle", SUPPORT, rx(r"controll", r"contr[oô]leu?r", r"contr[oô]le de gestion", r"\bfp&a\b", r"financial planning",
                                                  r"accounting", r"accountant", r"comptab", r"treasury", r"tr[eé]sor",
                                                  r"\btax\b", r"fiscal", r"reporting", r"finance analyst", r"financial analyst",
                                                  r"\bfinance\b", r"\bcfo\b")),
    ("Programmes multi-métiers", FRONT, rx(r"insight", r"\bacademy\b", r"programme", r"\bprogram\b", r"rotational",
                                            r"summer analyst", r"off[- ]cycle", r"spring week", r"graduate scheme")),
]

SPEC_NAMES = [s[0] for s in SPECIALISATIONS]

# Rôles non finance à écarter (sauf s'ils contiennent "quant")
_EXCLUDE = rx(r"software engineer", r"\bdeveloper\b", r"d[eé]veloppeur", r"data engineer", r"network", r"\bit\b",
              r"\bhr\b", r"human resources", r"recruit", r"talent acquisition", r"payroll", r"assistant(?! vice)", r"office manager",
              r"cloud", r"security engineer", r"site reliability", r"\bsre\b", r"devops", r"linux", r"hardware",
              r"machine learning engineer", r"designer", r"marketing", r"communications?", r"legal counsel",
              r"facilities", r"receptionist", r"chef\b", r"engineer\b(?!.*quant)", r"event", r"procurement",
              r"psycholog", r"instructor", r"coach")


def classify_specialisation(title: str, extra: str = "") -> tuple[str, str] | None:
    t = norm(f"{title} {extra}")
    if _EXCLUDE.search(t) and "quant" not in t:
        return None
    for name, family, pat in SPECIALISATIONS:
        if pat.search(t):
            return name, family
    return None


# --------------------------------------------------------------------------- localisation

REGIONS = {
    "Europe": ["France", "Royaume-Uni", "Allemagne", "Suisse", "Luxembourg", "Belgique", "Pays-Bas", "Irlande", "Italie",
               "Espagne", "Portugal", "Pologne", "Danemark", "Suède", "Norvège", "Finlande", "Autriche", "République tchèque",
               "Hongrie", "Grèce", "Roumanie", "Monaco", "Slovaquie", "Bulgarie", "Chypre", "Malte", "Jersey", "Guernesey",
               "Estonie", "Lettonie", "Lituanie", "Croatie", "Slovénie", "Serbie", "Islande", "Ukraine"],
    "Amérique du Nord": ["États-Unis", "Canada", "Bermudes", "Îles Caïmans"],
    "Amérique latine": ["Brésil", "Mexique", "Chili", "Colombie", "Argentine", "Pérou", "Uruguay", "Panama",
                        "Costa Rica"],
    "Asie-Pacifique": ["Hong Kong", "Singapour", "Japon", "Chine", "Inde", "Australie", "Corée du Sud", "Taïwan",
                       "Indonésie", "Malaisie", "Thaïlande", "Vietnam", "Philippines", "Nouvelle-Zélande", "Sri Lanka", "Pakistan",
                       "Bangladesh", "Kazakhstan"],
    "Moyen-Orient & Afrique": ["Émirats arabes unis", "Arabie saoudite", "Qatar", "Israël", "Afrique du Sud", "Maroc",
                               "Égypte", "Nigeria", "Kenya", "Turquie", "Bahreïn", "Koweït", "Côte d'Ivoire", "Sénégal"],
}
COUNTRY_REGION = {c: r for r, cs in REGIONS.items() for c in cs}

# alias pays -> nom affiché
COUNTRY_ALIASES = {
    "france": "France", "united kingdom": "Royaume-Uni", "uk": "Royaume-Uni", "england": "Royaume-Uni",
    "great britain": "Royaume-Uni", "royaume-uni": "Royaume-Uni", "scotland": "Royaume-Uni",
    "germany": "Allemagne", "deutschland": "Allemagne", "allemagne": "Allemagne",
    "switzerland": "Suisse", "suisse": "Suisse", "schweiz": "Suisse", "luxembourg": "Luxembourg",
    "belgium": "Belgique", "belgique": "Belgique", "netherlands": "Pays-Bas", "pays-bas": "Pays-Bas",
    "ireland": "Irlande", "italy": "Italie", "italie": "Italie", "spain": "Espagne", "espagne": "Espagne",
    "portugal": "Portugal", "poland": "Pologne", "pologne": "Pologne", "denmark": "Danemark", "sweden": "Suède",
    "norway": "Norvège", "finland": "Finlande", "austria": "Autriche", "czech republic": "République tchèque",
    "czechia": "République tchèque", "republique tcheque": "République tchèque", "hungary": "Hongrie",
    "greece": "Grèce", "romania": "Roumanie", "monaco": "Monaco",
    "united states": "États-Unis", "usa": "États-Unis", "u.s.": "États-Unis", "etats-unis": "États-Unis",
    "us": "États-Unis", "canada": "Canada", "brazil": "Brésil", "bresil": "Brésil", "mexico": "Mexique",
    "chile": "Chili", "colombia": "Colombie", "argentina": "Argentine", "peru": "Pérou",
    "hong kong": "Hong Kong", "singapore": "Singapour", "singapour": "Singapour", "japan": "Japon", "japon": "Japon",
    "china": "Chine", "chine": "Chine", "india": "Inde", "inde": "Inde", "australia": "Australie",
    "south korea": "Corée du Sud", "korea": "Corée du Sud", "taiwan": "Taïwan", "indonesia": "Indonésie",
    "malaysia": "Malaisie", "thailand": "Thaïlande", "vietnam": "Vietnam", "philippines": "Philippines",
    "new zealand": "Nouvelle-Zélande",
    "united arab emirates": "Émirats arabes unis", "uae": "Émirats arabes unis", "emirats arabes unis": "Émirats arabes unis",
    "saudi arabia": "Arabie saoudite", "qatar": "Qatar", "israel": "Israël", "south africa": "Afrique du Sud",
    "morocco": "Maroc", "maroc": "Maroc", "egypt": "Égypte", "nigeria": "Nigeria", "kenya": "Kenya",
    "turkey": "Turquie", "turkiye": "Turquie", "bahrain": "Bahreïn", "kuwait": "Koweït",
    "cote d'ivoire": "Côte d'Ivoire", "ivory coast": "Côte d'Ivoire", "senegal": "Sénégal",
    "slovakia": "Slovaquie", "bulgaria": "Bulgarie", "cyprus": "Chypre", "malta": "Malte", "jersey": "Jersey",
    "guernsey": "Guernesey", "estonia": "Estonie", "latvia": "Lettonie", "lithuania": "Lituanie", "croatia": "Croatie",
    "slovenia": "Slovénie", "serbia": "Serbie", "iceland": "Islande", "ukraine": "Ukraine", "sri lanka": "Sri Lanka",
    "pakistan": "Pakistan", "bangladesh": "Bangladesh", "kazakhstan": "Kazakhstan", "bermuda": "Bermudes",
    "cayman islands": "Îles Caïmans", "uruguay": "Uruguay", "panama": "Panama", "costa rica": "Costa Rica",
    "deutschland": "Allemagne", "nederland": "Pays-Bas", "espana": "Espagne", "italia": "Italie", "osterreich": "Autriche",
    "belgie": "Belgique", "polska": "Pologne", "schweiz": "Suisse", "brasil": "Brésil",
}

ISO2 = {"FR": "France", "GB": "Royaume-Uni", "UK": "Royaume-Uni", "DE": "Allemagne", "CH": "Suisse", "LU": "Luxembourg",
        "BE": "Belgique", "NL": "Pays-Bas", "IE": "Irlande", "IT": "Italie", "ES": "Espagne", "PT": "Portugal",
        "PL": "Pologne", "DK": "Danemark", "SE": "Suède", "NO": "Norvège", "FI": "Finlande", "AT": "Autriche",
        "CZ": "République tchèque", "HU": "Hongrie", "GR": "Grèce", "RO": "Roumanie", "SK": "Slovaquie", "BG": "Bulgarie",
        "CY": "Chypre", "MT": "Malte", "US": "États-Unis", "CA": "Canada", "BR": "Brésil", "MX": "Mexique", "CL": "Chili",
        "CO": "Colombie", "AR": "Argentine", "PE": "Pérou", "HK": "Hong Kong", "SG": "Singapour", "JP": "Japon",
        "CN": "Chine", "IN": "Inde", "AU": "Australie", "KR": "Corée du Sud", "TW": "Taïwan", "ID": "Indonésie",
        "MY": "Malaisie", "TH": "Thaïlande", "VN": "Vietnam", "PH": "Philippines", "NZ": "Nouvelle-Zélande",
        "AE": "Émirats arabes unis", "SA": "Arabie saoudite", "QA": "Qatar", "IL": "Israël", "ZA": "Afrique du Sud",
        "MA": "Maroc", "EG": "Égypte", "NG": "Nigeria", "KE": "Kenya", "TR": "Turquie", "BH": "Bahreïn", "LK": "Sri Lanka"}
ISO3 = {"FRA": "France", "GBR": "Royaume-Uni", "DEU": "Allemagne", "CHE": "Suisse", "LUX": "Luxembourg", "BEL": "Belgique",
        "NLD": "Pays-Bas", "IRL": "Irlande", "ITA": "Italie", "ESP": "Espagne", "PRT": "Portugal", "POL": "Pologne",
        "USA": "États-Unis", "CAN": "Canada", "BRA": "Brésil", "MEX": "Mexique", "HKG": "Hong Kong", "SGP": "Singapour",
        "JPN": "Japon", "CHN": "Chine", "IND": "Inde", "AUS": "Australie", "PHL": "Philippines", "MYS": "Malaisie",
        "ARE": "Émirats arabes unis", "ZAF": "Afrique du Sud", "CZE": "République tchèque", "HUN": "Hongrie",
        "ROU": "Roumanie", "SVK": "Slovaquie", "BGR": "Bulgarie", "AUT": "Autriche", "SWE": "Suède", "DNK": "Danemark",
        "NOR": "Norvège", "FIN": "Finlande", "KOR": "Corée du Sud", "TWN": "Taïwan", "IDN": "Indonésie", "THA": "Thaïlande",
        "ARG": "Argentine", "CHL": "Chili", "COL": "Colombie", "PER": "Pérou", "LKA": "Sri Lanka", "CRI": "Costa Rica"}
US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
             "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
             "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR"}

# alias ville -> (ville affichée, pays)
CITIES = {
    "paris": ("Paris", "France"), "la defense": ("Paris", "France"), "lyon": ("Lyon", "France"),
    "marseille": ("Marseille", "France"), "lille": ("Lille", "France"), "bordeaux": ("Bordeaux", "France"),
    "nantes": ("Nantes", "France"), "toulouse": ("Toulouse", "France"), "nice": ("Nice", "France"),
    "london": ("Londres", "Royaume-Uni"), "londres": ("Londres", "Royaume-Uni"), "edinburgh": ("Édimbourg", "Royaume-Uni"),
    "manchester": ("Manchester", "Royaume-Uni"), "glasgow": ("Glasgow", "Royaume-Uni"),
    "frankfurt": ("Francfort", "Allemagne"), "francfort": ("Francfort", "Allemagne"), "munich": ("Munich", "Allemagne"),
    "munchen": ("Munich", "Allemagne"), "berlin": ("Berlin", "Allemagne"), "hamburg": ("Hambourg", "Allemagne"),
    "dusseldorf": ("Düsseldorf", "Allemagne"), "cologne": ("Cologne", "Allemagne"),
    "zurich": ("Zurich", "Suisse"), "geneva": ("Genève", "Suisse"), "geneve": ("Genève", "Suisse"),
    "zug": ("Zoug", "Suisse"), "lausanne": ("Lausanne", "Suisse"), "basel": ("Bâle", "Suisse"),
    "luxembourg": ("Luxembourg", "Luxembourg"), "brussels": ("Bruxelles", "Belgique"), "bruxelles": ("Bruxelles", "Belgique"),
    "amsterdam": ("Amsterdam", "Pays-Bas"), "rotterdam": ("Rotterdam", "Pays-Bas"), "dublin": ("Dublin", "Irlande"),
    "milan": ("Milan", "Italie"), "milano": ("Milan", "Italie"), "rome": ("Rome", "Italie"),
    "madrid": ("Madrid", "Espagne"), "barcelona": ("Barcelone", "Espagne"), "lisbon": ("Lisbonne", "Portugal"),
    "lisboa": ("Lisbonne", "Portugal"), "porto": ("Porto", "Portugal"), "warsaw": ("Varsovie", "Pologne"),
    "warszawa": ("Varsovie", "Pologne"), "krakow": ("Cracovie", "Pologne"), "wroclaw": ("Wroclaw", "Pologne"),
    "copenhagen": ("Copenhague", "Danemark"), "aarhus": ("Aarhus", "Danemark"), "stockholm": ("Stockholm", "Suède"),
    "oslo": ("Oslo", "Norvège"), "helsinki": ("Helsinki", "Finlande"), "vienna": ("Vienne", "Autriche"),
    "prague": ("Prague", "République tchèque"), "pisek": ("Písek", "République tchèque"),
    "budapest": ("Budapest", "Hongrie"), "athens": ("Athènes", "Grèce"), "bucharest": ("Bucarest", "Roumanie"),
    "monaco": ("Monaco", "Monaco"),
    "new york": ("New York", "États-Unis"), "nyc": ("New York", "États-Unis"), "stamford": ("Stamford", "États-Unis"),
    "greenwich": ("Greenwich", "États-Unis"), "chicago": ("Chicago", "États-Unis"), "boston": ("Boston", "États-Unis"),
    "san francisco": ("San Francisco", "États-Unis"), "los angeles": ("Los Angeles", "États-Unis"),
    "miami": ("Miami", "États-Unis"), "west palm beach": ("West Palm Beach", "États-Unis"),
    "charlotte": ("Charlotte", "États-Unis"), "houston": ("Houston", "États-Unis"), "dallas": ("Dallas", "États-Unis"),
    "austin": ("Austin", "États-Unis"), "seattle": ("Seattle", "États-Unis"), "washington": ("Washington", "États-Unis"),
    "jersey city": ("Jersey City", "États-Unis"), "philadelphia": ("Philadelphie", "États-Unis"),
    "atlanta": ("Atlanta", "États-Unis"), "denver": ("Denver", "États-Unis"),
    "toronto": ("Toronto", "Canada"), "montreal": ("Montréal", "Canada"), "vancouver": ("Vancouver", "Canada"),
    "sao paulo": ("São Paulo", "Brésil"), "mexico city": ("Mexico", "Mexique"), "santiago": ("Santiago", "Chili"),
    "bogota": ("Bogotá", "Colombie"), "buenos aires": ("Buenos Aires", "Argentine"), "lima": ("Lima", "Pérou"),
    "hong kong": ("Hong Kong", "Hong Kong"), "singapore": ("Singapour", "Singapour"), "tokyo": ("Tokyo", "Japon"),
    "osaka": ("Osaka", "Japon"), "shanghai": ("Shanghai", "Chine"), "beijing": ("Pékin", "Chine"),
    "shenzhen": ("Shenzhen", "Chine"), "mumbai": ("Mumbai", "Inde"), "bengaluru": ("Bangalore", "Inde"),
    "bangalore": ("Bangalore", "Inde"), "gurgaon": ("Gurgaon", "Inde"), "gurugram": ("Gurgaon", "Inde"),
    "hyderabad": ("Hyderabad", "Inde"), "pune": ("Pune", "Inde"), "chennai": ("Chennai", "Inde"),
    "sydney": ("Sydney", "Australie"), "melbourne": ("Melbourne", "Australie"), "seoul": ("Séoul", "Corée du Sud"),
    "taipei": ("Taipei", "Taïwan"), "jakarta": ("Jakarta", "Indonésie"), "kuala lumpur": ("Kuala Lumpur", "Malaisie"),
    "bangkok": ("Bangkok", "Thaïlande"), "ho chi minh": ("Hô Chi Minh-Ville", "Vietnam"), "manila": ("Manille", "Philippines"),
    "auckland": ("Auckland", "Nouvelle-Zélande"),
    "dubai": ("Dubaï", "Émirats arabes unis"), "abu dhabi": ("Abu Dhabi", "Émirats arabes unis"),
    "riyadh": ("Riyad", "Arabie saoudite"), "doha": ("Doha", "Qatar"), "tel aviv": ("Tel Aviv", "Israël"),
    "johannesburg": ("Johannesburg", "Afrique du Sud"), "cape town": ("Le Cap", "Afrique du Sud"),
    "casablanca": ("Casablanca", "Maroc"), "cairo": ("Le Caire", "Égypte"), "lagos": ("Lagos", "Nigeria"),
    "nairobi": ("Nairobi", "Kenya"), "istanbul": ("Istanbul", "Turquie"), "manama": ("Manama", "Bahreïn"),
    "abidjan": ("Abidjan", "Côte d'Ivoire"), "dakar": ("Dakar", "Sénégal"),
    "neuilly": ("Neuilly-sur-Seine", "France"), "puteaux": ("Puteaux", "France"), "courbevoie": ("Courbevoie", "France"),
    "marcq-en-barœul": ("Marcq-en-Barœul", "France"), "marcq en baroeul": ("Marcq-en-Barœul", "France"),
    "boulogne-billancourt": ("Boulogne-Billancourt", "France"), "montrouge": ("Montrouge", "France"),
    "saint-denis": ("Saint-Denis", "France"), "nanterre": ("Nanterre", "France"), "levallois": ("Levallois-Perret", "France"),
    "strasbourg": ("Strasbourg", "France"), "rennes": ("Rennes", "France"), "montpellier": ("Montpellier", "France"),
    "canary wharf": ("Londres", "Royaume-Uni"), "nottingham": ("Nottingham", "Royaume-Uni"), "leeds": ("Leeds", "Royaume-Uni"),
    "birmingham": ("Birmingham", "Royaume-Uni"), "bristol": ("Bristol", "Royaume-Uni"), "belfast": ("Belfast", "Royaume-Uni"),
    "cardiff": ("Cardiff", "Royaume-Uni"), "saint helier": ("Saint-Hélier", "Jersey"), "st helier": ("Saint-Hélier", "Jersey"),
    "diegem": ("Diegem", "Belgique"), "antwerp": ("Anvers", "Belgique"), "wien": ("Vienne", "Autriche"),
    "bratislava": ("Bratislava", "Slovaquie"), "nicosia": ("Nicosie", "Chypre"), "limassol": ("Limassol", "Chypre"),
    "sofia": ("Sofia", "Bulgarie"), "gdynia": ("Gdynia", "Pologne"), "gdansk": ("Gdansk", "Pologne"), "lodz": ("Lodz", "Pologne"),
    "boadilla": ("Madrid", "Espagne"), "valletta": ("La Valette", "Malte"), "tallinn": ("Tallinn", "Estonie"),
    "vilnius": ("Vilnius", "Lituanie"), "riga": ("Riga", "Lettonie"), "zagreb": ("Zagreb", "Croatie"),
    "frankfurt am main": ("Francfort", "Allemagne"), "stuttgart": ("Stuttgart", "Allemagne"), "eschborn": ("Eschborn", "Allemagne"),
    "baltimore": ("Baltimore", "États-Unis"), "cincinnati": ("Cincinnati", "États-Unis"), "pittsburgh": ("Pittsburgh", "États-Unis"),
    "minneapolis": ("Minneapolis", "États-Unis"), "mclean": ("McLean", "États-Unis"), "milwaukee": ("Milwaukee", "États-Unis"),
    "cleveland": ("Cleveland", "États-Unis"), "richmond": ("Richmond", "États-Unis"), "detroit": ("Detroit", "États-Unis"),
    "owings mills": ("Owings Mills", "États-Unis"), "phoenix": ("Phoenix", "États-Unis"), "san diego": ("San Diego", "États-Unis"),
    "salt lake city": ("Salt Lake City", "États-Unis"), "columbus": ("Columbus", "États-Unis"), "st. louis": ("Saint-Louis", "États-Unis"),
    "nashville": ("Nashville", "États-Unis"), "tampa": ("Tampa", "États-Unis"), "jacksonville": ("Jacksonville", "États-Unis"),
    "wilmington": ("Wilmington", "États-Unis"), "princeton": ("Princeton", "États-Unis"), "newark": ("Newark", "États-Unis"),
    "palo alto": ("Palo Alto", "États-Unis"), "menlo park": ("Menlo Park", "États-Unis"), "west palm": ("West Palm Beach", "États-Unis"),
    "new delhi": ("New Delhi", "Inde"), "delhi": ("New Delhi", "Inde"), "noida": ("Noida", "Inde"), "kolkata": ("Kolkata", "Inde"),
    "kochi": ("Kochi", "Inde"), "ahmedabad": ("Ahmedabad", "Inde"), "gandhinagar": ("Gandhinagar", "Inde"),
    "makati": ("Manille", "Philippines"), "quezon": ("Manille", "Philippines"), "taguig": ("Manille", "Philippines"),
    "pasig": ("Manille", "Philippines"), "cebu": ("Cebu", "Philippines"), "kwun tong": ("Hong Kong", "Hong Kong"),
    "island east": ("Hong Kong", "Hong Kong"), "quarry bay": ("Hong Kong", "Hong Kong"), "kowloon": ("Hong Kong", "Hong Kong"),
    "colombo": ("Colombo", "Sri Lanka"), "caba": ("Buenos Aires", "Argentine"), "hamilton": ("Hamilton", "Bermudes"),
    "george town": ("George Town", "Îles Caïmans"), "montevideo": ("Montevideo", "Uruguay"), "san jose": ("San José", "Costa Rica"),
    "guangzhou": ("Canton", "Chine"), "chengdu": ("Chengdu", "Chine"), "dalian": ("Dalian", "Chine"), "suzhou": ("Suzhou", "Chine"),
    "brisbane": ("Brisbane", "Australie"), "perth": ("Perth", "Australie"), "toronto": ("Toronto", "Canada"),
    "calgary": ("Calgary", "Canada"), "ottawa": ("Ottawa", "Canada"), "quebec": ("Québec", "Canada"), "levis": ("Lévis", "Canada"),
}

_US_STATES = re.compile(r",\s*(NY|CT|IL|CA|MA|FL|TX|NJ|NC|WA|GA|PA|CO|DC)\b")


def _find_all(text: str, table: dict) -> list[tuple[int, str]]:
    out = []
    for alias in table:
        for m in re.finditer(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", text):
            out.append((m.start(), alias))
    out.sort()
    return out


def parse_location(raw: str, city_hint: str = "", country_hint: str = "") -> dict:
    """Renvoie {city, country, countries[], region, raw}."""
    text = norm(f"{raw} | {city_hint} | {country_hint}")
    cities = _find_all(text, CITIES)
    countries: list[str] = []
    city = ""
    for _, alias in cities:
        c, ctry = CITIES[alias]
        if not city:
            city = c
        if ctry not in countries:
            countries.append(ctry)
    for _, alias in _find_all(text, COUNTRY_ALIASES):
        ctry = COUNTRY_ALIASES[alias]
        if alias == "us" and not re.search(r"(?<![a-z])us(?![a-z])", norm(raw)):
            continue
        if ctry not in countries:
            countries.append(ctry)
    if not countries:
        r = raw or ""
        m = re.search(r"\b([A-Z]{3})-", r)  # « PHL-Taguig », « POL-Gdynia »
        if m and m.group(1) in ISO3:
            countries.append(ISO3[m.group(1)])
        elif re.search(r",\s*IN,?\s*\d{6}\b", r):  # code postal indien à 6 chiffres
            countries.append("Inde")
        else:
            codes = re.findall(r"(?:^|[,\s])([A-Z]{2})(?=\s*(?:,|$|\s*-|\s*\(?\d))", r)
            us = [c for c in codes if c in US_STATES]
            iso = [c for c in codes if c in ISO2 and c not in US_STATES]
            if iso:
                countries.append(ISO2[iso[-1]])
            elif us or re.match(r"^\s*(%s)\s*-" % "|".join(US_STATES), r):
                countries.append("États-Unis")
            else:
                low = re.search(r",\s*([a-z]{2})\s*$", r)  # « Courbevoie, fr »
                if low and low.group(1).upper() in ISO2:
                    countries.append(ISO2[low.group(1).upper()])
        if countries and not city:
            first = re.split(r"[,(]", re.sub(r"^[A-Z]{2,3}\s*-\s*", "", r))[0].strip(" -")
            if first and not re.search(r"\d|locations?", first, re.I) and len(first) < 40 and not re.fullmatch(r"[A-Z]{2,3}", first):
                city = first.title() if first.isupper() else first
    country = countries[0] if countries else ""
    return {
        "city": city,
        "country": country,
        "countries": countries,
        "region": COUNTRY_REGION.get(country, "Autre" if country else ""),
        "remote": bool(re.search(r"remote|t[eé]l[eé]travail", text)),
    }


# --------------------------------------------------------------------------- date de début

_SEASONS = {"summer": "Été", "spring": "Printemps", "autumn": "Automne", "fall": "Automne", "winter": "Hiver",
            "ete": "Été", "printemps": "Printemps", "automne": "Automne", "hiver": "Hiver"}
_MONTHS = {"january": "Jan", "february": "Fév", "march": "Mars", "april": "Avr", "may": "Mai", "june": "Juin",
           "july": "Juil", "august": "Août", "september": "Sept", "october": "Oct", "november": "Nov", "december": "Déc",
           "janvier": "Jan", "fevrier": "Fév", "mars": "Mars", "avril": "Avr", "mai": "Mai", "juin": "Juin",
           "juillet": "Juil", "aout": "Août", "septembre": "Sept", "octobre": "Oct", "novembre": "Nov", "decembre": "Déc"}


def parse_start(title: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    t = norm(title)
    m = re.search(r"(" + "|".join(_SEASONS) + r")\s*(20\d\d)", t)
    if m:
        return f"{_SEASONS[m.group(1)]} {m.group(2)}"
    m = re.search(r"(" + "|".join(_MONTHS) + r")\s*(20\d\d)", t)
    if m:
        return f"{_MONTHS[m.group(1)]} {m.group(2)}"
    if "off-cycle" in t or "off cycle" in t:
        return "Off-cycle"
    m = re.search(r"\b(20\d\d)\b", t)
    if m:
        return m.group(1)
    return ""
