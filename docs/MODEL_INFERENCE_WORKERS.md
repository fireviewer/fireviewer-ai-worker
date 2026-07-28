# Workers d’inférence alignés sur les trainers

Ce document distingue les contrats validés des composants seulement préparés. Un
checkpoint publié ne devient pas automatiquement un modèle de production : le
prétraitement, la précision numérique, la géométrie de sortie et les seuils
doivent reproduire le benchmark.

## État au 28 juillet 2026

| Modèle FireViewer | Rôle | Contrat worker | Branchement orchestrateur |
|---|---|---|---|
| RT-DETRv2-R50 feu/fumée | détection | **implémenté** : letterbox centré 768, poids FP32, autocast BF16, dé-letterbox | **actif** via `RTDETRAdapter` pour un checkpoint local FireViewer |
| D-FINE X-Large feu/fumée | détection/contradicteur | géométrie partagée disponible, mais chargement D-FINE spécifique non intégré | **non actif** |
| MolmoPoint-8B FireViewer | points flamme/front/origine fumée | prompt fermé et parseur normalisé disponibles | **non actif** : le rôle `fire_pointing` n’est pas encore exécuté par `SessionRunner` |
| Prithvi FireViewer | surface brûlée | blocage explicite du checkpoint déprécié | **interdit** : régression HLS confirmée ; modèle officiel conservé comme référence |

## Détecteurs RT-DETR et D-FINE

Le benchmark commun utilise une image carrée 768×768 construite ainsi :

1. conversion RGB ;
2. mise à l’échelle du côté le plus long à 768 avec interpolation linéaire OpenCV ;
3. centrage sur un fond noir ;
4. inférence sur ce canevas ;
5. retrait du padding, remise à l’échelle et clamp dans l’image source.

Les checkpoints FireViewer restent en FP32 en mémoire. L’inférence CUDA utilise
un autocast BF16. Le passage permanent des poids en BF16 ou FP16 n’est pas le
contrat validé.

Le worker générique de la baseline COCO RT-DETR conserve son propre processeur ;
ses objets génériques ne sont jamais renommés en moyens de lutte.

## MolmoPoint

`model_workers/pointing.py` n’accepte que trois sorties :

- `flame_point` ;
- `visible_front_point` ;
- `smoke_origin`, uniquement à l’origine visible sur le terrain.

Chaque point est limité aux coordonnées image normalisées `[0,1]`. Toute
coordonnée géographique, clé supplémentaire, type inconnu ou valeur hors image
est refusé. Une absence de preuve visible produit une liste vide.

Ce fichier ne prouve pas l’intégration au pipeline. Avant activation il reste à :

1. ajouter `fire_pointing` au registre/runtime ;
2. charger le checkpoint FireViewer épinglé ;
3. convertir les points en `ImagePointAnnotation` ;
4. traverser les gates de projection caméra/MNT ;
5. tester l’abstention et le déchargement CUDA.

## Prithvi BurnScars

Le checkpoint `fireviewer/prithvi-burnscars-firewarning-v1-deprecated` est
refusé avant chargement. Sur le lot indépendant HLS, son IoU de 0,789 est
inférieur au 0,864 du modèle officiel ; sa perfection sur EO4 provenait d’un
sous-domaine all-positive et ne constitue pas une preuve de généralisation.

Le contrat d’entrée de référence reste six bandes HLS
`BLUE/GREEN/RED/NIR_NARROW/SWIR_1/SWIR_2`, tuiles 512×512 et sortie binaire
`burned_area`. L’adaptateur TerraTorch du modèle officiel reste à implémenter
avant tout branchement.

## Graphiques et fiches

Les chiffres, empreintes de sélection, limitations et graphiques sont publiés
sur les quatre dépôts modèles de l’organisation FireViewer :

- <https://huggingface.co/fireviewer/rtdetr-v2-r50-fire-smoke>
- <https://huggingface.co/fireviewer/dfine-xlarge-fire-smoke>
- <https://huggingface.co/fireviewer/molmopoint-8b-fire-smoke-pointing>
- <https://huggingface.co/fireviewer/prithvi-burnscars-firewarning-v1-deprecated>
