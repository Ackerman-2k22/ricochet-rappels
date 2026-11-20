# Ricochet — rappels alimentaires

Quand une usine est citée dans un rappel alimentaire, quels autres produits faut-il surveiller ?

Pour chaque rappel publié sur [RappelConso](https://rappel.conso.gouv.fr/), on retrouve les produits
**d'autres marques** fabriqués dans **la même usine**, grâce à l'estampille sanitaire
(`FR 71.158.001 CE`). Ces produits forment une liste « à surveiller ».

Un produit de cette liste **n'est pas rappelé** : il sort de la même usine qu'un produit rappelé, rien de plus.
Seule la fiche officielle RappelConso fait foi.

> Projet en cours. Les listes ne sont pas encore publiées.

## Données

| Source | Usage | Licence |
|---|---|---|
| RappelConso V2 (DGCCRF, DGAL) | rappels, marques, estampilles, codes-barres | Licence Ouverte 2.0 |
| Open Food Facts | produits, marques, estampilles (`emb_codes`) | ODbL 1.0 |

Voir [DATA_LICENSE.md](DATA_LICENSE.md). Aucune donnée personnelle n'est collectée.

## Automatisations (GitHub Actions)

| Workflow | Quand | Ce qu'il fait |
|---|---|---|
| `collect_rappels.yml` | toutes les heures (minute 17) | ajoute les fiches RappelConso nouvelles ou modifiées dans `data/bronze/rappels/` |
| `snapshot_off.yml` | chaque lundi | publie un instantané réduit d'Open Food Facts en Parquet dans les Releases |
| `faisabilite.yml` | à la demande | lance `scripts/test_faisabilite.py` sur les exports du jour |
| `ci.yml` | à chaque push et PR | ruff et pytest |

## Travailler en local

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate ailleurs)
pip install -e ".[dev]"
pytest
```

Test de faisabilité sur les vrais exports (téléchargés à la main, voir l'en-tête du script) :

```bash
python scripts/test_faisabilite.py --rappels rappelconso.csv --off off.csv.gz --sortie rapport/
```
