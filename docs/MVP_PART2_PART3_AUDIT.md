# Audit MVP Part.2 / Part.3

Date de l'audit : 2026-08-21
Révision inspectée : `69854334a1e3d63645582be2e0c2146deb80526e`

## Frontière de chantier

Ce chantier est strictement additif dans `fireviewer-ai-worker`.

Hors chantier et non modifiés :

- Part.1 MAP, son builder, ses sources, ses exports et ses profils RunPod ;
- `fireviewer-spatial` ;
- l'intersection rayon/terrain existante ;
- Part.4 PÉRIMÈTRE et `deterministic_perimeter.py` ;
- le backend et ses transitions de publication pendant la stabilisation locale des contrats.

La nouvelle localisation s'arrête à :

```text
candidate clusters
-> camera groups
-> camera pose
-> target pixel
-> ray origin + ray direction + uncertainty
```

## CURRENT ARCHITECTURE

Le worker possède déjà deux familles de contrats :

1. `event-2.0` / `event-result-2.0`, orientés candidat privé, point de vue connu,
   ancrages visuels, tentative spatiale et abstention ;
2. worker `2.0`, orienté lots multi-médias, stages, provenance, modèles, consensus,
   faits, propositions spatiales et rapport privé.

Le backend persiste déjà les preuves privées, construit les bundles `event-2.0`,
revalide `event-result-2.0` et conserve la publication comme action humaine séparée.

Les manques observés pour le nouveau MVP étaient :

- aucun contrat `fireviewer.event-evidence.v1` event-level multi-source ;
- aucun contrat fermé `fireviewer.detection.v1`, `fireviewer.satellite.v1` ou
  `fireviewer.localization.v1` ;
- aucun `candidate_cluster` pondéré et inspectable ;
- aucun comptage explicite par `origin_id` et `media_group_id` ;
- aucun client Panoramax régional dans le runtime ;
- aucune projection perspective 8 vues / 4 vues ;
- aucun adaptateur local MegaLoc ni index FAISS versionné ;
- aucune métrique principale Event Recall@1/3/5 dans le dépôt.

## REUSE

Réutilisé sans dupliquer l'existant :

- `StrictModel`, `SafeIdentifierV2` et `Sha256HexV2` ;
- les validateurs GeoJSON existants ;
- les conventions d'abstention, d'incertitude et de provenance ;
- le runtime local `httpx`, Pillow, NumPy et Torch déjà verrouillé ;
- le principe du backend comme frontière de publication et source durable.

Les nouveaux contrats restent séparés de `event-2.0` jusqu'à stabilisation. Cela
évite une migration simultanée du worker et du backend et permet un adaptateur
explicite ultérieur.

## FILES MODIFIED

- `pyproject.toml` : extra local `localization-mvp` ;
- `uv.lock` : verrouillage de `faiss-cpu==1.15.0`.

## FILES CREATED

- `src/firewarning_worker/mvp/contracts/` : quatre contrats métier et types communs ;
- `src/firewarning_worker/mvp/providers.py` : interfaces provider interchangeables ;
- `src/firewarning_worker/mvp/localization/panoramax.py` : lecture STAC régionale ;
- `src/firewarning_worker/mvp/localization/perspective.py` : crops perspectives ;
- `src/firewarning_worker/mvp/localization/megaloc.py` : encodage local injecté ;
- `src/firewarning_worker/mvp/localization/faiss_index.py` : index cosine versionné ;
- `src/firewarning_worker/mvp/localization/evidence_fusion.py` : fusion V0 ;
- `src/firewarning_worker/mvp/benchmarks/event_localization.py` : métriques event-level ;
- `src/firewarning_worker/mvp/benchmarks/corpus.py` : contrat strict du mini-corpus ;
- `src/firewarning_worker/mvp/benchmarks/ground_truth.py` : lecture bornée des couches
  polygonales `observedEventA` ;
- `src/firewarning_worker/mvp/benchmarks/coverage.py` : reçu de couverture Panoramax
  sans téléchargement de média ;
- `benchmarks/mvp-event-localization/corpus/` : neuf cas France été 2026, avec
  Die/Justin comme premier cas, reçu de préflight réel et 180 médias examinés ;
- `tools/probe_mvp_summer_2026.py` : sonde reproductible Copernicus/Panoramax ;
- `tools/collect_event_media.py` : collecte bornée des médias et pages sources ;
- `tools/build_event_media_inventory.py` : vérification octet/SHA/dimensions,
  déduplication et planches-contact ;
- `tools/apply_event_media_review.py` : gel des décisions de revue visuelle ;
- `tools/build_summer_2026_media_corpus.py` : matérialisation du corpus média ;
- tests `test_mvp_*` correspondants.

## RISKS

1. Le mini-corpus réel contient neuf événements de juin, juillet et août 2026. Le
   gate média est atteint avec 180 fichiers examinés, soit 20 par cas, hachés et
   reliés à leurs pages sources. Le contrôle des droits reste explicitement
   `not_evaluated` et n'est pas présenté comme acquis.
2. Les vérités terrain CEMS de Die/Justin, Trévillach, Fontainebleau, Saumos et
   Biscarrosse sont figées et revérifiées par SHA-256. Boussès, Bénonces/Serrières,
   Bellegarde-en-Diois et Luglon n'ont pas encore de périmètre indépendant.
3. La sonde Panoramax régionale a trouvé des références dans huit AOI sur neuf ;
   Luglon en a zéro et Bellegarde une seule. Aucun JPEG n'a été téléchargé.
4. Aucun snapshot MegaLoc immuable n'a encore été chargé. L'adaptateur interdit le
   téléchargement implicite et exige un loader fourni par l'orchestration.
5. FAISS est validé localement sur un petit index, pas encore sur un corpus régional.
6. Le contrat `event-2.0` exige actuellement un point de vue ; un adaptateur vers
   `EventEvidenceV1` devra préserver la différence entre point de prise de vue et
   localisation de l'événement.
7. Les seuils PASS/PARTIAL/FAIL doivent être approuvés avant le benchmark réel ; le
   code exige qu'ils soient fournis et n'en invente pas.

## DEPENDENCIES

Extra `localization-mvp` :

- `faiss-cpu==1.15.0` ;
- `httpx==0.28.1` ;
- `numpy==2.4.6` ;
- `pillow==12.1.1` ;
- `torch==2.13.0`.

MegaLoc reste identifié par `model_id` et révision immuable dans chaque exécution.
Le modèle n'est ni téléchargé ni ajouté au dépôt.

## IMPLEMENTATION ORDER

1. compléter ou exclure explicitement les quatre cas sans vérité terrain ;
2. matérialiser uniquement les références Panoramax autorisées des huit AOI couvertes ;
3. générer les huit vues perspectives et construire l'index MegaLoc/FAISS régional ;
4. produire les candidats par média puis exécuter la fusion V0 ;
5. mesurer Event Recall@1/3/5, rayon candidat, distance à la vraie zone, taux non
   résolu/revue humaine et métriques image diagnostiques ;
6. rendre un verdict PASS/PARTIAL/FAIL avec analyse d'erreurs ;
7. ne commencer ALIKED/LightGlue, hloc ou PyCOLMAP qu'après réussite suffisante de ce
   gate event-level.

## VALIDATION OBSERVÉE

- suite complète du worker : `395 passed` ;
- tests MVP ciblés : `24 passed` ;
- Ruff sur `src` et `tests` : succès ;
- format des 28 fichiers Python MVP/corpus ciblés : conforme ;
- mypy : aucun problème dans 64 fichiers source ;
- lock uv : 236 paquets résolus, lock cohérent ;
- FAISS : ajout, recherche cosine, sérialisation et restauration validés avec le
  binding natif local ;
- Panoramax : requête STAC régionale réelle, deux références conservées dans un reçu
  métadonnées uniquement, aucun JPEG téléchargé.
- corpus été 2026 : neuf événements réels sur les trois mois, Die/Justin en premier ;
- médias événementiels : 334 candidats uniques vérifiés au niveau octets et
  dimensions, 180 retenus après revue visuelle, exactement 20 par cas ;
- gate média : `pass`, gate droits : `not_evaluated`, verdict qualité du benchmark :
  aucun ;
- Copernicus : cinq couches `observedEventA` téléchargées sous plafond de 64 MiB,
  validées Polygon/MultiPolygon, hachées puis relues sans divergence ;
- Panoramax : neuf AOI sondées avec une limite de 25 références chacune, 176 références
  métadonnées au total, zéro image téléchargée ; huit AOI couvertes, Luglon non couvert.

Ces validations prouvent l'implémentation et ses contrats. Elles ne constituent pas
un résultat de qualité de localisation sur corpus réel et ne déclenchent donc aucun
verdict produit PASS/PARTIAL/FAIL.
