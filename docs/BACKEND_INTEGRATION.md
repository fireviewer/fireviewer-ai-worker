# Raccordement du worker au backend FireViewer

## Frontière

Le navigateur ne contacte jamais RunPod. FastAPI persiste les candidats d’événement, points de vue,
consentements, preuves, fenêtres temporelles et résultats privés. Un dispatcher CPU durable est
l’unique client du worker.

```text
point de prise de vue + temps + message ou médias
  -> candidat d’événement et preuves privées persistés
  -> observations officielles et satellitaires versionnées
  -> bundle event-2.0 et dispatch persisté
  -> worker RunPod authentifié
  -> ancrages + localisation ou abstention + contradictions
  -> résultat event-result-2.0 revalidé par le backend
  -> proposition DRAFT et revue analyste
  -> publication éditeur explicite et séparée
```

La table historique `job` reste réservée à son usage historique. Les contrats et tables `agent_*`
restent disponibles pendant la migration additive. Ils ne remplacent pas les entités v2
`EventCandidate`, `Viewpoint`, `EvidenceAsset`, `LocalizationAttempt` et `FireActivityEvent`.

## Contrat événementiel v2

Le backend envoie un `EventPipelineInput` fermé avec `schema_version: event-2.0`. Le bundle contient
exactement un incident connu ou un incident candidat privé, un point de prise de vue, un intervalle
observé, un consentement d’analyse et de conservation, puis au moins un message ou un média.

Le worker répond avec `event-result-2.0`. Il conserve les ancrages, preuves spatiales, tentatives de
localisation, propositions d’activité, familles de preuves externes indépendantes, contradictions et
reason codes. `requires_human_review` reste toujours vrai.

Le backend demeure propriétaire des transitions métier et de la publication. Le worker ne peut ni
confirmer un incident candidat, ni valider un événement, ni publier une géométrie.

## Transport et compatibilité

Le contrat événementiel emprunte le transport authentifié déjà déployé. Les transports historiques
suivants restent supportés pendant la migration :

- pod persistant de recette : `POST /v1/jobs`, `GET /v1/jobs/{id}` et
  `POST /v1/jobs/{id}/cancel` ;
- Serverless futur : `/run`, `/status/{id}` et `/cancel/{id}` après bascule explicite.

Le Bearer est injecté par le gestionnaire de secrets. Aucun token ne doit apparaître dans Git,
l’image ou les exemples. L’identifiant du candidat, l’empreinte du payload, les révisions attendues,
la fenêtre d’analyse et l’idempotency key sont persistés avant soumission.

## Pod A40 v1

Le pod de recette historique démarre avec le manifeste interne `firewarning-mvp-a40-v1`. Ce nom est
un alias de compatibilité déprécié et ne définit pas la marque publique. Le profil exige BF16, Flash Attention
2, une file GPU séquentielle et un seul gros modèle en VRAM. Les poids épinglés manquants sont
téléchargés sur le volume monté ; ils ne sont ni copiés dans l’image ni versionnés.

La recherche tourne dans un processus isolé. Il peut joindre le courtier par socket Unix mais ne peut
pas ouvrir de socket IPv4/IPv6. Le courtier applique HTTPS, liste blanche, limites, protection SSRF et
provenance sans accéder aux poids, lots ou secrets backend.

Le service refuse les recherches si le probe `no_new_privs`/seccomp échoue. Le pod peut rester chaud
pendant une campagne puis être arrêté hors test.

## Stages, gates et résultats partiels

Chaque stage fournit des capacités et révisions épinglées, des seuils et une politique de cascade,
consensus ou shadow. Les modèles lourds sont exécutés et déchargés un par un. Le worker conserve leur
sortie privée, télémétrie et digest, puis compare les résultats lorsque le profil l’exige.

Une étape est libérée uniquement si son résultat est admissible. Une contradiction produit une revue
ou une abstention et reste visible. Elle ne supprime pas les autres résultats valides du bundle et ne
publie rien.

## Validation backend

Avant écriture métier, le backend vérifie notamment :

1. identité et version du candidat d’événement ;
2. modèle, stage et révision attendus ;
3. digest et schéma de chaque sortie ;
4. couverture attendue des stages et résultats shadow ;
5. appartenance des preuves au bundle privé ;
6. compatibilité temporelle avec la fenêtre d’analyse ;
7. caractère privé du résultat.

Une sortie invalide, une révision inattendue, une échéance dépassée ou un échec non récupérable ouvre
une dead letter. Une sortie partielle admissible peut créer une proposition de revue, jamais une
publication.

## Livrables spatiaux

Les calques sont rattachés à la révision spatiale de l’incident. Le worker ne remplace jamais le
package 3D. Une
coordonnée n’est admise que par une voie géométrique contrôlée : pose et caméra valides, rayon puis
intersection MNT. Sans ces préconditions, le pipeline s’abstient.

Flamme active, origine de fumée, hotspot, front visible, surface brûlée, enveloppe probable et simulation restent des types
distincts. Le backend refuse leur promotion implicite d’un type vers un autre.

## Training et artefacts

Le code de training et l’image dédiée peuvent être versionnés. Les datasets, médias, archives, poids,
checkpoints, caches, sorties de runs et secrets restent hors Git et hors image publique. La génération
des datasets est maintenue dans une branche distincte de ce raccordement runtime.
