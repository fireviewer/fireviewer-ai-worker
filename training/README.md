# Préparation générique des données

Ce dossier contient uniquement le code de préparation et de validation des
manifestes d’entraînement. Aucun média, dataset, annotation, rendu, modèle,
checkpoint ou résultat d’évaluation n’est versionné.

## Règles

- fournir une racine de données externe au dépôt ;
- conserver la provenance, la licence et le SHA-256 de chaque entrée ;
- séparer les groupes proches avant le découpage train/validation/test ;
- refuser les incidents opérationnels et les productions privées ;
- ne jamais inclure les données dans une image Docker publique ;
- exiger une validation humaine avant toute promotion d’un modèle.

Les exemples et tests utilisent des identifiants et des contenus synthétiques.
Les registres JSON versionnés décrivent seulement des contrats ou des sources,
jamais les échantillons eux-mêmes.

## Contrôles

```bash
ruff check training tools
ruff format --check training tools
pytest -q
```

Une exécution GPU, un corpus externe ou une campagne de qualité restent des
gates séparés et ne sont pas prouvés par ces tests locaux.
