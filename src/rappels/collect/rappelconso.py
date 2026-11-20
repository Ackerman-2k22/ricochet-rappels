"""
Collecte des fiches RappelConso V2 dans data/bronze/rappels/ (couche bronze, jamais réécrite).

Chaque lancement relit les fiches publiées sur une fenêtre glissante (30 jours par défaut, plus
la durée d'une éventuelle interruption) pour attraper aussi les fiches modifiées, et n'écrit que
les couples (numero_fiche, numero_version) absents du dossier : relancé deux fois, il n'écrit rien
la seconde fois. Sans données existantes, il récupère tout l'historique (~6 Mo compressé).

Sortie : date=AAAA-MM-JJ/rappels_AAAAMMJJTHHMMSSZ.jsonl.gz, daté de la collecte (UTC).
Chaque fiche reçoit un champ _collecte_utc : c'est ce que l'on savait à cette heure-là.

Bibliothèque standard uniquement : le workflow horaire n'installe rien.
"""

import argparse
import gzip
import json
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

JEU = "rappelconso-v2-gtin-espaces"
URL_EXPORT = f"https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/{JEU}/exports/jsonl"


def cle(fiche):
    return fiche["numero_fiche"], fiche.get("numero_version")


def cles_connues(dossier):
    cles = set()
    for fichier in dossier.glob("date=*/*.jsonl.gz"):
        with gzip.open(fichier, "rt", encoding="utf-8") as f:
            cles.update(cle(json.loads(ligne)) for ligne in f if ligne.strip())
    return cles


def derniere_collecte(dossier):
    jours = [d.name.removeprefix("date=") for d in dossier.glob("date=*") if d.is_dir()]
    return date.fromisoformat(max(jours)) if jours else None


def telecharger(depuis=None):
    """Fiches publiées depuis la date donnée (toutes si None), dans l'ordre de publication."""
    params = {"order_by": "date_publication"}
    if depuis:
        params["where"] = f"date_publication >= date'{depuis:%Y-%m-%d}'"
    requete = urllib.request.Request(
        f"{URL_EXPORT}?{urllib.parse.urlencode(params)}",
        headers={"Accept-Encoding": "gzip", "User-Agent": "ricochet-rappels/0.1"},
    )
    with urllib.request.urlopen(requete, timeout=300) as reponse:
        corps = reponse.read()
        if reponse.headers.get("Content-Encoding") == "gzip":
            corps = gzip.decompress(corps)
    return [json.loads(ligne) for ligne in corps.decode("utf-8").splitlines() if ligne.strip()]


def collecter(dossier, jours=30, maintenant=None):
    """Écrit les fiches nouvelles ou modifiées. Renvoie (fichier écrit ou None, nombre de fiches)."""
    maintenant = maintenant or datetime.now(UTC)
    connues = cles_connues(dossier)
    depuis = None
    if connues:
        depuis = (maintenant - timedelta(days=jours)).date()
        derniere = derniere_collecte(dossier)
        if derniere:
            # Workflow interrompu plus longtemps que la fenêtre : on reprend avant la dernière collecte
            depuis = min(depuis, derniere - timedelta(days=2))

    nouvelles = {}
    for fiche in telecharger(depuis):
        if cle(fiche) not in connues:
            nouvelles[cle(fiche)] = fiche
    if not nouvelles:
        return None, 0

    sortie = (
        dossier / f"date={maintenant:%Y-%m-%d}" / f"rappels_{maintenant:%Y%m%dT%H%M%SZ}.jsonl.gz"
    )
    sortie.parent.mkdir(parents=True, exist_ok=True)
    horodatage = maintenant.isoformat(timespec="seconds")
    with gzip.open(sortie, "wt", encoding="utf-8") as f:
        for fiche in nouvelles.values():
            f.write(json.dumps({**fiche, "_collecte_utc": horodatage}, ensure_ascii=False) + "\n")
    return sortie, len(nouvelles)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dossier", default="data/bronze/rappels")
    ap.add_argument("--jours", type=int, default=30, help="fenêtre relue à chaque lancement")
    a = ap.parse_args()
    sortie, n = collecter(Path(a.dossier), a.jours)
    print(f"{n} fiche(s) écrite(s) dans {sortie}" if sortie else "Aucune fiche nouvelle.")


if __name__ == "__main__":
    main()
