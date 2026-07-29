# Workers d’inférence alignés sur les trainers

Ce document distingue les contrats validés des composants seulement préparés. Un
checkpoint publié ne devient pas automatiquement un modèle de production : le
prétraitement, la précision numérique, la géométrie de sortie et les seuils
doivent reproduire le benchmark.

## État au 28 juillet 2026

| Modèle FireViewer | Rôle | Contrat worker | Branchement orchestrateur |
|---|---|---|---|
| D-FINE X-Large feu/fumée | détection principale | **implémenté** : checkpoint public épinglé, letterbox centré 768, poids FP32, autocast BF16, dé-letterbox | **actif**, candidat de rang 1 |
| RT-DETRv2-R50 feu/fumée | contre-détection | **implémenté** avec le même contrat géométrique et numérique | **actif**, candidat de rang 2 ; sa sortie est conservée même lorsque D-FINE est retenu |
| MolmoPoint-8B FireViewer | points flamme/front/origine fumée | **implémenté** : API native de jetons de point, métadonnées du processeur et coordonnées normalisées | **actif pour les lots V2** entre la sélection visuelle et la projection caméra/MNT |
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

Les deux détecteurs FireViewer sont exécutés séquentiellement sur les mêmes
preuves. D-FINE produit la proposition principale. RT-DETR produit une
contre-analyse persistée. Une divergence au-dessus du seuil de consensus appelle
l’arbitre Qwen3-14B sur les sorties structurées ; s’il manque la preuve visuelle
nécessaire pour trancher, le résultat reste privé et requiert une revue humaine.
Aucun consensus de détection n’est accepté si l’un des deux détecteurs échoue.
Aucun objet générique n’est renommé en moyen de lutte.

## MolmoPoint

Le runtime V2 interroge séparément le modèle pour trois sorties :

- `flame_point` ;
- `visible_front_point` ;
- `smoke_origin`, uniquement à l’origine visible sur le terrain.

Le checkpoint `fireviewer/molmopoint-8b-fire-smoke-pointing` est épinglé par
révision. Le worker suit l’API native MolmoPoint : il conserve les métadonnées
du processeur, contraint la génération par le `logits_processor` du modèle,
retire les jetons d’entrée avant décodage puis transforme les points pixels en
coordonnées image normalisées `[0,1]`.

Ces points ne sont jamais des coordonnées géographiques. Ils traversent ensuite
la projection caméra/rayon/MNT existante. Sans pose fiable, le worker s’abstient
et Florence reste la doublure visuelle par élément. Les propositions projetées
utilisent les types V2 `active_fire_point` et `smoke_origin_point`, puis
réutilisent la revue spatiale admin existante après persistance.

`model_workers/pointing.py` ne sert plus qu’à lire d’anciens exports JSON hors
ligne ; il n’est pas le chemin d’inférence du runtime V2.

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
