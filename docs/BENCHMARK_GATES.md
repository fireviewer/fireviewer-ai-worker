# Gates de benchmark

Ce document définit les familles de mesures. Les seuils de promotion sont enregistrés dans les rapports de campagne après mesure des baselines.

## Détection

- AP par classe et par domaine ;
- rappel des petites fumées ;
- faux positifs à rappel fixé ;
- calibration ;
- erreurs par famille de négatifs ;
- temps et mémoire par profil matériel ;
- comportement en cascade, quorum et shadow.

## Segmentation

- IoU par classe ;
- Boundary F1 ;
- petits composants ;
- artefacts parasites ;
- cohérence temporelle ;
- calibration par pixel ;
- performance réel/synthétique séparée.

## Pointage

- PCK à plusieurs tolérances ;
- erreur normalisée ;
- erreur géographique après projection ;
- couverture ;
- précision des abstentions ;
- points hors masque ;
- multi-instance.

## ASR

- WER et CER français bruité ;
- erreur de timestamps ;
- hallucinations sur silence ;
- mots critiques ;
- taux de segments omis.

## Ministral

- conformité au schéma ;
- validité des `evidence_refs` ;
- affirmations non supportées ;
- conservation des contradictions ;
- respect des outils autorisés ;
- absence de champs géographiques ;
- stabilité du replay.

## Retrieval

- Recall@K ;
- présence de la bonne zone ou pose parmi les candidats ;
- erreurs par saison, météo, relief et profil de caméra.

## Pose

- taux de résolution ;
- erreur médiane et quantiles ;
- erreurs catastrophiques ;
- reprojection ;
- stabilité au sous-échantillonnage ;
- abstentions correctes.

## Incertitude

- couverture empirique ;
- taille des enveloppes ;
- calibration par domaine ;
- motifs d’abstention ;
- stabilité du bootstrap.

## Runtime

- cold start ;
- exécution chaude ;
- pic VRAM ;
- RSS ;
- coût par média ;
- erreurs de cache ;
- fuite mémoire ;
- résultats partiels ;
- dead letters.

## Règle de promotion

Une promotion exige :

- lot tenu à l’écart ;
- splits groupés ;
- artefacts archivés ;
- rapport d’erreurs ;
- comparaison avec la baseline ;
- revue humaine ;
- rollback.
