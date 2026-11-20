"""
Instantané Open Food Facts : colonnes utiles seulement, en Parquet (couche bronze).

DuckDB lit l'export CSV compressé en flux : le fichier n'est jamais décompressé sur disque.
Toutes les lignes sont gardées : une semaine d'instantané manquée ne se rattrape pas.
"""

import argparse
import json
from pathlib import Path

import duckdb

COLONNES = [
    "code",
    "product_name",
    "brands",
    "emb_codes",
    "emb_codes_tags",
    "categories_tags",
    "countries_tags",
]


def instantane(source, sortie, memoire=None):
    con = duckdb.connect()
    if memoire:
        con.execute(f"SET memory_limit = '{memoire}'")
    src = str(source).replace("'", "''")
    dst = str(sortie).replace("'", "''")
    con.execute(f"""
        COPY (
            SELECT {", ".join(COLONNES)},
                   TRY_CAST(created_t AS BIGINT) AS created_t,
                   TRY_CAST(last_modified_t AS BIGINT) AS last_modified_t
            FROM read_csv('{src}', delim='\t', header=true, quote='', escape='',
                          all_varchar=true, ignore_errors=true, max_line_size=10000000)
        ) TO '{dst}' (FORMAT parquet, COMPRESSION zstd)
    """)
    produits, avec_estampille = con.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE coalesce(emb_codes, emb_codes_tags) IS NOT NULL)
        FROM '{dst}'
    """).fetchone()
    return {
        "produits": produits,
        "produits_avec_emb_codes": avec_estampille,
        "taille_octets": Path(sortie).stat().st_size,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True, help="en.openfoodfacts.org.products.csv.gz")
    ap.add_argument("--sortie", required=True, help="off_AAAA-MM-JJ.parquet")
    ap.add_argument("--memoire", help="limite DuckDB, par exemple 4GB (mode léger)")
    a = ap.parse_args()
    print(json.dumps(instantane(a.source, a.sortie, a.memoire)))


if __name__ == "__main__":
    main()
