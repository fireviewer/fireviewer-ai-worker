# Bundles d'entraînement FireWarning

Le dépôt privé `Charlbi/firewarning-training-corpus` publie **un ZIP par objectif
d'entraînement**. Les anciennes archives par source sont uniquement des entrées de migration ; elles
ne constituent pas le format final.

## Contrat final

Chaque ZIP possède une racine unique portant l'identifiant du train et contient :

- `TRAIN_BUNDLE.json` : sources, licences, état des gates et commandes ;
- `PAYLOAD_CHECKSUMS.sha256` : empreinte de chaque fichier source ;
- les sources montées aux chemins attendus par les trainers (`corpus/`, `sources/`, `additional/`) ;
- les manifestes `train` / `validation` / `test` fournis par chaque source ;
- aucune donnée critique ni incident Référence opérationnelle A/Référence opérationnelle B utilisé comme évaluation finale.

Les quatre bundles v1 sont déclarés dans `train-bundles-v1.json` et leurs spécifications exécutables
sont sous `specs/`.

## Construction locale

```powershell
python tools/dataset_hub/finalize_train_bundle.py `
  --spec tools/dataset_hub/specs/media-filter-fire-smoke-v1.json `
  --source-root D:\fireviewer-data\_train-bundles\remote `
  --work-dir D:\fireviewer-data\_train-bundles\work `
  --output-dir D:\fireviewer-data\_train-bundles\ready
```

La commande refuse le ZIP en cas d'archive tronquée, d'empreinte invalide, de chemin dangereux, de
fichier manquant, de doublon inter-source ou de fuite entre splits. Le ZIP est ensuite relu en entier
(CRC et SHA-256 de chaque entrée).

## Remplacement sur Hugging Face

Le remplacement distant n'est autorisé qu'après :

1. validation locale complète du ZIP ;
2. sauvegarde locale du ZIP et de son rapport ;
3. commit privé atomique ajoutant le ZIP et supprimant les anciennes archives couvertes ;
4. téléchargement de contrôle et vérification du SHA-256 distant ;
5. nettoyage du dossier local temporaire.

Si le commit atomique échoue, les archives distantes existantes restent la référence et la copie
locale n'est pas supprimée. Une source partagée par plusieurs objectifs reste déclarée dans chaque bundle concerné. Les lots
critiques et les références opérationnelles restent sous `evaluation/` et ne sont jamais promus dans
un ZIP de train.

## Sources supplémentaires

La préparation locale complémentaire utilise les mêmes manifestes et les mêmes contrôles :

- `prepare_supplemental_sources.py` : FireSpread_MedEU, Boreal Forest Fire,
  CrisisFACTS, IMSR, TartanAir rural/nature et DIODE outdoor ;
- `download_supplemental_archives.py` : téléchargements épinglés, reprenables et vérifiés de
  TartanAir et DIODE ;
- `download_boreal_forest_fire.py` : inventaire officiel Etsin et téléchargement Boreal par profil ;
- `prepare_openimages_engaged_assets.py` : sous-ensemble Open Images licencié par image pour
  ambulance, hélicoptère et avion ;
- `prepare_access_and_quarantine.py` : demande Corsican Fire Database sans envoi automatique et
  quarantaine McPed sans téléchargement ni republication des vues Google Earth.

Chaque source normalisée contient `SOURCE_MANIFEST.json`, `VALIDATION_REPORT.json`,
`manifest.jsonl`, les empreintes des artefacts et des groupes de split isolés par événement ou
site. La commande `bundle` produit exactement un ZIP par objectif d'entraînement, puis relit
intégralement le ZIP (CRC, chemins, inventaire et SHA-256 de chaque entrée).

Les sources et archives temporaires ne peuvent être supprimées qu'après publication du ZIP final,
retéléchargement depuis Hugging Face et égalité de l'empreinte distante. TartanAir reste un prior
synthétique ; Open Images ne fournit ni classe boxable camion de pompiers ni rôle aérien de lutte ;
la Corsican Fire Database attend un accord humain signé ; McPed reste privé tant que les droits de
ses vues aériennes ne permettent pas une republication indépendante.
