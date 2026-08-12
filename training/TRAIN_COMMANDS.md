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
| RF-DETR Large | Train terminé et modèle publié sur HF |
| RF-DETR Small | Train élite sol terminé; modèle, checkpoint et ONNX publiés |
| D-FINE XLarge v2 | Train, validation, test et publication HF terminés |
| DINOv3 ViT-B/16 multi-tâches | Train, test, modèle et dataset privé publiés; fichiers locaux purgés |
| DINOv3 multi-tâches v4 | Réservoir prêt, sampler équilibré, préflight et smoke CUDA validés; train complet non lancé |
| DINOv3 Cross-View Retrieval v1 | Échec fonctionnel confirmé; dépôts de modèles supprimés |
| SegFormer-B2 baseline | Train, test, modèle et dataset privé publiés; fichiers locaux purgés |
| RT-DETRv2 | Modèle historique conservé; aucun nouveau train prévu |
| THU-Wildfire Ninuo | Corpus temporel en quarantaine; pas un corpus multivue |
| Prithvi BurnScars | Bloqué par le test géographique indépendant |
| MoGe-2 ViT-B | Benchmark auxiliaire; vérité profondeur/FOV manquante |

## RF-DETR Small — corpus élite sol, profil low-RAM

Le corpus élite conserve 5 813 images d'entraînement après contrôle des
annotations, exclusion des quasi-doublons déclarés, déduplication perceptuelle
par séquence et plafonnement à deux vues par séquence au train. Le train réalise
12 époques, soit environ 2 184 pas d'optimiseur avec un batch effectif de 32.
Le profil conserve 6 workers mais désactive leur persistance, limite le
préchargement à 1 et désactive la mémoire épinglée. Cible : 35 à 55 minutes.

```powershell
& $env:FIREVIEWER_RFDETR_PYTHON -m training.train_rfdetr_large preflight `
  --variant small `
  --dataset-profile ground-elite `
  --dataset-root $env:FIREVIEWER_DETECTION_DATASET_ROOT `
  --rf-home $env:RF_HOME `
  --output '.\data\training\rfdetr-small-ground-elite-lowram-v1' `
  --epochs 12 --batch-size 8 --grad-accum-steps 4 --num-workers 6 `
  --learning-rate 1e-4 --encoder-learning-rate 1e-5 `
  --resolution 512 --seed 420

& $env:FIREVIEWER_RFDETR_PYTHON -m training.train_rfdetr_large plan `
  --variant small `
  --dataset-profile ground-elite `
  --dataset-root $env:FIREVIEWER_DETECTION_DATASET_ROOT `
  --rf-home $env:RF_HOME `
  --output '.\data\training\rfdetr-small-ground-elite-lowram-v1' `
  --epochs 12 --batch-size 8 --grad-accum-steps 4 --num-workers 6 `
  --learning-rate 1e-4 --encoder-learning-rate 1e-5 `
  --resolution 512 --seed 420

& '.\tools\start_rfdetr_small_train.ps1'
& '.\tools\monitor_rfdetr_small.ps1'
```

Le run court interrompu ne possède aucun checkpoint et n'est pas repris. Le run
final est reparti du poids RF-DETR Small vérifié sur le corpus élite et a
terminé ses 12 époques. Le bloc ci-dessus reste la commande de reproduction.

## RF-DETR Large — entraîné et publié

Le run sol a terminé 3 époques et 4 142 pas. Le checkpoint complet sélectionné
atteint un EMA mAP@50 de `0.704784` et un EMA mAP@50:95 de `0.432440`.

Publication vérifiée :
`fireviewer/rf-detr-large-ground-fire-smoke-v2`.

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

Publications :

- modèle : `fireviewer/dinov3-vitb16-multitask-fireviewer-v3` ;
- dataset privé : `fireviewer/dinov3-multitask-fireviewer-v3-dataset`.

## DINOv3 multi-tâches v4 — corpus et smoke prêts

Le réservoir complet contient 42 715 lignes, réparties en 32 404 lignes de
train, 5 057 de validation et 5 254 de test, sans fuite de groupe. Il conserve
les sept sources : Camp Swift, FireSentry, RxCADRE, FireViewer/Boreal,
FIReStereo FiresGL, FIgLib et Pyro-SDIS.

La vue d'entraînement est générée à chaque époque par un sampler pondéré avec
remplacement. Elle vise 48 % de positifs, 28 % de négatifs et 24 %
d'abstentions, avec Pyro-SDIS ciblé à 33 % afin de rester dans la plage
effective de 30–35 %. La
validation et le test utilisent la distribution naturelle du réservoir. Les
poids par qualité sont appliqués aux pertes, et les rapports incluent les
métriques par source, par rôle et les baselines triviales.

Le modèle v4 est initialisé depuis l'export complet du v3 validé, pas depuis le
backbone générique. Télécharger une seule fois cette révision immuable :

```powershell
hf download 'fireviewer/dinov3-vitb16-multitask-fireviewer-v3' `
  'model.safetensors' 'backbone_config.json' `
  --revision 'e4e89776cb623ffdab56f072c1744489464c5635' `
  --local-dir '.\data\models\dinov3-multitask-fireviewer-v3-initializer'
```

Préflight reproductible :

```powershell
$dinoV4Common = @(
  '--pointing-root', '.\data\campaigns\dinov3-multitask-fireviewer-v4\metadata\merged',
  '--multitask-manifest', '.\data\campaigns\dinov3-multitask-fireviewer-v4\metadata\merged\manifest.jsonl',
  '--data-root', '.\data\campaigns\dinov3-multitask-fireviewer-v4',
  '--model-id', 'facebook/dinov3-vitb16-pretrain-lvd1689m',
  '--model-revision', '5931719e67bbdb9737e363e781fb0c67687896bc',
  '--initial-safetensors', '.\data\models\dinov3-multitask-fireviewer-v3-initializer\model.safetensors',
  '--backbone-config', '.\data\models\dinov3-multitask-fireviewer-v3-initializer\backbone_config.json',
  '--output', '.\data\training\dinov3-multitask-fireviewer-v4',
  '--balanced-sampling',
  '--positive-share', '0.48',
  '--negative-share', '0.28',
  '--abstention-share', '0.24',
  '--pyro-max-share', '0.33',
  '--samples-per-epoch', '8192',
  '--image-size', '448'
)

python -m training.train_dinov3_multitask preflight @dinoV4Common
```

Smoke CUDA contrôlé, exécuté avant tout train complet :

```powershell
python -m training.train_dinov3_multitask smoke @dinoV4Common `
  --batch-size 2 --num-workers 2 --smoke-steps 4
```

Le smoke validé a exécuté quatre mises à jour avec pertes et gradients finis et
un pic VRAM de 4 015 602 176 octets. Le train complet suivant est préparé mais
ne doit être lancé qu'explicitement :

```powershell
python -m training.train_dinov3_multitask train @dinoV4Common `
  --epochs 12 --batch-size 4 --gradient-accumulation-steps 8 `
  --num-workers 6 --early-stopping-patience 3 --learning-rate 1e-5
```

Le staging du dataset privé est prêt sous forme de liens physiques. Sa
publication dans `fireviewer/dinov3-multitask-fireviewer-v4-dataset` doit avoir
lieu après les gates, puis être vérifiée avant tout nettoyage local.

## DINOv3 Cross-View Retrieval v1

Le corpus publié contient 7 890 paires (`train=4 672`, `validation=900`,
`test=2 318`) et 20 groupes sans fuite. Il combine Gaussians on Fire et des
caméras indépendantes synchronisées de Camp Swift. Wildfire3Data n'est pas
inclus faute d'archive publique téléchargeable lors de la préparation.

```powershell
python -m training.train_dinov3_cross_view preflight
python -m training.train_dinov3_cross_view plan `
  --epochs 40 --batch-size 4 --gradient-accumulation-steps 8
python -m training.train_dinov3_cross_view smoke `
  --batch-size 4 --gradient-accumulation-steps 8
& '.\tools\start_dinov3_cross_view_train.ps1'
& '.\tools\monitor_dinov3_cross_view.ps1'
```

Révision de base : `5931719e67bbdb9737e363e781fb0c67687896bc`.
Le smoke CUDA a validé 89 606 147 paramètres tous entraînables et des pertes
et gradients finis. Le train s'est arrêté proprement à 20 époques. Le test
gelé donne Recall@1 `0.00388266`, Recall@5 `0.02717860`, rang médian `164` et
erreur de point médiane normalisée `0.10156049`.

Le résultat est un échec fonctionnel et ne doit pas être promu. Les dépôts de
modèles Cross-View en échec ont été supprimés. Le dataset est conservé comme
matière première pour une future méthodologie distincte.

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
Révision distante : `cc3346d9b89ca4fd22f4b36eb9df0c12d7bb0eea`.

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
