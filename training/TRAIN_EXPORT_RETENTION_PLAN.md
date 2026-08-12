# FireViewer — cycle d'entraînement, publication et rétention

## Objectif

Exécuter un seul entraînement lourd à la fois et garantir qu'un dataset ou un
modèle validé est récupérable depuis Hugging Face avant de supprimer sa copie
locale. Le cycle doit empêcher l'accumulation simultanée de sources, de corpus
matérialisés, d'archives monolithiques et de checkpoints intermédiaires.

## Invariants

1. Un seul `train_id` peut être dans l'état `TRAINING`.
2. Un dépôt de modèle correspond à un seul entraînement.
3. Un dépôt de dataset correspond à un seul entraînement. Il peut réutiliser les
   mêmes sources par référence et empreinte, mais ne mélange jamais plusieurs
   objectifs d'entraînement.
4. Le dataset est publié et vérifié avant le lancement du train long.
5. Le modèle final est testé localement, publié, puis son inventaire distant est
   confirmé avant tout nettoyage du run.
6. La validation sélectionne `best`; le test gelé n'est lu qu'une fois après la
   sélection.
7. Deux checkpoints locaux au maximum sont conservés pendant le run : `best` et
   `last`.
8. Les datasets, modèles, caches, logs, PID et reçus locaux restent hors de Git.
9. Aucun secret ou chemin de poste n'est écrit dans un manifeste versionné.
10. Aucun nettoyage ne vise un cache partagé sans inventaire de ses références.

## Identité d'une release

Chaque cycle possède un identifiant immuable :

```text
<architecture>-<objectif>-<version>
```

Exemple :

```text
rfdetr-large-fire-smoke-v2
```

Les deux publications Hugging Face associées sont :

```text
dataset : <HF_ORG>/<train_id>-dataset
model   : <HF_ORG>/<train_id>
```

Les deux dépôts restent dédiés à ce seul `train_id`. Le reçu final relie les
révisions immuables du dataset, du poids de base et du modèle entraîné.

## Machine d'état obligatoire

```text
QUEUED
  -> DATASET_STAGING
  -> DATASET_VALIDATED
  -> DATASET_PUBLISHED
  -> DATASET_REMOTE_VERIFIED
  -> TRAINING
  -> MODEL_VALIDATED
  -> MODEL_PUBLISHED
  -> MODEL_REMOTE_VERIFIED
  -> REMOTE_INVENTORY_CONFIRMED
  -> CLEANUP_READY
  -> PURGED
  -> COMPLETE
```

Le train suivant ne peut atteindre `DATASET_STAGING` que lorsque le précédent
est `PURGED` ou lorsqu'il n'a jamais matérialisé de données locales.

## Organisation locale éphémère

Les chemins réels sont injectés par variables d'environnement. La structure
attendue est :

```text
<TRAINING_ROOT>/
  active/<train_id>/
    source/       # téléchargement courant seulement
    dataset/      # corpus normalisé courant
    shards/       # un shard en cours de publication
    run/          # best, last, métriques et logs
    export/       # modèle final minimal
    receipts/     # reçus locaux hors Git
  receipts/<train_id>/
```

Après purge, seul `receipts/<train_id>/` reste local. Il doit rester petit et
contenir uniquement des JSON, des rapports et des commandes assainies.

## Budget disque

Avant chaque cycle, le préflight calcule :

```text
espace_requis = dataset_normalise
              + 2 * taille_checkpoint_estimee
              + taille_du_plus_gros_shard
              + marge_15_pourcent
```

Le lancement est refusé si cet espace n'est pas disponible. Le cycle interdit :

- un ZIP monolithique du corpus en plus de sa copie extraite ;
- plusieurs datasets matérialisés simultanément ;
- les checkpoints périodiques non bornés ;
- une seconde copie permanente dans un cache personnel ;
- l'extraction d'une archive dans un autre disque sans déclaration explicite.

## Phase 1 — préparer et publier le dataset

1. Enregistrer chaque source par URL et révision publiée.
2. Télécharger une source à la fois dans `source/`.
3. Normaliser les données directement dans `dataset/`.
4. Produire les splits par incident, événement, caméra ou groupe géographique.
5. Refuser les doublons exacts et les fuites entre splits.
6. Écrire `DATASET_MANIFEST.json` et `SPLIT_REPORT.json`.
7. Créer des shards de taille bornée, recommandée entre 2 et 5 Go.
8. Publier chaque shard dès sa fermeture.
9. Confirmer par l'API HF que le manifest et tous les assets attendus sont
   présents dans le dépôt.
10. Enregistrer la révision HF dans `DATASET_RELEASE.json`.
11. Supprimer les archives sources devenues redondantes. Conserver le corpus
    normalisé uniquement pour le train qui suit immédiatement.

Le dataset ne doit plus être emballé dans un unique ZIP de plusieurs centaines
de gigaoctets. Les petits corpus peuvent conserver le contrat ZIP existant ; les
gros corpus passent à un manifeste plus des shards indépendants.

## Phase 2 — préflight et entraînement

Le lancement long nécessite les preuves suivantes :

- révision HF immuable du dataset ;
- inventaire complet du manifest et des assets ;
- révision immuable du modèle de base ;
- tests unitaires ciblés réussis ;
- smoke GPU avec pertes et gradients finis ;
- rapport de splits sans fuite ;
- espace disque conforme au budget ;
- aucun autre train lourd actif.

Pendant l'entraînement :

- `save_total_limit=2` ou mécanisme équivalent ;
- `best` et `last` écrits atomiquement ;
- métriques ajoutées à un fichier borné ;
- logs avec rotation ;
- PID exact, commande assainie et utilisation GPU suivis ;
- aucun nettoyage du dataset ou du cache du processus actif.

## Phase 3 — valider et exporter le modèle

La release minimale contient :

```text
config/
model.safetensors ou checkpoint final natif
preprocessor/
classes.json
metrics.json
TRAINING_PROVENANCE.json
README.md
```

`TRAINING_PROVENANCE.json` contient au minimum :

- `train_id` ;
- architecture et configuration ;
- révision du modèle de base ;
- dépôt et révision du dataset ;
- seed et versions logicielles ;
- métriques validation/test ;
- règle de sélection du checkpoint ;
- indication `merge_required` et méthode de merge éventuelle.

Un full fine-tuning ou un détecteur natif n'est pas artificiellement « mergé ».
Un adaptateur PEFT/LoRA doit fournir à la fois l'adaptateur et, si nécessaire,
un export fusionné distinct.

## Phase 4 — publication et preuve de récupération

Ordre obligatoire :

1. Créer le dépôt modèle dédié au `train_id`.
2. Publier le contenu minimal de `export/`.
3. Enregistrer la révision HF retournée par le commit.
4. Interroger l'inventaire distant avec les métadonnées de fichiers.
5. Refuser le nettoyage si un fichier obligatoire est absent ou vide.
6. Enregistrer l'état du smoke local déjà exécuté sur l'export final.
7. Écrire `MODEL_RELEASE.json` et `REMOTE_INVENTORY_REPORT.json`.

Un simple succès de `hf upload` n'autorise jamais la suppression locale :
l'inventaire HF distant doit confirmer les fichiers obligatoires.

## Gate de nettoyage

`CLEANUP_READY` exige simultanément :

```text
dataset_remote_revision != null
dataset_remote_inventory_complete == true
model_remote_revision != null
model_remote_inventory_complete == true
local_export_smoke_passed == true
training_process_stopped == true
cleanup_targets_resolved_under_training_root == true
```

Le nettoyage génère d'abord un manifeste de prévisualisation indiquant chaque
cible et sa taille. L'exécution doit refuser :

- une cible hors de `<TRAINING_ROOT>/active/<train_id>` ;
- une racine, un dossier parent ou un chemin non résolu ;
- un point de jonction ou autre reparse point non prévu ;
- un dossier utilisé par un PID actif ;
- un cache partagé sans compteur de références nul ;
- un `train_id` différent de celui présent dans les reçus vérifiés.

Après ces contrôles, les éléments supprimables sont :

```text
source/
dataset/
shards/
run/
export/
verify/
```

Les reçus sont déplacés vers `receipts/<train_id>/`. Un inventaire final et le
gain d'espace observé sont enregistrés avant le passage au train suivant.

## Traitement des échecs

### Échec de publication dataset

Le dataset local reste intact. Le train long ne démarre pas.

### Échec du train

Le dataset étant déjà publié, il peut être rematérialisé. `best`, `last`, les
métriques et le diagnostic sont conservés jusqu'à décision de reprise ou
d'archivage. Aucun autre checkpoint n'est conservé.

### Modèle invalide

Le modèle n'est pas publié comme final. Le run peut être archivé dans un dépôt
privé avec `status=failed`, ou supprimé après décision explicite. Le dataset
reste récupérable par sa révision distante.

### Échec de vérification distante

Aucun nettoyage n'est autorisé. La copie locale demeure la référence jusqu'à
ce que l'inventaire HF confirme tous les fichiers obligatoires.

## Orchestrateur du cycle

L'automatisation future doit exposer des commandes idempotentes :

```text
train-cycle prepare-dataset <train_id>
train-cycle publish-dataset <train_id>
train-cycle verify-dataset <train_id>
train-cycle preflight <train_id>
train-cycle train <train_id>
train-cycle validate <train_id>
train-cycle publish-model <train_id>
train-cycle verify-model <train_id>
train-cycle cleanup-plan <train_id>
train-cycle cleanup-apply <train_id>
train-cycle next
```

L'état est écrit atomiquement dans `CYCLE_STATE.json`. Chaque commande vérifie
l'état précédent, peut être relancée sans dupliquer un upload et refuse de
sauter un gate.

## Ordre d'adoption

1. Ajouter la publication et la vérification distante obligatoires aux trainers
   déjà prêts.
2. Borner tous les trainers à deux checkpoints.
3. Remplacer les gros ZIP par des shards vérifiables individuellement.
4. Ajouter le reçu de release commun dataset/modèle.
5. Ajouter le plan de nettoyage fail-closed.
6. Tester le cycle complet sur un petit corpus.
7. Activer l'enchaînement automatique pour les trains lourds.

Le premier essai de l'orchestrateur doit utiliser un corpus réduit. Aucun train
long existant ne doit être relancé uniquement pour tester le mécanisme.
