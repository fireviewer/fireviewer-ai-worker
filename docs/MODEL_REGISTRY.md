# Registre des modèles

La table opérationnelle doit être générée depuis les manifestes du runtime. Ce document décrit les responsabilités et règles de gouvernance.

| Fonction | Modèle | Rôle | Statut documentaire |
| --- | --- | --- | --- |
| ASR | Whisper Large V3 Turbo | Transcription locale | intégré, qualification suivie séparément |
| Détection principale | D-FINE XLarge FireViewer | Images et keyframes | intégré |
| Triage / second détecteur | RT-DETRv2-R50 FireViewer | Vidéo et contre-détection | intégré |
| Pointage primaire | MolmoPoint-8B FireViewer | Ancrages visuels | intégré |
| Analyse structurée actuelle | Qwen | Ancien rôle | migration en cours |
| Analyse structurée cible | Ministral 3 8B Instruct | Extraction, recherche et rapport privé | bloqué jusqu’à intégration |
| OCR | PP-OCRv6 Small | Indices textuels CPU | à intégrer |
| Segmentation-pointage | DINOv3 multi-tâches | Challenger shadow | benchmark |
| Baseline segmentation | SegFormer | Comparaison hors ligne | benchmark |
| Annotation | SAM | Pré-annotation et suivi | hors runtime normal |
| Surface brûlée | Prithvi officiel | Produit auxiliaire | intégré |
| Matcher actuel | AerialExtreMatch-RoMa | Baseline spatiale | promotion bloquée |
| Matcher challenger | RoMa v2 | Sol et UAV | benchmark |
| Pose | PyCOLMAP | Estimation et raffinement | à intégrer |
| Profondeur auxiliaire | MoGe | Intrinsics et cohérence | benchmark |
| Prior multivue | VGGT-Ω | Séquences | long terme |
| Challenger détection | RF-DETR | Comparaison | benchmark |

## Champs du manifeste

Chaque entrée doit conserver :

- identifiant ;
- fournisseur ;
- révision immuable ;
- licence ;
- type de tâche ;
- capacité ;
- profil matériel ;
- précision numérique ;
- URI ou cache attendu ;
- empreinte ;
- statut d’activation ;
- contrats compatibles ;
- méthode de déchargement ;
- artefacts de benchmark.

## Règles

- aucun fallback vers `main` ;
- aucune révision flottante ;
- aucun modèle déclaré actif uniquement parce que ses poids sont présents ;
- aucune performance copiée depuis un benchmark externe comme preuve FireViewer ;
- tout retrait conserve l’historique de la révision.
