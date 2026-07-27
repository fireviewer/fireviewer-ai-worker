# Réparations de contrats à appliquer aux ZIP publics

Cette note décrit uniquement les modifications de métadonnées à appliquer lors d'une future
reconstruction. Aucun ZIP public ne doit être téléchargé ou réenvoyé pour cette étape.

Le registre de référence est `train-bundles-v1.json`. Tant qu'un artefact porte
`embedded_contract_status: rebuild_required`, son `TRAIN_BUNDLE.json` embarqué ne doit pas être
exécuté. Le validateur `validate_mvp_training_contracts.py --bundle ... --train-id ...` doit
réussir avant tout lancement.

## `fire-pointing-lora-v1.zip`

- supprimer les commandes `training.spatial_train_qwen` ;
- fixer `allenai/MolmoPoint-8B` comme modèle de pointing principal ;
- conserver `microsoft/Florence-2-large-ft` comme baseline ;
- conserver `Qwen/Qwen3.5-9B` comme vérificateur uniquement, sans autorité pour produire une
  coordonnée ;
- laisser l'entrypoint MolmoPoint non exécutable jusqu'à l'implémentation du trainer et à la
  disponibilité du lot pixel double-validé ;
- intégrer `contract_revision: mvp-a40-v2` et le `model_contract` de
  `specs/fire-pointing-lora-v1.json`.

## `cross-view-localization-v1.zip`

- supprimer l'entrypoint du prototype `DINOv2 coarse cross-view` ;
- fixer ConGeo comme modèle principal et PLGeo comme challenger ;
- conserver les deux entrypoints non exécutables tant que leurs trainers dédiés et le test
  géographique double-validé ne sont pas disponibles ;
- intégrer `contract_revision: mvp-a40-v2` et le `model_contract` de
  `specs/cross-view-localization-v1.json`.

## `burned-area-segmentation-v1.zip` — réparé

Le ZIP public a été remplacé par le corpus HLS/EO4 matérialisé et vérifié. Son contrat embarqué
`mvp-a40-v2` appelle désormais le préflight et le trainer
`training.train_prithvi_burnscars`, fixe `Prithvi-EO-2.0-300M-BurnScars` comme modèle principal
et conserve `TerraMind-base-Fire` comme benchmark. Le dataset est matérialisé, mais le trainer
refuse désormais le lancement tant que le rapport du test géographique indépendant n'est pas
présent et validé. Après entraînement, la promotion exige encore l'évaluation indépendante du
modèle produit.

## Nouveau bundle `dfine-fire-smoke-v1.zip`

Ce ZIP n'existe pas encore dans le dépôt public. Lorsqu'il sera construit, il devra réunir :

- FASDD, Pyro-SDIS et Alarmod depuis `media-filter-fire-smoke-v1.zip` ;
- Boreal Forest Fire Detection depuis `wildfire-smoke-detection-v1.zip`, converti du format YOLO
  source vers le manifeste FireWarning ;
- le trainer D-FINE épinglé ;
- une sélection de benchmark immuable partagée par D-FINE, Pyronear et RT-DETR ;
- `contract_revision: mvp-a40-v2` et le `model_contract` de
  `specs/dfine-fire-smoke-v1.json`.

La reconstruction ne devra pas inclure de dataset critique, d'incident Référence opérationnelle A ou Référence opérationnelle B, de
checkpoint privé ou de secret.
