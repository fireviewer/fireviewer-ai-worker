# FireViewer — commandes d'entraînement

Ce document ne contient aucun chemin de poste, token ou emplacement privé.
Les datasets, caches, modèles, logs et sorties de run restent hors de Git.

## Variables locales requises

Définir ces variables dans le terminal sans les enregistrer dans le dépôt :

```powershell
$env:FIREVIEWER_RFDETR_PYTHON = '<RF-DETR_VENV_PYTHON>'
$env:FIREVIEWER_DETECTION_DATASET_ROOT = '<DETECTION_DATASET_ROOT>'
$env:FIREVIEWER_POINTING_DATASET_ROOT = '<POINTING_DATASET_ROOT>'
$env:FIREVIEWER_CROSS_VIEW_BUNDLE_ROOT = '<CROSS_VIEW_BUNDLE_ROOT>'
$env:RF_HOME = '<RF_DETR_WEIGHTS_ROOT>'
$env:HF_TOKEN = '<INJECTED_BY_SECRET_MANAGER>'
Set-Location '<FIREVIEWER_AI_WORKER_REPOSITORY>'
```

Les exemples utilisent `python` lorsque l'environnement courant contient déjà
les dépendances du worker.

## État vérifié

| Cible | État |
|---|---|
| RF-DETR Large | Train 3 époques terminé et checkpoint vérifié |
| RF-DETR Small | Run court arrêté à la demande au pas 2049 de l'époque 1; aucun checkpoint |
| D-FINE XLarge v2 | Train, validation, test et publication HF terminés |
| DINOv3 ViT-B/16 multi-tâches | Train terminé; meilleur checkpoint époque 15 |
| DINOv3 Cross-View Retrieval v1 | Préflight intégral et smoke CUDA verts; train long non lancé |
| RT-DETRv2 | Modèle historique conservé; aucun nouveau train prévu |
| THU-Wildfire Ninuo | Corpus temporel en quarantaine; pas un corpus multivue |
| Prithvi BurnScars | Bloqué par le test géographique indépendant |
| MoGe-2 ViT-B | Benchmark auxiliaire; vérité profondeur/FOV manquante |

## RF-DETR Small — profil court

Le profil FireViewer force trois époques. Il n'utilise pas le défaut amont de
240 époques.

```powershell
& $env:FIREVIEWER_RFDETR_PYTHON -m training.train_rfdetr_large preflight `
  --variant small `
  --dataset-root $env:FIREVIEWER_DETECTION_DATASET_ROOT `
  --rf-home $env:RF_HOME `
  --output '.\data\training\rfdetr-small-fire-smoke-v1' `
  --epochs 3 --batch-size 4 --grad-accum-steps 8 `
  --learning-rate 1e-4 --encoder-learning-rate 1e-5 `
  --resolution 512 --seed 420

& $env:FIREVIEWER_RFDETR_PYTHON -m training.train_rfdetr_large plan `
  --variant small `
  --dataset-root $env:FIREVIEWER_DETECTION_DATASET_ROOT `
  --rf-home $env:RF_HOME `
  --output '.\data\training\rfdetr-small-fire-smoke-v1' `
  --epochs 3 --batch-size 4 --grad-accum-steps 8 `
  --learning-rate 1e-4 --encoder-learning-rate 1e-5 `
  --resolution 512 --seed 420

& '.\tools\start_rfdetr_small_train.ps1'
```

Le run interrompu ne possède aucun checkpoint et ne peut pas être repris. Un
nouveau lancement repartirait du poids RF-DETR Small vérifié.

## RF-DETR Large — profil validé

```powershell
& $env:FIREVIEWER_RFDETR_PYTHON -m training.train_rfdetr_large preflight `
  --variant large `
  --dataset-root $env:FIREVIEWER_DETECTION_DATASET_ROOT `
  --rf-home $env:RF_HOME `
  --output '.\data\training\rfdetr-large-fire-smoke-v2' `
  --epochs 3 --batch-size 4 --grad-accum-steps 16 `
  --learning-rate 1e-4 --encoder-learning-rate 1e-5 `
  --resolution 512 --seed 420
```

Résultat conservé hors Git : 3 époques, 5 385 pas, meilleur EMA mAP `0.4429`.

## DINOv3 multi-tâches — reproduction

Révision immuable :
`facebook/dinov3-vitb16-pretrain-lvd1689m@5931719e67bbdb9737e363e781fb0c67687896bc`.

```powershell
python -m training.train_dinov3_multitask preflight `
  --pointing-root $env:FIREVIEWER_POINTING_DATASET_ROOT `
  --multitask-manifest '.\data\training\dinov3-boreal-multitask-v1\manifest.jsonl' `
  --data-root '.\data\training\wildfire-smoke-segmentation-v1' `
  --model-id '.\data\models\dinov3-vitb16-pretrain-lvd1689m' `
  --model-revision '5931719e67bbdb9737e363e781fb0c67687896bc' `
  --output '.\data\training\dinov3-multitask-v1'
```

Le modèle est entraîné en full fine-tuning. Le checkpoint est complet : aucun
merge PEFT ou LoRA n'est nécessaire.

## DINOv3 Cross-View Retrieval v1

Le corpus contient 390 paires réelles (`train=288`, `validation=57`,
`test=45`) et 14 groupes spatiaux sans fuite. JustZoomIn est exclu du train
principal car ses étapes changent le zoom, pas le point de vue.

```powershell
python -m training.train_dinov3_cross_view preflight --verify-file-hashes
python -m training.train_dinov3_cross_view plan `
  --epochs 40 --batch-size 4 --gradient-accumulation-steps 8
python -m training.train_dinov3_cross_view smoke `
  --batch-size 4 --gradient-accumulation-steps 8
& '.\tools\start_dinov3_cross_view_train.ps1'
& '.\tools\monitor_dinov3_cross_view.ps1'
```

Révision de base : `5931719e67bbdb9737e363e781fb0c67687896bc`.
SHA-256 du manifest :
`532d3b545242a08f76322a8ef9edbb8ee554b53d0935087f9babb2cce0ab2965`.
Le smoke CUDA a validé 89 606 147 paramètres tous entraînables et des pertes
et gradients finis.

## THU-Wildfire Ninuo — quarantaine

```powershell
python -m training.thu_wildfire_ninuo_setup prepare `
  --source-root '<THU_NINUO_EXTRACTED_ROOT>' `
  --output '.\data\training\thu-wildfire-ninuo-v1'
```

Le préflight reste volontairement fermé : licence absente du payload, un seul
événement et baseline caméra maximale insuffisante. Ninuo sert à l'évaluation
temporelle/cross-modale, jamais comme preuve multivue.

## D-FINE XLarge v2 — publication vérifiée

Le run complet est publié dans `fireviewer/dfine-xlarge-fire-smoke-v2`.
Révision vérifiée : `cc3346d9b89ca4fd22f4b36eb9df0c12d7bb0eea`.
SHA-256 du modèle :
`7efdcd9fc02c7006d06974a7aa13c03171f5ec7414eb80cbb0193eca860c6329`.

## Publication d'un modèle final

Le token doit être injecté par le gestionnaire de secrets et ne doit jamais
être écrit dans une commande conservée, un rapport ou un commit.

```powershell
hf repo create '<HF_ORG>/<MODEL_REPOSITORY>' --repo-type model --exist-ok
hf upload '<HF_ORG>/<MODEL_REPOSITORY>' '<HF_EXPORT_DIRECTORY>' . `
  --repo-type model --commit-message 'Publish validated FireViewer model'
```

La création du dépôt et le push ne valent pas promotion production. Le
benchmark gelé et la revue humaine restent obligatoires.
