"""Génère dist/fintrack.html : le site avec les données intégrées (un seul fichier, sans serveur)."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent.parent
html = (root / "site/index.html").read_text()
data = json.loads((root / "site/data/jobs.json").read_text())
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
out = root / "dist/fintrack.html"
out.parent.mkdir(exist_ok=True)
out.write_text(html.replace("/*__DATA__*/", f"window.__FINTRACK__={blob};", 1))
print(out, out.stat().st_size, "octets")
