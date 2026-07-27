# FireViewer AI worker

Worker agentique privé pour l’analyse factuelle de médias FireViewer. Le dépôt
contient le runtime, les contrats, l’orchestration et les outils génériques de
préparation. Il ne contient aucun corpus, média, poids, checkpoint, sortie
d’inférence, secret ou cas d’incident réel.

## Principes

- Chaque sortie reste privée jusqu’à une décision humaine.
- Un fait, un repère spatial et un rapport sont des propositions indépendantes.
- Une abstention explicite est préférable à une géométrie non démontrée.
- Les modèles et leurs révisions sont configurés et chargés depuis un volume
  externe au dépôt.
- Les téléchargements sont limités aux hôtes HTTPS autorisés.
- Le runtime n’effectue aucune publication publique.

Le contrat producteur se trouve sous `contracts/agent-worker`. Les consommateurs
doivent verrouiller le tag, le chemin et le SHA-256 dans leur
`contracts.lock.json`.

## Installation et contrôles

```bash
python -m pip install -e ".[dev]"
ruff check src tests scripts training tools
ruff format --check src tests scripts training tools
mypy src
pytest -q
docker build -t fireviewer-ai-worker:local .
```

Les tests locaux emploient uniquement des cas synthétiques. Ils ne prouvent ni
le fonctionnement CUDA, ni la présence des poids, ni la qualité des modèles sur
un endpoint RunPod. Ces validations sont réalisées séparément avec des artefacts
privés.

## Configuration

Les valeurs sensibles sont injectées à l’exécution. Les noms de variables et
leurs contraintes sont documentés dans `.env.example`; ce fichier ne contient
aucune valeur secrète. Les caches Hugging Face, poids privés, corpus et bundles
de validation doivent rester sur un volume externe.

## Données et modèles

Les scripts de `training/` préparent des manifestes génériques. Les racines de
données sont fournies explicitement par l’opérateur et doivent rester hors du
checkout. Aucun téléchargement, rendu ou résultat généré n’est destiné à Git.

## Publication

Le dépôt source est publié sous AGPL-3.0-or-later. La documentation est proposée
sous CC BY 4.0. Les licences des modèles et datasets externes restent celles de
leurs producteurs et doivent être vérifiées avant toute utilisation.
