"""Parsing de scripts/test_faisabilite.py, sur des valeurs tirées des exports RappelConso et
Open Food Facts du 20 novembre 2026 (sauf mention contraire)."""

import pytest
from test_faisabilite import (
    cles_usine,
    gtin_valide,
    gtins_rappel,
    meme_marque,
    norm_marque,
)

# ---------------------------------------------------------------- estampilles


@pytest.mark.parametrize(
    "texte",
    [
        "FR 71.158.001 CE",  # variantes de CLAUDE.md §4
        "fr-71-158-001-ce",
        "FR71158001",
        "fr 71 158 001 ce",
        "FR 71.158.001 EC",  # suffixe utilisé par Open Food Facts
    ],
)
def test_exemple_de_reference(texte):
    assert cles_usine(texte) == {"FR-71-158-001"}


@pytest.mark.parametrize(
    "texte, cle",
    [
        ("fr 68 294 003 ce", "FR-68-294-003"),
        ("fr.25.056.058.ce", "FR-25-056-058"),
        ("fr 74-211-060 ce", "FR-74-211-060"),
        ("fr 29,026,502 ue", "FR-29-026-502"),
        ("france 34-108 534 ce", "FR-34-108-534"),
        ("fr23.117.001ce/ue", "FR-23-117-001"),  # Chavegrand, fiche U du 9 août 2025
        ("fr2b.120.020 ce", "FR-2B-120-020"),
        ("fr 2b033 025 ce", "FR-2B-033-025"),
        ("fr-2b-318-003-ce", "FR-2B-318-003"),
        ("FR 85.215.001 EC", "FR-85-215-001"),  # Open Food Facts, emb_codes
        ("fr-85-215-001-ec", "FR-85-215-001"),  # Open Food Facts, emb_codes_tags
    ],
)
def test_estampilles_reelles(texte, cle):
    assert cles_usine(texte) == {cle}


@pytest.mark.parametrize(
    "texte",
    [
        "fr 974.07.018 ce",
        "fr 974-07-018 ce",
        "fr 974 07 018 ce",
        "FR 97.407.018",  # découpage métropolitain d'un code DOM (construit) : même clé
    ],
)
def test_dom(texte):
    assert cles_usine(texte) == {"FR-974-07-018"}


def test_plusieurs_estampilles_dans_un_champ():
    texte = "FR 23.004.023 EC,EMB 23004D | fr 71.158.001 ce"
    assert cles_usine(texte) == {"FR-23-004-023", "FR-71-158-001"}


def test_forme_sans_fr_seulement_si_demandee():
    assert cles_usine("28-177-002") == set()
    assert cles_usine("28-177-002", sans_fr=True) == {"FR-28-177-002"}
    assert cles_usine("09.289.001ce", sans_fr=True) == {"FR-09-289-001"}


@pytest.mark.parametrize(
    "texte",
    [
        "fr 42 165 0006 ue",  # 4 chiffres d'établissement : non lu, plutôt que tronqué
        "fr 12.264.04 ue",
        "fr-412-008 ce",
        "pl 04.621.801 we",  # estampille polonaise de même forme
        "it 05 97 ec",
        "EMB 71158",  # code emballeur, pas une estampille
        "estampille sanitaire",
    ],
)
def test_rejets(texte):
    assert cles_usine(texte, sans_fr=True) == set()


# ---------------------------------------------------------------- codes-barres


def test_gtin_premier_champ_seulement():
    # Les lots « 18070324 » et « 3013018233 » ont la longueur d'un code-barres
    assert gtins_rappel("3389190104482$18070324$date limite de consommation$2024-05-08$") == {
        "3389190104482"
    }
    assert gtins_rappel(
        "3266980029647$3013018233$date limite de consommation$2023-08-21$,"
        "3266980029647$3013018233$date limite de consommation$2023-08-22$"
    ) == {"3266980029647"}
    assert gtins_rappel("$1528$date de durabilité minimale$2025-11-30$") == set()


def test_gtin_colonne_seule():
    # Colonne gtin du jeu « trié par GTIN » (lue en entier, zéro de tête perdu)
    assert gtins_rappel("3474930202006") == {"3474930202006"}


def test_codes_internes_magasin_ecartes():
    # Fiche 2021-04-0217 : produits pesés, codes non uniques d'un magasin à l'autre
    assert not gtin_valide("2421006000000")
    assert not gtin_valide("0202222000000")
    assert gtins_rappel("2421006000000$lot n°109$date limite de consommation$2021-05-19$") == set()


def test_cle_de_controle():
    assert gtin_valide("3038680075022")  # Open Food Facts, Delpierre
    assert not gtin_valide("3038680075023")
    assert gtin_valide("20016579")  # code à 8 chiffres (Lidl) : gardé


# ---------------------------------------------------------------- marques


def test_marques_inconnues():
    assert norm_marque("sans marque") == set()
    assert norm_marque("Sans Marque") == set()
    assert norm_marque("neutre") == set()
    assert norm_marque("/") == set()


def test_marques():
    assert norm_marque("u") == {"u"}  # Système U : une seule lettre, à garder
    assert norm_marque("Danette, Danone") == {"danette", "danone"}
    assert norm_marque("chêne d'argent") == {"chenedargent"}


def test_meme_marque():
    assert meme_marque(norm_marque("carrefour"), norm_marque("Carrefour Bio"))
    assert meme_marque(norm_marque("Danette, Danone"), norm_marque("danone"))
    # « u » est inclus dans « auchan », mais trop court pour que l'inclusion compte
    assert not meme_marque(norm_marque("u"), norm_marque("auchan"))
    assert not meme_marque(norm_marque("le gaulois"), norm_marque("corico"))
