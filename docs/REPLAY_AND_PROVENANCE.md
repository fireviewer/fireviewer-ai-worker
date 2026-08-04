# Replay et provenance

**Provenance de sortie `event-2.0` :** `IMPLEMENTED_TESTED_LOCAL`

**Manifeste de replay complet :** `PENDING`

## Objectif

Un résultat doit pouvoir être expliqué et, lorsque les dépendances le permettent, rejoué à partir des mêmes entrées et révisions.

## Manifeste de replay cible

Le worker local conserve déjà modèle, révision, méthode, référence, ancrages, reason codes et statut shadow dans les sorties `event-2.0`. Il retourne également les ancrages de perception et les preuves spatiales effectivement utilisés. Un ancrage nouvellement inféré doit référencer un média privé exact du bundle ; une preuve spatiale localisée n’est acceptée que si elle était déjà présente à l’identique dans l’outbox persistante. Le cross-view est conservé sous l’état distinct `SHADOW` et ne peut alimenter un événement. Le manifeste inter-dépôts complet ci-dessous n’est pas encore matérialisé comme un artefact signé unique.

Le manifeste conserve :

- identifiant de l’événement candidat et révision source ;
- snapshot du point de vue et de sa visibilité ;
- intervalle observé ;
- identifiant du lot ;
- identifiant du média ;
- empreinte du média ;
- artefacts parents ;
- contrats ;
- stages exécutés ;
- stages non applicables ;
- abstentions ;
- modèle et révision ;
- paramètres d’inférence ;
- seed lorsqu’elle existe ;
- profil matériel ;
- versions runtime ;
- sorties ;
- erreurs ;
- temps et ressources mesurés ;
- trace d’audit.
- relations d’événements proposées ;
- événements supports d’une enveloppe ;
- CRS natifs, transformations et datums.

## Résultats partiels

Un résultat partiel est conservé uniquement si :

- son stage est terminal ;
- son schéma est valide ;
- ses artefacts existent ;
- ses parents sont vérifiables ;
- les étapes manquantes sont explicites.

## Recherche externe

Le replay enregistre :

- requête ;
- outil ;
- URL ;
- organisation, collection, identifiant objet et révision ;
- temps d’acquisition, de traitement et de publication ;
- date de collecte ;
- contenu archivé ;
- empreinte ;
- ETag ou Last-Modified lorsqu’ils existent ;
- licence, attribution et politique d’archivage ;
- CRS, footprint, résolution et filiation ;
- extraits utilisés ;
- liens vers les observations.

## Limites

Un replay peut différer lorsqu’une dépendance externe non archivée a changé. Cette limite doit être déclarée au lieu d’être masquée.

Une décision humaine est référencée, mais elle n’est jamais rejouée comme une sortie du modèle. Une nouvelle version d’une page à la même URL et une rétractation fournisseur restent deux révisions auditables.
