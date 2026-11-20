"""Collecte RappelConso : idempotence, versions, reprise après interruption. Sans appel réseau."""

import gzip
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from rappels.collect import rappelconso

# Fiches réelles réduites à quelques champs (référence FR 71.158.001, 1er octobre 2026)
FICHE_A = {"numero_fiche": "2026-10-0001", "numero_version": 1, "marque_produit": "corico"}
FICHE_B = {"numero_fiche": "2026-10-0002", "numero_version": 1, "marque_produit": "le gaulois"}
LUNDI = datetime(2026, 11, 23, 10, 17, tzinfo=UTC)


@pytest.fixture
def api(monkeypatch):
    """Remplace l'API : renvoie api.fiches et note la date « depuis » demandée."""

    faux = SimpleNamespace(fiches=[], depuis=[])

    def telecharger(depuis=None):
        faux.depuis.append(depuis)
        return list(faux.fiches)

    monkeypatch.setattr(rappelconso, "telecharger", telecharger)
    return faux


def lire(dossier):
    lignes = []
    for f in sorted(dossier.glob("date=*/*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as g:
            lignes += [json.loads(ligne) for ligne in g]
    return lignes


def test_premier_lancement_recupere_tout(tmp_path, api):
    api.fiches = [FICHE_A, FICHE_B]
    sortie, n = rappelconso.collecter(tmp_path, maintenant=LUNDI)
    assert n == 2
    assert api.depuis == [None]
    assert (
        sortie.relative_to(tmp_path).as_posix()
        == "date=2026-11-23/rappels_20261123T101700Z.jsonl.gz"
    )
    assert all(f["_collecte_utc"] == "2026-11-23T10:17:00+00:00" for f in lire(tmp_path))


def test_relance_n_ecrit_rien(tmp_path, api):
    api.fiches = [FICHE_A, FICHE_B]
    rappelconso.collecter(tmp_path, maintenant=LUNDI)
    sortie, n = rappelconso.collecter(tmp_path, maintenant=LUNDI.replace(hour=11))
    assert (sortie, n) == (None, 0)
    assert len(lire(tmp_path)) == 2


def test_nouvelle_version_ecrite(tmp_path, api):
    api.fiches = [FICHE_A]
    rappelconso.collecter(tmp_path, maintenant=LUNDI)
    api.fiches = [FICHE_A, {**FICHE_A, "numero_version": 2}]
    _, n = rappelconso.collecter(tmp_path, maintenant=LUNDI.replace(hour=11))
    assert n == 1
    assert [f["numero_version"] for f in lire(tmp_path)] == [1, 2]


def test_fenetre_glissante(tmp_path, api):
    api.fiches = [FICHE_A]
    rappelconso.collecter(tmp_path, maintenant=LUNDI)
    rappelconso.collecter(tmp_path, maintenant=LUNDI.replace(hour=11))
    assert api.depuis[-1] == date(2026, 10, 24)  # 30 jours avant


def test_reprise_apres_longue_interruption(tmp_path, api):
    api.fiches = [FICHE_A]
    rappelconso.collecter(tmp_path, maintenant=datetime(2026, 9, 1, tzinfo=UTC))
    rappelconso.collecter(tmp_path, maintenant=LUNDI)
    assert api.depuis[-1] == date(2026, 8, 30)  # 2 jours avant la dernière collecte
