# FireViewer — checklist des entraînements

Ce fichier suit les contrats et résultats reproductibles sans conserver de
chemin de poste, secret, dataset, modèle, log ou artefact de run dans Git.

## Trains terminés

### DINOv3 ViT-B/16 multi-tâches

- Base immuable : `5931719e67bbdb9737e363e781fb0c67687896bc`.
- Full fine-tuning du backbone et des trois têtes.
- Dataset adapté : 1 417 lignes (`655/453/309`).
- Manifest SHA-256 :
  `aa8e20742c55654d822068bdca49e89e668fc2f20aa7be8b452cd01ca096e48f`.
- Meilleur checkpoint : époque 15, `validation_loss=0.2116717139`.
- Publication terminée; promotion runtime toujours soumise au benchmark shadow
  et à la revue humaine.

### RF-DETR Large

- Corpus gelé : 170 409 images, deux classes.
- Profil : 3 époques, batch 4, accumulation 16, résolution 512.
- Résultat : 5 385 pas en 8 h 46, meilleur EMA mAP `0.4429`.
- Checkpoint final vérifié hors Git.

### D-FINE XLarge v2

- Corpus dédupliqué : 170 389 JPEG uniques.
- Résultat : 24 048 pas, validation mAP `0.1361`, test mAP `0.1342`.
- Modèle SHA-256 :
  `7efdcd9fc02c7006d06974a7aa13c03171f5ec7414eb80cbb0193eca860c6329`.
- Dépôt : `fireviewer/dfine-xlarge-fire-smoke-v2`.
- Révision : `cc3346d9b89ca4fd22f4b36eb9df0c12d7bb0eea`.

## Trains prêts mais non lancés

### DINOv3 Cross-View Retrieval v1

- 390 paires UAV/orthophoto réelles.
- Splits : `288/57/45`.
- 14 groupes géographiques, aucune fuite de groupe ou d'asset.
- 684 images et poids DINOv3 vérifiés par SHA-256.
- Encodeur partagé entièrement entraînable.
- Perte contrastive multi-positive et tête de pointage dans le crop.
- Smoke CUDA batch 4 : pertes et gradients finis.
- Sélection : Recall@1 validation, puis erreur de pointage.
- Test lu uniquement après sélection du meilleur checkpoint.
- Promotion bloquée par le benchmark géographique indépendant, le benchmark
  RoMa/PyCOLMAP et le test de masquage feu/fumée transitoire.

## Runs interrompus

### RF-DETR Small

- Profil court demandé : 3 époques, batch 4, accumulation 8.
- Run arrêté à la demande pendant l'époque 1, au pas 2049.
- Aucun checkpoint complet écrit.
- Run non reprenable et non publiable; les artefacts partiels restent hors Git.
- Un éventuel nouveau run doit repartir du poids Small vérifié.

## Corpus auxiliaires et blocages

### THU-Wildfire Ninuo

- 389 instants RGB/thermique sur 3 h 40 et 125 masques.
- Baseline maximale entre centroïdes : `0.0205040646 m` à environ 450 m.
- Corpus temporel/cross-modal, pas multivue.
- Quarantaine obligatoire : licence non matérialisée et un seul événement.

### Prithvi BurnScars

- Corpus multispectral matérialisé.
- Train bloqué par l'absence d'un test géographique indépendant.

### MoGe-2 ViT-B

- Benchmark auxiliaire uniquement.
- Bloqué par l'absence de vérité profondeur/FOV/intrinsics.

### OCR, VLM et périmètre déterministe

- PP-OCRv6 Small et Ministral 3 sont des intégrations runtime, pas des trains.
- Le périmètre déterministe est un moteur de règles avec abstention et revue
  humaine obligatoire, pas un modèle à entraîner.

## Gate avant tout nouveau train

- [ ] Dataset et poids absents de l'index Git.
- [ ] Aucun chemin absolu ou identifiant personnel dans les fichiers suivis.
- [ ] Aucun secret dans les commandes, rapports ou variables enregistrées.
- [ ] Préflight sans erreur et hashes immuables vérifiés.
- [ ] Tests unitaires ciblés réussis.
- [ ] Smoke avec perte et gradients finis.
- [ ] Splits isolés par événement ou groupe géographique.
- [ ] PID, logs, métriques et checkpoints écrits uniquement sous un répertoire
      ignoré ou dans un stockage externe.
- [ ] Sélection du checkpoint uniquement sur la validation.
- [ ] Test final gelé, publication HF dédiée, puis revue humaine.

Les commandes reproductibles et variables locales attendues sont décrites dans
`training/TRAIN_COMMANDS.md`.
