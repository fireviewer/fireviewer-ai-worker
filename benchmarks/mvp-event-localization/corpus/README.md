# Mini-corpus de localisation — France, été 2026

Ce lot couvre neuf incendies de juin, juillet et août 2026. Il est réservé au
benchmark Part.3 et n'alimente aucun builder ou rendu Part.1.

| Mois | Événement | Médias examinés | Vérité terrain | Panoramax (sonde 25 max.) |
| --- | --- | ---: | --- | ---: |
| Juin | Die / massif du Justin (24 juin) | 20 | CEMS EMSR890, vérifiée | 25 |
| Juin | Boussès (23 juin) | 20 | à identifier | 25 |
| Juin | Bénonces / Serrières-de-Briord (23 juin) | 20 | à identifier | 25 |
| Juillet | Trévillach (4 juillet) | 20 | CEMS EMSR889, vérifiée | 25 |
| Juillet | Fontainebleau (12 juillet) | 20 | CEMS EMSR894, vérifiée | 25 |
| Juillet | Saumos (22 juillet) | 20 | CEMS EMSR899, vérifiée | 25 |
| Juillet | Biscarrosse (23 juillet) | 20 | CEMS EMSR902, vérifiée | 25 |
| Août | Bellegarde-en-Diois / massif du Claps (3 août) | 20 | à identifier | 1 |
| Août | Luglon (14 août) | 20 | à identifier | 0 |

## État du gate

Le corpus est `coverage_profiled`, pas `benchmark_ready` :

- les cinq couches CEMS sont résumées depuis leurs octets exacts et vérifiées par
  SHA-256 ;
- la sonde Panoramax est limitée aux AOI et ne télécharge aucune image ;
- 180 médias sont sélectionnés après revue visuelle, soit exactement 20 par cas ;
- chaque fichier sélectionné possède son URL source, son chemin local, ses dimensions
  et son SHA-256 ;
- le gate média est `pass` ; le contrôle des droits est volontairement
  `not_evaluated` et reste distinct du gate technique ;
- quatre événements n'ont pas encore de vérité terrain polygonale indépendante ;
- Luglon n'a aucune référence Panoramax dans l'AOI et Bellegarde une seule.

En conséquence, aucun résultat `PASS`, `PARTIAL` ou `FAIL` n'est émis.

Artifacts :

- `france-summer-2026-candidates.v1.json` : manifeste strict et provenance ;
- `france-summer-2026-media-ready.v1.json` : corpus enrichi des 180 médias examinés ;
- `france-summer-2026-preflight-20260821.json` : reçu réel Copernicus/Panoramax ;
- `event-media-inventory-20260821.json` : inventaire dédupliqué et vérifié ;
- `event-media-reviewed-selection-20260821.json` : sélection visuelle figée à 20/cas ;
- `event-media-review-decisions.v1.json` : décisions de revue reproductibles ;
- `tools/probe_mvp_summer_2026.py` : sonde reproductible, métadonnées seulement.
