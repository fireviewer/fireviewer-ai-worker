# Event-localisation mini-corpus — France, summer 2026

This research lot covers nine wildfires from June, July, and August 2026. It is
limited to the event-localisation evaluation path and never feeds the separate
map-production pipeline.

| Month | Event | Media reviewed | Independent polygon reference | Panoramax metadata probe (maximum 25) |
| --- | --- | ---: | --- | ---: |
| June | Die / Justin massif, 24 June | 20 | CEMS EMSR890, verified | 25 |
| June | Boussès, 23 June | 20 | not yet identified | 25 |
| June | Bénonces / Serrières-de-Briord, 23 June | 20 | not yet identified | 25 |
| July | Trévillach, 4 July | 20 | CEMS EMSR889, verified | 25 |
| July | Fontainebleau, 12 July | 20 | CEMS EMSR894, verified | 25 |
| July | Saumos, 22 July | 20 | CEMS EMSR899, verified | 25 |
| July | Biscarrosse, 23 July | 20 | CEMS EMSR902, verified | 25 |
| August | Bellegarde-en-Diois / Claps massif, 3 August | 20 | not yet identified | 1 |
| August | Luglon, 14 August | 20 | not yet identified | 0 |

## Gate status

The corpus is `coverage_profiled`, not `benchmark_ready`:

- five CEMS layers were summarised from exact bytes and verified by SHA-256;
- the Panoramax probe is bounded to each area of interest and downloads no
  images;
- 180 media items were selected after visual review: exactly 20 per event;
- every selected file has a source URL, dimensions, and SHA-256 in the private
  materialisation inventory;
- the technical media gate is `pass`, while rights review is
  `not_evaluated` and remains an independent gate;
- four events still have no independent polygon ground truth;
- Luglon has no Panoramax reference in the area of interest and Bellegarde has
  one.

No model result may therefore be labelled `PASS`, `PARTIAL`, or `FAIL` from
this inventory alone.

## Versioned records

- `france-summer-2026-candidates.v1.json`: strict event and provenance manifest;
- `france-summer-2026-media-ready.v1.json`: reviewed 180-media inventory;
- `france-summer-2026-preflight-20260821.json`: Copernicus/Panoramax preflight
  receipt;
- `event-media-inventory-20260821.json`: deduplicated, hashed inventory;
- `event-media-reviewed-selection-20260821.json`: fixed 20-item selection per
  event;
- `event-media-review-decisions.v1.json`: reproducible review decisions;
- `tools/probe_mvp_summer_2026.py`: metadata-only reproducibility probe.

These records document corpus coverage. They do not grant media rights, prove
independent splits, or establish detector or localisation quality.
