# Raccordement du worker au backend FireWarning

## Frontière

Le navigateur ne contacte jamais RunPod. FastAPI persiste les packages, consentements, fenêtres,
lots et résultats privés. Un dispatcher CPU durable est l’unique client du worker.

```text
sources utilisateur / recherche Admin / satellite
  -> stockage et contrat privés
  -> lots et dispatch persistés
  -> worker RunPod authentifié
  -> candidats séquentiels + consensus
  -> revalidation backend
  -> proposition privée et revue humaine
  -> publication explicite séparée
```

La table historique `job` reste réservée à son usage historique. Les analyses utilisent les tables
`agent_*`, dont les packages de sources, consentements, recherches, lots, dispatchs, sorties
candidates, consensus, dead letters et revues.

## Contrat de transport

Deux transports partagent les mêmes états et le même payload :

- pod persistant de recette : `POST /v1/jobs`, `GET /v1/jobs/{id}` et
  `POST /v1/jobs/{id}/cancel` ;
- Serverless futur : `/run`, `/status/{id}` et `/cancel/{id}` après bascule explicite.

Le Bearer est injecté par le gestionnaire de secrets. Aucun token ne doit apparaître dans Git,
l’image ou les exemples. Le `batch_id`, l’empreinte du payload, les révisions attendues et la fenêtre
d’analyse sont persistés avant soumission.

## Pod A40 v1

Le pod de recette démarre avec le manifeste `firewarning-mvp-a40-v1`. Il exige BF16, Flash Attention
2, une file GPU séquentielle et un seul gros modèle en VRAM. Les poids épinglés manquants sont
téléchargés sur le volume monté ; ils ne sont ni copiés dans l’image ni versionnés.

La recherche tourne dans un processus isolé. Il peut joindre le courtier par socket Unix mais ne peut
pas ouvrir de socket IPv4/IPv6. Le courtier applique HTTPS, liste blanche, limites, protection SSRF et
provenance sans accéder aux poids, lots ou secrets backend.

Le service refuse les recherches si le probe `no_new_privs`/seccomp échoue. Le pod peut rester chaud
pendant une campagne puis être arrêté hors test.

## Candidats, gates et consensus

Chaque étape fournit un groupe de candidats épinglés, une politique de consensus, des seuils et un
nombre minimal de succès. Les candidats sont exécutés et déchargés un par un. Le worker conserve leur
sortie privée, télémétrie et digest, puis compare les résultats.

Une étape est libérée uniquement si son résultat est admissible. Une contradiction peut appeler
l’arbitre final ; sinon elle produit une abstention ou une revue. Elle ne supprime pas les autres
résultats valides du lot et ne publie rien.

## Validation backend

Avant écriture métier, le backend vérifie :

1. identité du batch et de chaque entrée ;
2. modèle, candidat et révision attendus ;
3. digest et schéma de chaque sortie ;
4. couverture exacte des candidats par le consensus ;
5. appartenance des preuves au lot ;
6. compatibilité temporelle avec la fenêtre d’analyse ;
7. caractère privé du résultat.

Une sortie invalide, une révision inattendue, une échéance dépassée ou un échec non récupérable ouvre
une dead letter. Une sortie partielle admissible peut créer une revue, jamais une publication.

## Livrables spatiaux

Les calques sont rattachés à la scène 3D existante. Le worker ne remplace jamais le package 3D. Une
coordonnée n’est admise que par une voie géométrique contrôlée : pose et caméra valides, rayon puis
intersection MNT. Sans ces préconditions, le pipeline s’abstient.

Point chaud, front visible, périmètre brûlé, enveloppe probable et simulation restent des types
distincts. Le backend refuse leur promotion implicite d’un type vers un autre.

## Training et artefacts

Le code de training et l’image dédiée peuvent être versionnés. Les datasets, médias, archives, poids,
checkpoints, caches, sorties de runs et secrets restent hors Git et hors image publique. La génération
des datasets est maintenue dans une branche distincte de ce raccordement runtime.
