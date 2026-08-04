# Recalage spatial dans le worker

## Frontière

Le worker spatial propose une géométrie privée ou une abstention. Il ne publie rien et ne modifie pas le package de la zone.

## Entrées

- média et artefacts ;
- ancrage visuel ;
- profil de vue ;
- révision du package spatial ;
- MNT/MNS ;
- orthophoto ou banque de rendus ;
- modèle de caméra ou intrinsics candidats.

## Photos au sol

```text
retrieval local
→ filtres EXIF / horizon / FOV / relief
→ RoMa v2 photo-rendu
→ points 2D-3D
→ PyCOLMAP
→ contrôles
→ raycast MNT
→ uncertainty_envelope
```

## UAV

AerialExtreMatch-RoMa reste baseline. RoMa v2, AdHoP/OrthoLoC et les autres challengers sont évalués sur les mêmes lots.

## Masques dynamiques

Les correspondances sur :

- ciel ;
- feu ;
- fumée ;
- personnes ;
- véhicules ;
- aéronefs ;
- autres objets mobiles ;

sont exclues avant la pose.

## Statuts

### Visuels

- `insufficient_visual_anchor`
- `ambiguous_anchor`
- `no_visible_ground_origin`

### Géométriques

- `insufficient_geometry`
- `unstable_camera_pose`
- `invalid_raycast`
- `uncertainty_above_limit`

## Incertitude

La covariance locale de pose ne suffit pas. La sortie agrège aussi les incertitudes du pointage, des intrinsics, des correspondances et du terrain.

Le terme `uncertainty_envelope` est utilisé tant que la couverture probabiliste n’est pas calibrée.
