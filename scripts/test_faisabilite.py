"""
Test de faisabilité — projet Rappels alimentaires
==================================================

Question : le lien « même usine, autre marque » existe-t-il assez souvent ?
Seuil de décision : au moins 200 rappels reliés à un produit d'une autre marque.

Entrées (à télécharger avant de lancer) :
  1. Export CSV de RappelConso V2 « Rappels de produits » (~26 Mo), jeu rappelconso-v2-gtin-espaces
     https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso-v2-gtin-espaces/exports/csv?delimiter=%3B
     Ne pas prendre le jeu « produits triés par GTIN » : il ne contient pas les produits sans
     code-barres, donc une bonne partie des produits estampillés vendus à la coupe.
  2. Export CSV d'Open Food Facts (~1,5 Go compressé, ne pas décompresser)
     https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz

Installation :
  pip install duckdb pandas

Lancement :
  python test_faisabilite.py --rappels rappelconso.csv \
      --off en.openfoodfacts.org.products.csv.gz --sortie rapport/

Sorties dans le dossier --sortie :
  rapport.json                  les comptages et le verdict
  rappels_relies.csv            les rappels reliés à une autre marque (chemin, usine, produits)
  extensions_30j.csv            les rappels d'une usine suivis d'un rappel d'une autre marque
  colonnes_detectees.txt        les colonnes et catégories retenues, pour vérifier la détection

Règles de comptage :
  - Estampilles françaises uniquement (FR dd.ccc.eee, FR 97d.cc.eee dans les DOM) ;
    les estampilles étrangères sont comptées à part.
  - Un rappel « sans marque » ne peut pas être relié à une « autre » marque : il est compté
    à part et n'entre pas dans le verdict.
  - Open Food Facts décrit le présent. Le compteur « deja_dans_off_le_jour_du_rappel » ne garde
    que les produits qui existaient déjà dans Open Food Facts à la date du rappel.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SEUIL = 200
FENETRE_MIN_J, FENETRE_MAX_J = 1, 30

# Estampille française : FR + code INSEE de la commune (5 caractères) + établissement (3 chiffres).
# Métropole : FR dd.ccc.eee (dd = 2 chiffres, 2A ou 2B). DOM : FR 97d.cc.eee (« fr 974.07.018 ce »).
SEP = r"[\s.,\-_]*"
RE_ESTAMPILLE = re.compile(
    rf"(?<![a-z])FR(?:ANCE)?{SEP}(?:(97\d){SEP}(\d{{2}})|(2A|2B|\d{{2}}){SEP}(\d{{3}})){SEP}(\d{{3}})(?!\d)",
    re.IGNORECASE,
)
# Le même code sans « FR », seul dans le champ (« 28-177-002 ») : accepté dans RappelConso uniquement
RE_ESTAMPILLE_SANS_FR = re.compile(
    r"^\s*(\d{2})[\s.\-](\d{3})[\s.\-](\d{3})\s*(?:CE|UE)?\s*$", re.IGNORECASE
)
RE_ESTAMPILLE_ETRANGERE = re.compile(
    r"(?<![a-z])(AT|BE|BG|CH|CY|CZ|DE|DK|EE|EL|ES|FI|GB|GR|HR|HU|IE|IT|LT|LU|LV|MT|NL|NO|PL|PT|RO|SE|SI|SK|UK)"
    r"[\s.\-_]*[A-Z]{0,4}[\s.\-_]*\d",
    re.IGNORECASE,
)
# Dans identification_produits, chaque produit s'écrit « GTIN$lot$type de date$date$… »
RE_GTIN_IDENTIFICATION = re.compile(r"(?:^|[,|])\s*(\d{8,14})\s*\$")
MARQUES_INCONNUES = {
    "sans",
    "neutre",
    "aucune",
    "nc",
    "na",
    "nonapplicable",
    "inconnue",
    "vrac",
}


# ---------------------------------------------------------------- normalisation


def sans_accents(texte):
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()


def _cle(dom, commune_dom, dept, commune, etab):
    """Clé canonique FR-DD-CCC-EEE (FR-97D-CC-EEE dans les DOM), quel que soit le découpage écrit."""
    code = (dom + commune_dom if dom else dept.upper() + commune) + etab
    if code.startswith("97"):
        return f"FR-{code[:3]}-{code[3:5]}-{code[5:]}"
    return f"FR-{code[:2]}-{code[2:5]}-{code[5:]}"


def cles_usine(texte, sans_fr=False):
    """Estampilles françaises d'un texte. Avec sans_fr, accepte aussi un code seul écrit sans « FR »."""
    if not isinstance(texte, str) or not texte.strip():
        return set()
    cles = {_cle(*g) for g in RE_ESTAMPILLE.findall(texte)}
    if sans_fr:
        for partie in texte.split("|"):
            m = RE_ESTAMPILLE_SANS_FR.match(partie)
            if m:
                cles.add(_cle("", "", *m.groups()))
    return cles


def norm_marque(texte):
    """Marques d'un champ « A, B » → clés sans accents ni ponctuation. « Sans marque » → aucune clé."""
    if not isinstance(texte, str):
        return set()
    out = set()
    for m in re.split(r"[,;/|]", texte):
        m = re.sub(r"[^a-z0-9]", "", sans_accents(m))
        if m and m not in MARQUES_INCONNUES and "sansmarque" not in m:
            out.add(m)
    return out


def meme_marque(a, b):
    """Deux ensembles de marques se recoupent, à l'inclusion près (« carrefour », « carrefourbio »)."""
    return any(x == y or (min(len(x), len(y)) >= 4 and (x in y or y in x)) for x in a for y in b)


def gtin_valide(code):
    """Clé de contrôle GS1 juste, et pas un code interne au magasin : les codes à 12 ou 13 chiffres
    commençant par 2, 02 ou 04 désignent des produits pesés en rayon, pas uniques d'un magasin à l'autre."""
    if not (code.isdigit() and 8 <= len(code) <= 14):
        return False
    g = code.zfill(14)
    somme = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(g[:-1]))
    if (10 - somme % 10) % 10 != int(g[-1]):
        return False
    return len(code) <= 8 or not g[1:].startswith(("2", "02", "04"))


def gtins_rappel(texte):
    """Codes-barres valides d'un champ RappelConso, sans zéros de tête. Dans identification_produits,
    seul le premier champ de chaque produit est un code-barres : les suivants sont le lot et les dates."""
    if not isinstance(texte, str):
        return set()
    if "$" in texte:
        codes = RE_GTIN_IDENTIFICATION.findall(texte)
    else:
        codes = re.findall(r"(?<!\d)\d{8,14}(?!\d)", texte)
    return {c.lstrip("0") for c in codes if gtin_valide(c)}


# ---------------------------------------------------------------- RappelConso


def trouver_colonne(colonnes, inclure, exclure=(), obligatoire=True, nom=""):
    for col in colonnes:
        c = sans_accents(col)
        if all(i in c for i in inclure) and not any(e in c for e in exclure):
            return col
    if obligatoire:
        sys.exit(f"Colonne introuvable pour « {nom} » parmi : {list(colonnes)}")
    return None


def joindre(s):
    return " | ".join(s.dropna().astype(str).unique())


def charger_rappels(chemin):
    df = None
    for sep in (";", ",", "\t"):
        try:
            essai = pd.read_csv(chemin, sep=sep, dtype=str, low_memory=False)
            if essai.shape[1] > 5:
                df = essai
                break
        except (pd.errors.ParserError, UnicodeDecodeError):
            continue
    if df is None:
        sys.exit("Impossible de lire l'export RappelConso (séparateur ; , ou tabulation).")

    cols = {
        "fiche": trouver_colonne(df.columns, ["fiche"], ["lien", "url", "pdf"], False)
        or trouver_colonne(
            df.columns, ["id"], ["guid", "identification"], nom="identifiant de fiche"
        ),
        "estampille": trouver_colonne(df.columns, ["salubrit"], nom="marque de salubrité"),
        "gtin": trouver_colonne(df.columns, ["gtin"], obligatoire=False),
        "identification": trouver_colonne(df.columns, ["identification"], obligatoire=False),
        "marque": trouver_colonne(df.columns, ["marque"], ["salubrit"], nom="marque du produit"),
        "date": trouver_colonne(df.columns, ["publication"], nom="date de publication"),
        "categorie": trouver_colonne(df.columns, ["categorie"], ["sous"], obligatoire=False),
    }

    # Jour calendaire en France : c'est lui qui compte pour « le même jour » et « 1 à 30 jours après »
    df["_date"] = (
        pd.to_datetime(df[cols["date"]], errors="coerce", utc=True)
        .dt.tz_convert("Europe/Paris")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    # Une ligne par fiche dans le jeu « Rappels de produits », une par code-barres dans le jeu
    # trié par GTIN : on regroupe par fiche dans les deux cas
    agg = {"_date": "min"}
    for c in (cols["estampille"], cols["marque"], cols["gtin"], cols["identification"]):
        if c:
            agg[c] = joindre
    if cols["categorie"]:
        agg[cols["categorie"]] = "first"
    fiches = df.groupby(cols["fiche"], dropna=True).agg(agg).reset_index()

    infos = {"colonnes": list(df.columns), "categories": {}}
    if cols["categorie"]:
        cat = fiches[cols["categorie"]].fillna("")
        # « bébés-enfants (hors alimentaire) » contient « aliment » : on l'écarte explicitement
        alim = cat.map(
            lambda c: "aliment" in sans_accents(c) and "hors aliment" not in sans_accents(c)
        )
        for c, n in cat.value_counts().items():
            infos["categories"][c] = (int(n), bool(alim[cat == c].iloc[0]))
        if alim.any():
            fiches = fiches[alim].copy()

    est = fiches[cols["estampille"]].fillna("")
    fiches["usines"] = est.map(lambda t: cles_usine(t, sans_fr=True))
    fiches["usine_ecrite_sans_fr"] = fiches["usines"].map(bool) & ~est.map(
        lambda t: bool(cles_usine(t))
    )
    fiches["estampille_brute"] = est.str.strip() != ""
    fiches["estampille_etrangere"] = ~fiches["usines"].map(bool) & est.map(
        lambda t: bool(RE_ESTAMPILLE_ETRANGERE.search(t))
    )
    fiches["marques"] = fiches[cols["marque"]].map(norm_marque)
    gtins = [set() for _ in range(len(fiches))]
    for c in (cols["gtin"], cols["identification"]):
        if c:
            gtins = [g | gtins_rappel(t) for g, t in zip(gtins, fiches[c], strict=True)]
    fiches["gtins"] = gtins
    return fiches.rename(columns={cols["fiche"]: "fiche", "_date": "date"}), cols, infos


# ---------------------------------------------------------------- Open Food Facts


def charger_off(chemin):
    import duckdb

    con = duckdb.connect()
    source = str(chemin).replace("'", "''")
    # Une seule lecture du fichier compressé : on garde en mémoire les seules colonnes utiles
    con.execute(f"""
        CREATE TABLE off AS
        SELECT code, brands, created_t,
               nullif(trim(coalesce(emb_codes, '') || ' ' || coalesce(emb_codes_tags, '')), '') AS emb,
               coalesce(countries_tags, '') LIKE '%en:france%' AS france
        FROM read_csv('{source}', delim='\t', header=true, quote='', escape='',
                      all_varchar=true, ignore_errors=true, max_line_size=10000000)
    """)
    totaux = con.execute("SELECT count(*), count(*) FILTER (WHERE france) FROM off").fetchone()
    off = con.execute("SELECT * FROM off WHERE emb IS NOT NULL").df()
    off["usines"] = off["emb"].map(cles_usine)
    off["marques"] = off["brands"].map(norm_marque)
    off["code"] = off["code"].fillna("")
    off["gtin"] = off["code"].str.lstrip("0")
    off["gtin_valide"] = off["code"].map(gtin_valide)
    off["cree_le"] = (
        pd.to_datetime(pd.to_numeric(off["created_t"], errors="coerce"), unit="s", utc=True)
        .dt.tz_convert("Europe/Paris")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    return off, {"produits": totaux[0], "produits_france": totaux[1]}


# ---------------------------------------------------------------- comptages


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--rappels", required=True)
    ap.add_argument("--off", required=True)
    ap.add_argument("--sortie", default="rapport")
    a = ap.parse_args()
    out = Path(a.sortie)
    out.mkdir(parents=True, exist_ok=True)

    print("Lecture de RappelConso…")
    fiches, cols, infos = charger_rappels(a.rappels)
    print("Lecture d'Open Food Facts (quelques minutes)…")
    off, totaux_off = charger_off(a.off)

    # Index usine → produits Open Food Facts portant cette estampille
    off_fr = off[off["usines"].map(bool)]
    usine_produits, gtin_usines = {}, {}
    for p in off_fr.itertuples(index=False):
        for u in p.usines:
            usine_produits.setdefault(u, []).append((p.gtin, p.marques, p.cree_le))
        if p.gtin_valide:
            gtin_usines[p.gtin] = (p.usines, p.cree_le)

    # 3. Rappels reliés à un produit d'une autre marque, par les deux chemins
    lignes = []
    for f in fiches.itertuples(index=False):
        # (chemin, usine) → le lien était-il déjà visible dans Open Food Facts le jour du rappel ?
        liens = {("estampille", u): True for u in f.usines}
        for g in f.gtins:
            usines, cree = gtin_usines.get(g, ((), pd.NaT))
            for u in usines:
                liens[("gtin", u)] = liens.get(("gtin", u), False) or cree <= f.date
        for (chemin, u), lien_avant in liens.items():
            autres = [
                (g, cree)
                for g, m, cree in usine_produits.get(u, [])
                if m and not meme_marque(m, f.marques) and g not in f.gtins
            ]
            if autres:
                avant = sum(cree <= f.date for _, cree in autres) if lien_avant else 0
                lignes.append(
                    {
                        "fiche": f.fiche,
                        "date": f.date,
                        "chemin": chemin,
                        "usine": u,
                        "marque_rappel_connue": bool(f.marques),
                        "nb_produits_autres_marques": len(autres),
                        "nb_deja_dans_off_le_jour_du_rappel": int(avant),
                        "exemples_gtin": " ".join(g for g, _ in autres[:5]),
                    }
                )
    relies = pd.DataFrame(
        lignes,
        columns=[
            "fiche",
            "date",
            "chemin",
            "usine",
            "marque_rappel_connue",
            "nb_produits_autres_marques",
            "nb_deja_dans_off_le_jour_du_rappel",
            "exemples_gtin",
        ],
    )
    relies.to_csv(out / "rappels_relies.csv", index=False)
    connue = relies[relies["marque_rappel_connue"].astype(bool)]
    n_relies = connue["fiche"].nunique()

    # 4. Usines servant au moins deux marques
    usines_multi = 0
    for prods in usine_produits.values():
        marques = [m for _, m, _ in prods if m]
        if any(not meme_marque(marques[0], m) for m in marques[1:]):
            usines_multi += 1

    # 5. Cible du modèle : rappel d'une autre marque, même usine, 1 à 30 jours après
    ev = fiches[
        fiches["usines"].map(bool) & fiches["date"].notna() & fiches["marques"].map(bool)
    ].explode("usines")
    ext = []
    for u, grp in ev.groupby("usines"):
        recs = grp.sort_values("date").to_dict("records")
        for i, b in enumerate(recs):
            for a_ in recs[:i]:
                delta = (b["date"] - a_["date"]).days
                if FENETRE_MIN_J <= delta <= FENETRE_MAX_J and not meme_marque(
                    a_["marques"], b["marques"]
                ):
                    ext.append(
                        {
                            "usine": u,
                            "fiche_initiale": a_["fiche"],
                            "fiche_suivante": b["fiche"],
                            "jours": delta,
                        }
                    )
                    break
    ext = pd.DataFrame(ext, columns=["usine", "fiche_initiale", "fiche_suivante", "jours"])
    ext.to_csv(out / "extensions_30j.csv", index=False)

    rapport = {
        "entrees": {
            "rappels": Path(a.rappels).name,
            "off": Path(a.off).name,
            "execution_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "1_fiches_alimentaires": len(fiches),
        "1_fiches_avec_champ_estampille_rempli": int(fiches["estampille_brute"].sum()),
        "1_fiches_avec_estampille_FR_lue": int(fiches["usines"].map(bool).sum()),
        "1_dont_ecrite_sans_FR": int(fiches["usine_ecrite_sans_fr"].sum()),
        "1_fiches_avec_estampille_etrangere": int(fiches["estampille_etrangere"].sum()),
        "1_fiches_avec_code_barres": int(fiches["gtins"].map(bool).sum()),
        "1_fiches_sans_marque_connue": int((~fiches["marques"].map(bool)).sum()),
        "2_produits_off_total": int(totaux_off["produits"]),
        "2_produits_off_france": int(totaux_off["produits_france"]),
        "2_produits_off_avec_estampille_FR": len(off_fr),
        "2_dont_vendus_en_france": int(off_fr["france"].sum()),
        "3_rappels_relies_autre_marque": int(n_relies),
        "3_dont_par_estampille": int(connue[connue["chemin"] == "estampille"]["fiche"].nunique()),
        "3_dont_par_gtin": int(connue[connue["chemin"] == "gtin"]["fiche"].nunique()),
        "3_dont_avec_produit_deja_dans_off_le_jour_du_rappel": int(
            connue[connue["nb_deja_dans_off_le_jour_du_rappel"] > 0]["fiche"].nunique()
        ),
        "3_hors_verdict_rappels_sans_marque_relies": int(
            relies[~relies["marque_rappel_connue"].astype(bool)]["fiche"].nunique()
        ),
        "4_usines_servant_2_marques_ou_plus": int(usines_multi),
        "5_extensions_1_30_jours": int(ext["fiche_suivante"].nunique()),
        "seuil": SEUIL,
        "verdict": "SEUIL ATTEINT"
        if n_relies >= SEUIL
        else "SEUIL NON ATTEINT : basculer sur le plan B",
    }
    (out / "rapport.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    detection = [f"{k}: {v}" for k, v in cols.items()]
    detection += ["", "Colonnes de l'export :"] + [f"  {c}" for c in infos["colonnes"]]
    detection += ["", "Catégories (nombre de fiches) :"] + [
        f"  {'gardée ' if g else 'écartée'} {n:6d}  {c}"
        for c, (n, g) in infos["categories"].items()
    ]
    (out / "colonnes_detectees.txt").write_text("\n".join(detection), encoding="utf-8")

    print("\n=== Rapport de faisabilité ===")
    for k, v in rapport.items():
        print(f"{k:55s} {v}")
    print(f"\nFichiers écrits dans {out.resolve()}")


if __name__ == "__main__":
    main()
