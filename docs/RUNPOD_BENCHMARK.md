# Recette RunPod 16 Go et arbitrage du cold start

## Préconditions bloquantes

- image Docker identifiée par digest, pas seulement par tag ;
- `flash-attn==2.8.3` importable et GPU NVIDIA Ampere, Ada, Hopper ou plus récent ;
- trois snapshots publics présents aux commits inscrits dans `model_registry.py` ;
- RT-DETR présent, son SHA-256 vérifié et son benchmark métier accepté ;
- hôte de médias privé autorisé, URLs courtes et révocables ;
- aucun secret dans les logs ;
- endpoint de staging sans accès au service de publication.

## Matrice à exécuter

Pour chaque GPU 16 Go candidat et pour `idleTimeout = 60, 90, 120, 300, 600` secondes :

1. partir de zéro worker actif ;
2. soumettre le même lot de référence par `/run` ;
3. relever délai de file, initialisation du conteneur, `boot_ms`, chargement et inférence par modèle ;
4. relever le pic VRAM par modèle et côté plateforme ;
5. répéter trois cold starts ;
6. soumettre un second lot pendant la fenêtre chaude ;
7. calculer coût du cold start, coût d'inférence et coût d'attente séparément.

Le timeout retenu est le plus petit qui respecte le SLO utilisateur. D'un point de vue coût pur, le
seuil de rentabilité d'une attente chaude est approximativement la durée du cold start évité, puisque
le même GPU est facturé pendant les deux périodes. Les distributions réelles de lots doivent remplacer
cette approximation.

`boot_ms` mesure uniquement l'initialisation Python jusqu'à l'enregistrement du handler. Le délai de
file, le provisionnement GPU, le téléchargement éventuel de l'image et FlashBoot sont des mesures de
plateforme à relever séparément ; leur somme constitue le cold start perçu.

## Dix cycles de stabilité

Exécuter dix fois sur le même worker chaud un lot contenant audio, images, frames et texte. Pour chaque
cycle, enregistrer :

- `torch.cuda.memory_allocated()` avant et après chaque modèle ;
- `torch.cuda.memory_reserved()` avant et après nettoyage ;
- `torch.cuda.max_memory_allocated()` ;
- RSS du processus ;
- temps de chargement et d'inférence ;
- identifiant et révision de chaque modèle ;
- statut de validation de chaque sortie.

Échec de recette si un cycle dépasse 16 Go, si la mémoire allouée finale croît de façon monotone, si le
RSS dérive sans plateau explicable ou si une révision diffère du registre. `empty_cache()` seul ne
constitue pas une preuve d'absence de fuite.

## Cas d'échec obligatoires

- cache Qwen absent : échec fermé sans téléchargement réseau ;
- SHA-256 RT-DETR faux : aucun chargement du checkpoint ;
- URL externe ou redirection : refus avant lecture du corps ;
- JSON Qwen invalide deux fois : résultat antérieur conservé et revue humaine ;
- preuve inconnue : sortie rejetée ;
- image sans coordonnées : aucun marqueur ;
- GPS EXIF : marqueur de prise de vue seulement ;
- panne Florence : transcription et détections précédentes conservées ;
- dépassement du délai : job récupérable côté backend, jamais publication partielle.

## Limite de preuve locale

La suite unitaire prouve les contrats et le cycle logique de libération. Elle ne prouve ni la tenue
réelle en 16 Go, ni Flash Attention 2, ni les performances, ni la qualité de RT-DETR. Ces conclusions
restent **À VALIDER SUR RUNPOD** jusqu'à exécution et archivage des mesures ci-dessus.
