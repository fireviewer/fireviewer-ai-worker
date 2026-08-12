# FireViewer — checklist des entraînements

Ce fichier suit les contrats et résultats reproductibles sans conserver de
chemin de poste, secret, dataset, modèle, log ou artefact de run dans Git.

## Trains terminés

### DINOv3 ViT-B/16 multi-tâches

- Base immuable : `5931719e67bbdb9737e363e781fb0c67687896bc`.
- Full fine-tuning du backbone et des trois têtes.
- Dataset partagé : 1 940 lignes (`966/555/419`).
- Dataset privé : `fireviewer/dinov3-multitask-fireviewer-v3-dataset`.
- Modèle : `fireviewer/dinov3-vitb16-multitask-fireviewer-v3`.
- Meilleur checkpoint : époque 5, `validation_loss=0.9348679466`.
- Test gelé : IoU `0.6701531572`, point PCK@10 `0.7923627685`.
- Export final `model.safetensors` publié.
- Publication terminée; promotion runtime toujours soumise au benchmark shadow
  et à la revue humaine.

### D-FINE XLarge v2

- Corpus dédupliqué : 170 389 JPEG uniques.
- Résultat : 24 048 pas, validation mAP `0.1361`, test mAP `0.1342`.
- Dépôt : `fireviewer/dfine-xlarge-fire-smoke-v2`.
- Révision : `cc3346d9b89ca4fd22f4b36eb9df0c12d7bb0eea`.

### DINOv3 Cross-View Retrieval v1

- 7 890 paires Gaussians on Fire et Camp Swift.
- Splits : `4 672/900/2 318`; 20 groupes sans fuite.
- Full fine-tuning de l'encodeur partagé et des têtes retrieval/pointage.
- Arrêt anticipé propre après 20 époques; meilleur checkpoint époque 6.
- Test : Recall@1 `0.00388266`, Recall@5 `0.02717860`, rang médian `164`.
- Résultat classé comme échec fonctionnel : le modèle n'est pas promouvable.
- Les deux dépôts de modèles Cross-View en échec ont été supprimés de HF.
- Le dataset reste distinct des modèles et peut être conservé pour une nouvelle
  méthodologie avec masquage des transitoires feu/fumée.

### SegFormer-B2 baseline v1

- Même corpus de segmentation, publié dans un dépôt dédié de 1 940 lignes.
- Arrêt anticipé à l'époque 18; meilleur checkpoint époque 10.
- Test sur 419 images : IoU `0.782232`, Dice `0.877812`, loss `0.528253`.
- Modèle : `fireviewer/segformer-b2-fire-smoke-baseline-v1`.
- Dataset privé : `fireviewer/segformer-b2-fire-smoke-baseline-v1-dataset`.
- Export Transformers autonome publié; fichiers locaux purgés.

### RF-DETR Large ground fire/smoke v2

- Train terminé : 3 époques et 4 142 pas.
- EMA mAP@50 : `0.704784`.
- EMA mAP@50:95 : `0.432440`.
- Checkpoint complet chargeable, sans merge d'adaptateur.
- Modèle : `fireviewer/rf-detr-large-ground-fire-smoke-v2`.
- Export ONNX publié et inventaire distant vérifié.
- Inventaire distant HF confirmé avant tout nettoyage local.

### RF-DETR Small — corpus élite sol low-RAM

- Corpus élite : 5 813 train, 680 validation et 712 test.
- Vues sol uniquement, boîtes contrôlées, quasi-doublons déclarés exclus,
  déduplication perceptuelle et plafond par séquence.
- Train terminé : 12 époques et 2 184 pas d'optimiseur.
- Validation EMA mAP@50:95 : `0.4602849`.
- Test : mAP@50:95 `0.4365011`, mAP@50 `0.6970135`, F1 `0.6718110`.
- Modèle : `fireviewer/rf-detr-small-ground-elite-fire-smoke-v1`.
- Checkpoint complet, export ONNX et inventaire distant publiés.

## Trains en cours

Aucun train n'est actif. Le train DINOv3 v4 reste soumis au lancement explicite
après validation de son smoke contrôlé.

## Corpus en préparation

### DINOv3 multi-tâches v4

- Réservoir final : 42 715 lignes (`32 404/5 057/5 254`) et zéro fuite de
  groupe entre les splits.
- Sources intégrées : Camp Swift, FireSentry, RxCADRE, FireViewer/Boreal,
  FIReStereo FiresGL, FIgLib et Pyro-SDIS.
- Vue d'entraînement générée par échantillonnage pondéré : positifs `48 %`,
  négatifs `28 %`, abstentions `24 %`, Pyro-SDIS ciblé à `33 %` pour rester
  dans la plage effective de `30–35 %`.
- Taille d'époque : 8 192 tirages avec remplacement depuis le réservoir complet.
- Validation et test conservent leur distribution naturelle de benchmark.
- Préflight : 126 427 artefacts vérifiés, aucune erreur de train.
- Initialisation : export complet du DINOv3 v3 validé.
- Smoke CUDA : quatre mises à jour, pertes et 266 tenseurs de gradients finis,
  pic VRAM `4 015 602 176` octets.
- Métriques globales, par source, par rôle et baselines triviales intégrées.
- Dataset privé préparé localement; publication et train complet non lancés.

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
- [ ] Préflight sans erreur et révisions de sources enregistrées.
- [ ] Tests unitaires ciblés réussis.
- [ ] Smoke avec perte et gradients finis.
- [ ] Splits isolés par événement ou groupe géographique.
- [ ] PID, logs, métriques et checkpoints écrits uniquement sous un répertoire
      ignoré ou dans un stockage externe.
- [ ] Sélection du checkpoint uniquement sur la validation.
- [ ] Test final gelé, publication HF dédiée, puis revue humaine.
- [ ] Export final sans état d'optimiseur confirmé chargeable localement.
- [ ] Aucune suppression locale avant confirmation de l'inventaire HF distant.

Les commandes reproductibles et variables locales attendues sont décrites dans
`training/TRAIN_COMMANDS.md`.
