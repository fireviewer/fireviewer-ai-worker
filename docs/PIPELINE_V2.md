# Pipeline IA v2

**Source canonique :** `docs/ARCHITECTURE.md`

## Décision d’architecture

Le runtime conserve une exécution GPU séquentielle. Le changement porte sur le plan de contrôle : l’ordre fixe des rôles devient un graphe déclaratif de stages.

Chaque stage déclare :

- capacités requises ;
- entrées ;
- sorties ;
- pré-gate ;
- post-gate ;
- reason codes ;
- comportement de reprise ;
- profil de cascade, consensus ou shadow.

## Stages

```text
validate_media
extract_audio
detect_speech
transcribe
sample_video_frames
triage_video
detect_precise
run_ocr
point_primary
segment_point_shadow
extract_observations
classify_view_profile
retrieve_spatial_candidates
match_spatial
estimate_pose
raycast
propagate_uncertainty
finalize_review_payload
```

Les stages non applicables retournent `not_applicable`. Une incapacité à conclure retourne une abstention typée. Une erreur technique retourne `failed`.

## Pipeline média

### Audio

```text
audio
→ VAD
→ Whisper
→ segments de preuve
→ Ministral
```

### Vidéo

```text
vidéo
→ frames candidates
→ RT-DETRv2 triage
→ keyframes
→ D-FINE
→ MolmoPoint
→ DINOv3 shadow
→ Ministral
```

### Image

```text
image
→ D-FINE
→ OCR conditionnel
→ MolmoPoint
→ DINOv3 shadow
→ Ministral
```

## Détecteurs

Profils :

- `production_cascade`
- `validation_quorum`
- `shadow_sampling`

D-FINE reste principal. RT-DETRv2 est utilisé pour le triage et la contre-détection selon le profil. RF-DETR reste hors production tant qu’un benchmark FireViewer ne justifie pas sa promotion.

## Pointage

MolmoPoint reste primaire.

Le challenger DINOv3 produit des masques, heatmaps et abstentions visuelles. Il ne produit pas `insufficient_geometry`, qui appartient à la branche spatiale.

## Analyse structurée

Ministral remplace Qwen pour :

- extraction ;
- recherche bornée ;
- synthèse privée ;
- arbitrage textuel ou structuré.

Aucun champ géographique n’est autorisé dans ses contrats.

## GPU

- un seul gros modèle chargé à la fois ;
- déchargement et contrôle mémoire entre stages ;
- révisions verrouillées ;
- pas de téléchargement silencieux ;
- résultats partiels conservés ;
- backend source durable des lots et transitions.

## Promotion

Un stage est promu après :

- tests de contrat ;
- replay ;
- benchmark ;
- recette GPU ;
- shadow mode ;
- analyse d’erreurs ;
- décision documentée.
