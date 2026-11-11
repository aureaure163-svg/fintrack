# FinTrack — tracker des offres en finance

Site qui recense en continu les **stages, graduate programmes, CDI, VIE, alternances et spring weeks** en finance,
dans le monde entier, à la manière de fyntraq.io/tracker.

- **Collecteur** (`scraper/`) : interroge directement les API publiques des pages carrières
  (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) et l'API Business France pour les VIE,
  garde uniquement les métiers finance, puis classe chaque offre (contrat, métier, pays, ville, date de début).
- **Site** (`site/`) : une page statique (HTML + JS, sans framework) avec filtres par contrat, pays (groupés par région),
  métier, type d'entreprise, entreprise, date de publication, recherche plein texte, raccourcis, vue tableau/cartes,
  pagination, watchlist (offres ★ + entreprises suivies), flux RSS pour les alertes.
- **Automatisation** (`.github/workflows/scrape.yml`) : GitHub Actions relance la collecte **toutes les 2 heures**,
  commit `site/data/jobs.json` et redéploie le site sur GitHub Pages. Gratuit, aucun serveur.

## Mise en ligne (10 minutes)

1. Créez un dépôt GitHub (ex. `fintrack`) et poussez-y ce dossier.
2. Dans le dépôt : **Settings → Pages → Source : GitHub Actions**.
3. **Actions → « Collecte des offres » → Run workflow**.
4. Le site est en ligne sur `https://<votre-pseudo>.github.io/fintrack/`, puis se met à jour tout seul.

Flux RSS des nouvelles offres : `https://<votre-pseudo>.github.io/fintrack/data/feed.xml`.

## En local

```bash
pip install -r requirements.txt
python scraper/scrape.py --check     # teste chaque source (OK / ERR + nombre d'offres finance)
python scraper/scrape.py             # collecte et écrit site/data/jobs.json + feed.xml
python -m http.server -d site 8000   # puis http://localhost:8000
python tests/test_sources.py         # tests hors-ligne des connecteurs
python scripts/build_preview.py      # dist/fintrack.html : site + données dans un seul fichier
```

## Entreprises suivies

`scraper/sources.yaml` contient **209 entreprises** (8 bulge brackets, 12 elite boutiques, 31 banques CIB,
30 fonds de private equity, ~100 hedge funds / sociétés de gestion / trading firms, 14 cabinets de conseil et audit…),
dont **184 avec un identifiant de plateforme connu**. Elles viennent de trois sources :

1. les 50 entreprises qui publient le plus d'offres sur Fyntraq (classement public de fyntraq.io/companies) ;
2. les listes Wikipédia (banques d'investissement, private equity, hedge funds, sociétés de gestion, plus grandes
   banques), croisées avec deux jeux de données publics sous licence MIT qui associent ~38 000 entreprises à leur
   identifiant Greenhouse / Lever / Ashby / Workday :
   [Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator) et
   [ConorsCode/open-jobs-data](https://github.com/ConorsCode/open-jobs-data) ;
3. des boutiques, fonds et sociétés de trading ajoutés à la main.

Les homonymes évidents ont été écartés (ex. « summit », « apollo » ou « maven » sur Greenhouse ne sont pas les
fonds du même nom). Les catégories d'entreprise reprennent celles de Fyntraq.

Chaque entreprise est branchée de l'une de ces deux façons :

```yaml
# 1. connecteur explicite (plateforme connue)
- { name: Barclays, type: Bulge Bracket, ats: workday, url: "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays" }

# 2. détection automatique : on donne juste la page carrières
- { name: Lazard, type: Elite Boutique, careers: "https://www.lazard.com/careers/jobs/" }
```

Pour (2), le collecteur lit la page carrières (et les pages liées), repère la plateforme
(Workday, Greenhouse, Oracle, Taleo…), mémorise le résultat dans `scraper/resolved.json` et l'utilise
aux passages suivants. Si un connecteur explicite tombe en panne, la détection prend aussi le relais.

### Connecteurs disponibles

| `ats:` | Plateforme | Paramètres | Exemples |
|---|---|---|---|
| `workday` | Workday | `url` | Citi, Morgan Stanley, Barclays, Deutsche Bank, BlackRock, MUFG, Houlihan Lokey |
| `oracle` | Oracle Recruiting Cloud | `host`, `site` | JPMorgan (`jpmc.fa.oraclecloud.com`, `CX_1001`) |
| `taleo` | Oracle Taleo | `host`, `section` | Société Générale (`socgen.taleo.net`, `sgcareers`) |
| `successfactors` | SAP SuccessFactors | `url` | EY (`https://careers.ey.com/ey`) |
| `avature` | Avature | `url` (page SearchJobs) | HSBC |
| `greenhouse` | Greenhouse | `token` | Jane Street, Point72, Jump, Tower, DRW, IMC |
| `lever` / `ashby` / `smartrecruiters` / `workable` / `recruitee` / `personio` | API publiques | `token` | |
| `html` | n'importe quelle page de liste | `pages` (avec `{page}`), `link` (regex des liens d'offres) | BNP Paribas |
| `sitemap` | sitemap XML du site | `url`, `link` | Citadel, Citadel Securities |

### Ajouter une entreprise (pour approcher les 1 500 de Fyntraq)

```bash
python scraper/discover.py "Ardian" https://www.ardian.com/careers
# → {"name": "Ardian", "ats": "workday", "url": "https://..."}   à coller dans sources.yaml
```

Sans URL, `discover.py` essaie aussi les identifiants probables sur Greenhouse, Lever, Ashby,
SmartRecruiters et Workable. Le plus simple : ajouter `careers:` et laisser la collecte faire le reste.

Une source en panne n'arrête jamais la collecte : elle est signalée en rouge dans le pied de page du site,
et ses offres de la collecte précédente sont conservées.

## Classification

`scraper/classify.py` contient toutes les règles, en anglais et en français :

- **Contrat** : VIE › Alternance › Spring week › Stage › Graduate › CDI (premier qui matche).
- **Métier** : M&A, Investment Banking, Private Equity & VC, Sales & Trading, Quant, Research, Asset Management,
  Wealth Management, Crédit & Financement, Risk, Compliance, Opérations, Audit & Transaction Services,
  Corporate Finance & Contrôle, Programmes multi-métiers. Les postes non finance (tech, RH, juridique…) sont écartés.
- **Lieu** : ~150 villes et 60 pays reconnus, regroupés par région.

Pour corriger une offre mal classée, ajoutez un mot-clé à la bonne règle et relancez.

## Limites connues

- **Banques et boutiques françaises** : beaucoup publient sur Welcome to the Jungle ou sur leur propre site,
  absents des jeux de données. Elles passent par la détection automatique ou le connecteur `html`.

- **Vérifié** (`verified: true`) : 12 sources testées à la main ; les 152 venues des jeux de données publics sont
  collectées chaque jour par ces projets, donc très probablement actives. Les ~25 restantes sont configurées d'après la page carrières de chaque
  entreprise mais n'ont pas pu être testées depuis l'environnement de développement ; le premier
  `python scraper/scrape.py --check` (ou le premier passage GitHub Actions) indique lesquelles répondent.
- **Goldman Sachs** n'est pas collecté : le `robots.txt` de higher.gs.com interdit la collecte automatique.
  De même, le collecteur saute toute page HTML interdite par le `robots.txt` d'un site (Crédit Agricole
  en fait peut-être partie) ; ces entreprises apparaissent en rouge dans le pied de page.
- Les grands cabinets (Deloitte, KPMG, PwC) ont un site carrières par pays : la détection automatique
  trouvera le site global, il faudra peut-être ajouter les sites France/UK à la main.
- L'API Business France n'est pas documentée officiellement ; si elle change, seul `src_vie` est à adapter.
- Respectez les conditions d'utilisation des sites : le collecteur fait peu de requêtes (toutes les 2 h),
  respecte `robots.txt` pour les pages HTML et renvoie toujours vers l'annonce d'origine.
