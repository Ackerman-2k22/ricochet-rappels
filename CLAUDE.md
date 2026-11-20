# CLAUDE.md — Projet Rappels alimentaires

Ce fichier sert de mémoire à Claude Code pour ce dépôt. Lis-le en entier avant toute tâche.
Quand une décision change, mets ce fichier à jour dans le même commit.

## 1. Le projet en une phrase

Quand une usine est rappelée, quels autres produits faut-il surveiller ?
Pour chaque rappel alimentaire publié en France, on retrouve les produits **d'autres marques**
fabriqués dans **la même usine** (même estampille sanitaire). On les classe dans une liste « à surveiller ».

- Thème : sécurité alimentaire et rappels de produits.
- Cadre : projet Data de groupe en alternance. Il doit couvrir tout le cycle : collecte → stockage → traitement → modélisation → restitution.
- Équipe : Rowane (Data Engineer · BI), Franck (AI Engineer · MLOps), Annie (génie logiciel · management des SI).
- Échéance : présentation la semaine du 8 mars 2027.
- Sujet retenu le 17 novembre 2026. Plan B si le test de faisabilité échoue : qualité de l'eau du robinet (PFAS).

### Ce qui existe déjà, et ce qui manque
- Des applications (Raptoo, VérifConso…) répondent à « ce code-barres est-il rappelé ? ».
- Aucun outil ouvert, à notre connaissance, ne relie **les marques entre elles par l'usine**. C'est notre apport. Ne pas reconstruire un simple « vérificateur de code-barres ».

### Exemple de référence (à utiliser dans les tests et démos)
Le 1er octobre 2026, cinq marques de filets de poulet ont été rappelées le même jour pour suspicion de salmonelle.
Elles portaient toutes l'estampille `FR 71.158.001 CE`.

## 2. Règles non négociables

1. **Wording** : un produit est « à surveiller », **jamais** « dangereux », « contaminé » ni « rappelé » s'il ne l'est pas officiellement. Cette règle vaut partout : UI, README, noms de colonnes exposées, messages de commit visibles.
2. **Pas de données personnelles.** On travaille sur des produits et des usines, pas sur des personnes. Ne jamais ajouter de source qui en contient.
3. **Pas de fuite temporelle.** À la date d'un rappel, le modèle ne voit que ce qui était connu ce jour-là (voir §6).
4. **Pas de chiffre inventé.** Toute valeur affichée (ROI, volume, taux) vient d'une mesure du pipeline ou d'une source citée.
5. **Licences respectées** (voir §3). Les données dérivées d'Open Food Facts restent publiques, sous ODbL.
6. **0 € de budget.** Aucun service payant. Aucun serveur permanent.

## 3. Sources de données

| Source | Contenu utile | Accès | Licence |
|---|---|---|---|
| RappelConso V2 (DGCCRF, DGAL) | date de publication, marque, catégorie, motif, GTIN (depuis nov. 2024), marque de salubrité (estampille) | export CSV ~26 Mo sur data.gouv.fr, API Opendatasoft sur data.economie.gouv.fr (jeu `rappelconso-v2-gtin-espaces`) | Licence Ouverte 2.0 |
| Open Food Facts | code (GTIN), brands, emb_codes, emb_codes_tags, categories, countries, created_t, last_modified_t | `https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz` (1,54 Go gz au 19/11/2026, taille décompressée non mesurée, export quotidien) | ODbL (base), CC-BY-SA (images) |
| Établissements agréés (DGAL) | numéro d'agrément, raison sociale, commune, activité | listes publiées par le ministère de l'Agriculture | **à vérifier** avant toute republication |

Points d'attention :
- **Ne jamais décompresser l'export OFF sur disque.** DuckDB le lit directement en `.csv.gz` avec `delim='\t', quote='', all_varchar=true, ignore_errors=true`.
- Alternative à évaluer : l'export Parquet d'Open Food Facts publié sur Hugging Face. Il est plus léger à lire. Garder celui qui donne les mêmes comptages pour moins de temps.
- Open Food Facts décrit **le présent**. Pour le backtest, il faut des **instantanés hebdomadaires** datés (voir §5).
- RappelConso V2, vérifié le 20/11/2026 sur l'API (`https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/<id>`, réponses gzippées : `curl --compressed`) :
  - Jeu à utiliser : `rappelconso-v2-gtin-espaces`, une ligne par fiche (19 284 fiches, `numero_fiche` unique). **Pas** `rappelconso-v2-gtin-trie` : une ligne par GTIN, et les produits sans code-barres en sont absents (souvent les produits estampillés vendus à la coupe).
  - Colonnes utiles : `numero_fiche`, `date_publication` (ISO 8601 avec fuseau), `categorie_produit`, `marque_produit`, `marque_salubrite`, `identification_produits`, `motif_rappel`. L'export CSV commence par un BOM.
  - Le jeu complet n'a **pas** de colonne `gtin`. Les GTIN sont dans `identification_produits` : `GTIN$lot$type de date$date$…`, produits séparés par des virgules. Seul le premier champ est un GTIN ; les lots font souvent 8 à 10 chiffres.
  - Catégorie : filtrer sur `alimentation`. Un simple « contient aliment » garde aussi « bébés-enfants (hors alimentaire) ».
  - `marque_produit` vaut « sans marque » (ou « sans », « neutre »…) dans plus de 1 700 fiches alimentaires.
  - Le script de faisabilité détecte quand même les colonnes par motif et écrit ce qu'il a trouvé dans `colonnes_detectees.txt`.

## 4. Clé de jointure : l'estampille sanitaire

Format français : `FR dd.ccc.eee CE`, soit département (2 chiffres, `2A`/`2B` ou `97x`), commune (3 chiffres) et établissement (3 chiffres).
Une même usine s'écrit de plusieurs façons : `FR 71.158.001 CE`, `fr-71-158-001-ce`, `FR71158001`, `71.158.001`…

- Clé canonique : `FR-DD-CCC-EEE` (exemple : `FR-71-158-001`). Dans les DOM, le département a 3 chiffres et la commune 2 : `fr 974.07.018 ce` → `FR-974-07-018`. Les 8 caractères forment toujours code INSEE de la commune + établissement ; la clé est calculée à partir d'eux, quel que soit le découpage écrit.
- Regex de référence (dans `test_faisabilite.py`, insensible à la casse) : `FR` ou `FRANCE`, puis `97d` + 2 chiffres (DOM) ou `dd`/`2A`/`2B` + 3 chiffres, puis 3 chiffres non suivis d'un chiffre. Séparateurs acceptés : espace, `.`, `,`, `-`, `_`. Elle lit 4 483 des 6 001 champs remplis (fiches alimentaires, 20/11/2026).
- Forme sans `FR` (`28-177-002`, 365 fiches) : acceptée **seulement** dans `marque_salubrite` de RappelConso, et seulement si le code est seul dans le champ, sinon `pl 04.621.801` serait lu comme français. Comptée à part.
- Non lus, volontairement : établissement sur 2 ou 4 chiffres (`fr 12.264.04`, `fr 42 165 0006`), ordre inversé (`ce 22.389.003 fr`), codes emballeur `EMB 71158`.
- GTIN : clé de contrôle GS1 vérifiée. Les codes à 12-13 chiffres commençant par `2`, `02` ou `04` (produits pesés en rayon) ne servent pas de clé de jointure : ils ne sont pas uniques d'un magasin à l'autre.
- Les estampilles étrangères (`ES`, `DE`, `IT`…) sont hors périmètre de la V1. Elles sont comptées à part, pas jetées.
- Deux chemins pour relier un rappel à une usine :
  1. **estampille** lue dans la fiche RappelConso ;
  2. **GTIN** de la fiche → produit Open Food Facts → ses `emb_codes`.
  Toujours garder une colonne `chemin` (`estampille` | `gtin`) pour mesurer chaque chemin séparément.
- Splink sert à l'appariement flou (marques mal orthographiées, produits sans code). Il ne remplace pas la clé d'estampille quand elle existe.
- Hors périmètre : un fournisseur d'ingrédient commun à plusieurs usines (cas Danone et lait infantile). On relie par **l'usine de fabrication** uniquement.

## 5. Architecture et environnement

Contrainte : 3 portables personnels, pas de serveur, 0 €. Deux modes d'exécution :

### En continu : GitHub Actions (dépôt **public**)
- `collect_rappels.yml` : toutes les heures, à la **minute 17** (`17 * * * *`) pour éviter la congestion du début d'heure. Il lance `src/rappels/collect/rappelconso.py` (bibliothèque standard seule) :
  - Il relit les fiches publiées sur 30 jours glissants, ou depuis 2 jours avant la dernière collecte si le workflow a été interrompu plus longtemps. Cela rattrape aussi les fiches modifiées.
  - Il écrit seulement les couples `(numero_fiche, numero_version)` absents, dans `data/bronze/rappels/date=YYYY-MM-DD/rappels_YYYYMMDDTHHMMSSZ.jsonl.gz`. La date est celle de la **collecte** (UTC) et chaque fiche porte `_collecte_utc`.
  - Le premier lancement récupère tout l'historique (19 284 fiches, 5,8 Mo compressé au 20/11/2026). Le JSONL non compressé ferait 47 Mo, d'où le gzip.
  - Les fichiers sont commités dans le dépôt. Ensuite, c'est très petit : 5 à 6 rappels par jour.
- `snapshot_off.yml` : chaque lundi (`23 4 * * 1`). Il lance `src/rappels/collect/off_snapshot.py` : DuckDB lit l'export OFF en streaming, garde **toutes les lignes** mais **uniquement les colonnes utiles**, et écrit un Parquet zstd.
  - Le fichier est daté par l'en-tête `Last-Modified` de l'export (`off_YYYY-MM-DD.parquet`, Release `off-YYYY-MM-DD`). Il est publié comme **asset de GitHub Release** (limite 2 Go par fichier).
  - Mesure du 20/11/2026 : 4 922 927 produits, 144 Mo, 35 s sur un portable.
  - Si l'asset existe déjà, le workflow ne fait rien. Il ne commite jamais de gros fichier dans le dépôt (limite 100 Mo par fichier, historique git qui gonfle).
- `faisabilite.yml` : déclenchement manuel (`workflow_dispatch`). Il lance `scripts/test_faisabilite.py` sur les vrais exports et publie `rapport/` en artefact.
- `ci.yml` : à chaque push sur `main` et à chaque PR, il lance `ruff check`, `ruff format --check` et `pytest` (Python 3.11, la version minimale).

Pièges GitHub Actions à respecter :
- Intervalle minimal de 5 min ; les exécutions planifiées peuvent être retardées ou sautées.
- Les workflows planifiés ne tournent **que depuis la branche par défaut**.
- Sur un dépôt public, les workflows planifiés sont **désactivés après 60 jours sans activité** du dépôt. Le commit horaire des rappels maintient l'activité. Ne pas le supprimer.
- Runner Linux standard (dépôt public) : 4 vCPU, 16 Go de RAM, ~14 Go de SSD. Le snapshot OFF doit tenir dedans : streaming, pas de décompression.
- Chaque workflow doit être **idempotent** : relancé deux fois, il ne crée pas de doublon. Dédupliquer sur `(numero_fiche, numero_version)`, pour garder aussi les modifications de fiche.
- Pas de secret nécessaire : toutes les sources sont publiques. Ne jamais commiter de jeton.

### À la demande : nos portables
- `docker compose up` lance Airflow (orchestration des traitements batch), MLflow (suivi des essais) et Streamlit (restitution).
- Les données lourdes sont téléchargées depuis les Releases dans `data/` (gitignoré, sauf `data/bronze/rappels/`).
- Prévoir un mode « léger » qui tourne sur un portable de 8 Go de RAM : DuckDB avec `memory_limit`, et un échantillon d'Open Food Facts pour le développement.

### Couches médaillon
| Couche | Contenu | Outils |
|---|---|---|
| Bronze | fichiers bruts horodatés, jamais modifiés | Parquet, Delta Lake (historique des instantanés OFF, time travel) |
| Silver | estampilles normalisées, produits dédupliqués, appariement flou, tests de qualité | dbt-duckdb, Splink ; Spark **uniquement** pour normaliser l'historique OFF |
| Gold | graphe usines ↔ produits ↔ marques ↔ rappels, features, listes « à surveiller » | DuckDB |
| Restitution | appli de recherche par produit/usine, tableau de bord | Streamlit (front unique) |

### Outils écartés : ne pas les réintroduire sans décision d'équipe
- **MinIO** : la version communautaire n'est plus distribuée ni maintenue depuis fin 2025, et son dépôt est archivé.
- **PostgreSQL** : DuckDB suffit pour la couche gold.
- **Kafka** : 5 à 6 rappels par jour ne justifient pas de streaming.
- **Neo4j** : le graphe tient en tables DuckDB.
- **Great Expectations** : les tests dbt suffisent.

**Spark** reste soumis à un banc d'essai face à DuckDB sur la même tâche. Le résultat du banc d'essai (temps, mémoire) va dans `docs/benchmark_spark_duckdb.md`, et on garde Spark seulement s'il gagne ou s'il est exigé par la grille.

## 6. Modèle et protocole d'évaluation

- **Cible** : quand une usine est citée dans un rappel à la date T, un produit d'une **autre marque** issu de cette usine sera-t-il rappelé entre T+1 et T+30 jours ?
- **Exclusions** : les rappels publiés **le même jour pour le même incident** ne comptent pas comme positifs, car les prédire ne vaut rien.
- **Modèles, dans cet ordre** : régression logistique, puis CatBoost. SHAP pour expliquer chaque alerte en une phrase.
- **Motifs de rappel** : classés par règles (listeria, salmonelle, E. coli, corps étranger, allergène non déclaré, etc.). Un LLM ne traite **que le résidu** non classé, et son résultat est stocké pour ne pas être recalculé.
- **Features** : uniquement à partir des données connues à T. On utilise l'instantané OFF **le plus récent antérieur à T**, jamais l'export du jour.
- **Backtest** : chronologique, en fenêtre glissante, sans mélange aléatoire.
- **Références à battre** :
  1. toute l'usine sans tri ;
  2. un produit tiré au hasard dans l'usine.
- **Métriques** : précision sur les 10 premiers (precision@10) et jours d'avance (date du rappel réel − date de l'alerte).
- **Juge vivant** : de décembre 2026 à mars 2027, les listes publiées **avant** chaque nouveau rappel sont horodatées et figées (commit ou Release). Ce sont elles qu'on évalue en mars.
- Le protocole est écrit dans `docs/protocole.md` **avant** de regarder les résultats. Tout écart au protocole est noté dans ce fichier, daté.
- Tout essai est tracé dans MLflow : paramètres, métriques, version des données (date d'instantané).

## 7. Valeur et cas d'usage

- Formule : valeur ≈ rappels annoncés × jours d'avance × coût d'un jour d'exposition.
- Le backtest mesure les deux premiers termes. Le coût d'un jour d'exposition sera chiffré avec un professionnel de la qualité : **ne pas l'inventer**.
- Utilisateurs : un foyer (scan d'un produit), une cuisine collective (cantine, Ehpad, hôpital), un responsable qualité (usines de ses fournisseurs), la presse et les associations (carte des usines qui concentrent les rappels).
- Cas réel cité : Chavegrand, été 2025 : une estampille (`FR 23.117.001`), plusieurs marques, des produits en vente jusqu'au 9 août, 21 cas de listériose dont 2 décès. On ne prétend pas que l'outil les aurait évités.

## 8. Décision du 27 novembre 2026

- `test_faisabilite.py` tourne sur les vrais exports.
- **Seuil** : au moins **200 rappels** reliés à un produit d'une autre marque issu de la même usine → on continue. Sinon → plan B.
- Ce seuil mesure la **faisabilité** (assez d'exemples pour entraîner et valider), **pas** le volume Big Data.
- Plausibilité : en 2023, viande, lait et poisson faisaient 1 161 rappels sur 2 023. Il suffirait qu'environ 4 % des rappels estampillés soient reliés.
- Sorties attendues dans `rapport/` : `rapport.json` (comptages et verdict), `rappels_relies.csv`, `extensions_30j.csv`, `colonnes_detectees.txt`.
- Règle de comptage proposée le 20/11/2026, **à valider en équipe** : un rappel « sans marque » (2 009 fiches) ne peut pas être relié à une « autre » marque. Il est compté à part (`3_hors_verdict_…`) et n'entre pas dans le verdict.
- Premier lancement sur les vrais exports le 20/11/2026, en local (RappelConso du 20/11, OFF du 19/11), en 49 s. C'est une **mesure, pas encore la décision** :
  - 14 107 fiches alimentaires, dont 4 848 avec une estampille FR lue et 9 150 avec un code-barres valide.
  - **3 368** rappels reliés à un produit d'une autre marque : 3 157 par l'estampille et 1 097 par le GTIN (une fiche peut passer par les deux chemins). Pour 3 343 d'entre eux, le produit existait déjà dans OFF le jour du rappel.
  - 1 004 extensions entre 1 et 30 jours, 1 663 usines servant au moins 2 marques.
- Limites vues en contrôlant un échantillon à la main :
  - Des fautes de frappe créent de fausses « autres marques » (`etal du volailler` / `L'état du Volaillier`, `saveurs des mauges` / `Saveur Des Mauges`). C'est le rôle de Splink.
  - OFF ne connaît beaucoup d'estampilles que par `emb_codes_tags` (129 254 produits sans `emb_codes`). Il faut lire les deux champs.

## 9. Planning

| Période | Bloc | Livrable |
|---|---|---|
| sept. → 17 nov. 2026 | Exploration | sujet choisi, état de l'art, cadrage |
| 18 → 27 nov. | Test et décision | dépôt public, collecte automatique, comptages, décision |
| 7 → 18 déc. | Pipeline | bronze, silver, appariement, qualité |
| 4 → 22 janv. 2027 | Modèle | gold, modèle, backtest |
| 8 → 19 févr. | Restitution | appli, tableau de bord, gouvernance |
| sem. du 8 mars | Présentation | résultats face au juge vivant |

Entre les blocs (périodes en entreprise), seuls les workflows GitHub Actions tournent. **Chaque semaine d'instantané OFF manquée est perdue** : surveiller les échecs du workflow hebdomadaire.

## 10. Structure du dépôt (cible)

```
.
├── CLAUDE.md
├── README.md                  # présentation publique, wording « à surveiller »
├── LICENSE                    # code ; données dérivées OFF sous ODbL (voir DATA_LICENSE.md)
├── DATA_LICENSE.md
├── .github/workflows/
│   ├── collect_rappels.yml
│   ├── snapshot_off.yml
│   ├── faisabilite.yml
│   └── ci.yml
├── docker-compose.yml         # airflow, mlflow, streamlit
├── pyproject.toml
├── src/rappels/
│   ├── collect/               # clients RappelConso, OFF, DGAL
│   ├── estampille.py          # parsing et normalisation (une seule implémentation)
│   ├── matching/              # Splink
│   ├── features/
│   ├── models/
│   └── app/                   # Streamlit
├── dbt/                       # modèles silver et gold (dbt-duckdb)
├── dags/                      # Airflow
├── scripts/test_faisabilite.py
├── tests/
├── docs/
│   ├── protocole.md
│   ├── benchmark_spark_duckdb.md
│   └── decisions.md           # journal des décisions, daté
└── data/                      # gitignoré sauf data/bronze/rappels/
```

## 11. Conventions de code

- Python 3.11+, gestion des dépendances dans `pyproject.toml`. Format avec `ruff format`, lint avec `ruff check` (configuration dans `pyproject.toml`).
- On travaille dans un venv `.venv` à la racine (gitignoré) : `python -m venv .venv`, puis `pip install -e ".[dev]"`. pytest trouve `src/` et `scripts/` grâce à `pythonpath` dans `pyproject.toml`.
- `scripts/test_faisabilite.py` contient encore sa propre normalisation d'estampille. Elle doit être déplacée dans `src/rappels/estampille.py` avant d'écrire la couche silver.
- **Une seule fonction de normalisation d'estampille** (`src/rappels/estampille.py`), réutilisée partout (script, dbt via UDF ou macro, Splink). Testée avec les variantes de §4.
- Tests avec `pytest`. Tout parsing (estampille, GTIN, dates) a des tests unitaires avec de vrais exemples tirés des données.
- Données : Parquet partout, dates en ISO 8601 et en UTC. Les colonnes sont en `snake_case` français ou anglais, mais cohérentes au sein d'une table.
- Le code et les commentaires sont en français ou en anglais, au choix de chaque module, sans mélanger dans un même fichier. La doc utilisateur est en français.
- Aucun chemin absolu, aucun secret, aucun fichier > 50 Mo dans git.
- Les commits sont petits et descriptifs. Les branches de travail sont fusionnées par PR vers `main`, puisque les workflows planifiés ne tournent que sur `main`.

## 12. Questions ouvertes

- [ ] Licence des listes DGAL : peut-on les republier ?
- [x] Identifiant exact du jeu de données de l'API RappelConso V2 : `rappelconso-v2-gtin-espaces` (voir §3).
- [ ] Pagination de l'API RappelConso V2 pour la collecte horaire (curseur sur `date_publication` ?).
- [x] Taille réelle du Parquet hebdomadaire OFF une fois les colonnes réduites : 144 Mo (export du 19/11/2026).
- [ ] Licence du code (fichier `LICENSE` absent pour l'instant).
- [ ] Grille d'évaluation de l'école : outils imposés (Spark ? cloud ?) ?
- [ ] RAM et OS de chaque portable, pour calibrer le mode léger.
- [ ] Entretien avec un professionnel de la qualité, pour chiffrer le coût d'un jour d'exposition.
