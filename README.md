# FireViewer AI worker

Worker agentique privé pour l’analyse factuelle de médias FireViewer. Le dépôt
contient le runtime, les contrats, l’orchestration et les outils génériques de
préparation. Il ne contient aucun corpus, média, poids, checkpoint, sortie
d’inférence, secret ou cas d’incident réel.

## Position dans l’architecture événementielle v2

L’unité d’analyse n’est plus un média isolé. Le worker reçoit un bundle privé
`event-2.0` qui réunit le candidat d’événement, le point de prise de vue, le
moment observé, le message, les médias autorisés, la provenance et les
observations externes déjà collectées par le backend.

La sortie `event-result-2.0` conserve séparément :

- le profil de prise de vue ;
- les ancrages visuels issus des preuves privées ;
- les preuves et tentatives de localisation ;
- les contradictions entre sources indépendantes ;
- les propositions d’activité en état `DRAFT` ;
- les motifs d’abstention ou d’échec.

Toute sortie exige une revue humaine. Le worker ne crée pas un événement
publié, ne transforme pas le point de prise de vue en point actif et ne ferme
pas un périmètre à partir d’une fumée, d’un hotspot ou d’une simulation.

Le contrat événementiel est protégé par
`FV_AGENT_EVENT_PIPELINE_ENABLED`. Les contrats historiques restent lisibles
pendant la migration, sans devenir la source canonique du produit v2.

## Principes

- Chaque sortie reste privée jusqu’à une décision humaine.
- Un fait, un ancrage visuel, une géométrie et un rapport sont des propositions
  indépendantes et traçables.
- Une abstention explicite est préférable à une géométrie non démontrée.
- Un modèle de langage peut structurer les faits, mais ne peut pas inventer une
  coordonnée, un périmètre ou une chronologie.
- La branche cross-view reste en `SHADOW` jusqu’à un benchmark événementiel
  indépendant et ne peut pas alimenter un événement publiable.
- Les modèles et leurs révisions sont configurés et chargés depuis un volume
  externe au dépôt.
- Les téléchargements sont limités aux hôtes HTTPS autorisés.
- Le runtime n’effectue aucune publication publique.

Le contrat producteur se trouve sous `contracts/agent-worker`. Les consommateurs
doivent verrouiller le tag, le chemin et le SHA-256 dans leur
`contracts.lock.json`.

## Documentation de référence

- `docs/PIPELINE_V2.md` : graphe de stages et règles de promotion ;
- `docs/SPATIAL_REGISTRATION.md` : recalage, raycast et abstentions ;
- `docs/REPLAY_AND_PROVENANCE.md` : éléments nécessaires au replay ;
- `docs/MODEL_REGISTRY.md` : rôles et statuts documentaires des modèles ;
- `docs/BENCHMARK_GATES.md` : métriques et gates avant promotion ;
- `docs/BACKEND_INTEGRATION.md` : frontière de confiance avec le backend.

La doctrine produit, les contrats transverses et la matrice d’acceptation sont
maintenus dans le dépôt canonique `fireviewer/Fireviewer_doc`.

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

Les nouveaux entraînements longs et les promotions de challengers restent
suspendus tant qu’un benchmark événementiel, groupé par incident, ne mesure pas
la localisation en mètres, la cohérence temporelle, la calibration et la
qualité des abstentions.

## Publication

Le dépôt source est publié sous AGPL-3.0-or-later. La documentation est proposée
sous CC BY 4.0. Les licences des modèles et datasets externes restent celles de
leurs producteurs et doivent être vérifiées avant toute utilisation.
