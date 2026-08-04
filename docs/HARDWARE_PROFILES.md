# Profils matériels et runtime

## Source de vérité

Les profils actifs sont définis dans les manifestes et configurations versionnés du dépôt. Les README ne recopient pas des estimations de VRAM ou de latence sans artefact de mesure.

## Principes

- un gros modèle chargé à la fois ;
- chargement séquentiel ;
- déchargement explicite ;
- révisions verrouillées ;
- précision numérique déclarée ;
- résolution d’entrée déclarée ;
- batch déclaré ;
- contexte LLM déclaré ;
- cache externe ;
- aucun poids dans l’image publique.

## Profils

Un profil matériel décrit :

- GPU ;
- runtime CUDA ;
- version PyTorch ;
- backend d’inférence ;
- précision ;
- résolution ;
- batch ;
- limites de contexte ;
- modèles autorisés ;
- politique de cache ;
- métriques archivées.

## Documentation des mesures

Toute valeur publiée doit référencer :

- révision du code ;
- révision du modèle ;
- profil matériel ;
- commande ;
- dataset ou fixture ;
- p50/p95 lorsque pertinent ;
- cold start ou exécution chaude ;
- date ;
- artefact de sortie.

## Conflits documentaires

Lorsqu’un runbook ancien mentionne un profil générique différent du manifeste actif :

1. le manifeste actif prévaut pour le runtime ;
2. le runbook est marqué historique ou mis à jour ;
3. les chiffres non reproduits sont retirés ;
4. aucune compatibilité matérielle n’est déduite sans recette.
