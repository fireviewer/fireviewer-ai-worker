# Source Acquisition Method

## Purpose

The source-acquisition system builds a usable, time-qualified evidence record
for each wildfire episode. Its deliverable is not a list of search results and
not a collection of downloaded files. It is a set of durable evidence tickets
that can support an observable incident timeline and, when spatial evidence is
available, the deterministic perimeter stage.

The scraper owns the acquisition loop. A downstream worker must never have to
invent a manual search plan or create a synthetic `EventCandidate` to start
research.

```text
incident + episode + local day + AOI
                 |
                 v
       adaptive source acquisition
                 |
        +--------+---------+
        |                  |
        v                  v
 public Web evidence   structured EO APIs
        |                  |
        +--------+---------+
                 v
       IncidentDayEvidenceBundle
                 |
                 v
     vision / geography / supervision
                 |
                 v
 deterministic observed perimeter candidate
```

The acquisition system does not draw a perimeter and it does not read the
published perimeter used as evaluation truth.

## Canonical acquisition target

Every run starts from a backend-created, immutable target containing:

- `research_id`, `incident_id`, `episode_id`, and `analysis_id`;
- canonical incident name and public aliases;
- the local calendar day and its timezone-aware UTC interval;
- the incident AOI or a conservative search radius around its public reference;
- known episode timestamps and lifecycle hints such as ignition, resumption,
  fixed, controlled, or ended;
- source-registry revision and connector revisions;
- the previous accepted evidence snapshot, without any held-out perimeter.

The target is generated from durable incident state. User-entered query JSON,
domains, URLs, and search templates are not accepted by the worker.

## Acquisition state machine

```text
PLANNED
  -> DISCOVERING
  -> FETCHING
  -> VERIFYING
  -> EXTRACTING
  -> AUGMENTING
  -> COVERAGE_READY
  -> HANDED_OFF
```

Recoverable outcomes are `RETRY_SCHEDULED` and `COLLECTION_PARTIAL`. A terminal
technical failure is `FAILED`. Exhausting a query list is not success.

`COVERAGE_READY` is reached only when the coverage contract below is satisfied.
An incomplete bundle is retained for the next acquisition wave, but it does not
silently start perimeter generation.

## Adaptive Web acquisition

### Query waves

The planner produces bounded waves from the canonical target.

1. **Identity and official state**
   - incident name, aliases, municipality, department, and exact local date;
   - official terms such as `communique`, `point de situation`, `prefecture`,
     `SDIS`, `mairie`, and `ONF`;
   - direct inspection of approved feeds, sitemaps, and known official update
     pages when an exact connector exists.
2. **Progression and operations**
   - `progression`, `front`, `secteur`, `hectares`, `evacuation`, `route`,
     `pompiers`, `moyens aeriens`, `fixe`, `maitrise`, and `eteint`;
   - exact-date searches followed by incident-wide chronology searches.
3. **Visual coverage**
   - `photo`, `video`, `drone`, `fumee`, `flammes`, and named sectors extracted
     from already verified claims;
   - regional press and approved public institutional media pages.
4. **Missing-dimension expansion**
   - queries are generated from the coverage report, not from a fixed retry;
   - a missing date, location, active-front observation, video, or official
     confirmation gets its own targeted wave;
   - adjacent-day pages may be inspected, but evidence is assigned to the target
     day only when the content explicitly supports that time.

Broad and domain-targeted queries are both used. Search providers discover
candidates only; a search result is never evidence by itself.

### Page verification

Each candidate page passes all of these checks before becoming a source ticket:

- canonical HTTPS URL and approved publisher policy;
- SSRF and DNS controls on every request and redirect hop;
- bounded response size and timeout;
- supported content type;
- content SHA-256 calculated from the fetched response;
- incident relevance and temporal relevance;
- extraction of publisher, publication/update time, title, JSON-LD and OpenGraph
  metadata when available;
- canonical-URL and content-hash deduplication;
- provenance that links every claim and media ticket to the page revision.

Redirects may be followed only through a small bounded chain when every hop is
HTTPS and independently allowed. Publisher pages and their media CDN hosts have
separate policies; discovering an image on an allowed page does not allow the
worker to fetch an arbitrary host.

### Text and multimodal extraction

The configured evidence provider receives the verified page text and at most
four relevant public images in memory. It emits only structured, attributed
claims such as:

- incident status and lifecycle transition;
- affected-area figure and its unit;
- named location or sector;
- explicit observation time or interval;
- reported progression, resumption, or stable front;
- operational resources, evacuation, closure, damage, and public instruction;
- media description tied to a specific media ticket.

The provider may interpret evidence, detect contradictions, and classify
temporal relevance. It may not generate final GPS coordinates or a perimeter.
Claims without a source ticket and evidence reference are rejected.

## Image collection

The parser inspects OpenGraph, JSON-LD, `picture`, `srcset`, gallery, and ordinary
image references. A public image becomes a media ticket only after a bounded
in-memory fetch confirms:

- decodable image content and declared type agreement;
- byte SHA-256, dimensions, and perceptual hash;
- useful minimum dimensions;
- absence of obvious logos, tracking pixels, avatars, placeholders, and repeated
  thumbnails;
- parent source, canonical media URL, attribution and known reuse policy;
- capture or publication time when available;
- incident and day relevance.

Public image bytes are discarded after extraction and analysis. Downstream
vision may re-fetch an image through the controlled broker by ticket, verify the
same SHA-256, analyze it, and discard it again. A changed object is journaled as
stale evidence rather than silently replacing the ticket.

## Video and audio collection

A video URL counts as one source media item. Its frames do not count as
independent media.

The broker streams or uses a bounded ephemeral file, then:

1. validates container, type, size, duration, and hash;
2. selects frames by scene change, fixed temporal coverage, and detector signal;
3. records keyframe timestamps and parent-video hash;
4. sends keyframes to the visual providers;
5. extracts audio when present and performs transient transcription;
6. converts explicit spoken facts into sourced claim tickets with time offsets;
7. deletes the video, audio, keyframes, and full transcript after the run.

Only claim tickets, keyframe derivation receipts, detections, hashes, timestamps,
URLs, and failure journals persist. A full public transcript is never retained.

## Satellite acquisition

Satellite data uses structured geospatial interfaces, not Web Search.

### Discovery

The official-source scheduler queries the incident AOI and time window through
versioned connectors:

- CDSE STAC for product discovery and immutable product metadata;
- Sentinel-3 FRP products and NASA FIRMS for active thermal observations;
- Sentinel-2 Level-2A for optical change and burned-area analysis;
- Sentinel-1 GRD as an auxiliary cloud-independent observation when a qualified
  downstream method is available;
- EFFIS or CEMS products as separately attributed external observations, never
  as hidden ground truth.

Every observation retains acquisition time, publication time, footprint, CRS,
platform, sensor, product identifier, resolution, quality flags, licence,
attribution, connector revision, and content hash.

### Materialisation

Only products selected for the AOI and analysis window are materialised.
Satellite rasters may be retained under the satellite retention policy.

For the current Prithvi burned-area contract, the materialiser produces a
georeferenced six-band raster with canonical band names:

```text
BLUE, GREEN, RED, NIR_NARROW, SWIR_1, SWIR_2
```

For Sentinel-2 Level-2A these normally map to `B02`, `B03`, `B04`, `B8A`, `B11`,
and `B12`; scene classification and cloud masks are retained as quality inputs,
not silently inserted as model bands. The raster manifest signs its CRS,
geotransform, bounds, dimensions, band order, nodata policy, resampling method,
acquisition time, and SHA-256 before inference.

Thermal points preserve their native footprint and accuracy. They are evidence
of a sensor observation, not exact ground-fire coordinates.

## Deduplication and independence

Deduplication happens at four levels:

- canonical page URL;
- page content SHA-256;
- media byte SHA-256 and perceptual similarity;
- evidence family: publisher, original capture, satellite pass, video, or public
  statement.

Mirrors, syndication, multiple crops, and frames from one video remain one
independent evidence family. Twenty images copied from one press agency are not
twenty independent proofs.

## Coverage contract

The scraper computes coverage after every wave.

### Incident-level documentary target

- at least 20 valid public image or video tickets for the incident collection;
- at least one official or emergency-service source;
- multiple independent publisher or capture families;
- chronological coverage across the documented active episode;
- no unresolved hash, provenance, or temporal-assignment error on admitted
  tickets.

The number 20 measures usable media candidates, not independent proofs. Logos,
duplicates, search-result thumbnails, and derived keyframes do not count.

### Day-level analysis target

A day is ready for spatial analysis when it contains:

- at least one time-qualified observation;
- at least one spatially usable observation: georeferenced satellite data,
  explicit source geometry, or visual evidence with sufficient camera/map/terrain
  references for the geographic stage;
- provenance and uncertainty for every admitted observation;
- no unresolved hard contradiction about incident identity or observation day.

Independent textual reports can make a day useful for the public chronology,
but a hectare figure or place name alone cannot justify a perimeter geometry.

The coverage object exposes counts by source type, media type, day, evidence
family, and spatial capability, plus explicit missing dimensions and the next
query wave. `queries_exhausted` and `coverage_ready` are separate fields.

## Durable output

The scraper emits an `IncidentDayEvidenceBundle` containing references only:

```json
{
  "schema_version": "incident-day-evidence-1.0",
  "research_id": "SR-...",
  "analysis_id": "AN-...",
  "incident_id": "FR-26-00001",
  "local_date": "2026-07-06",
  "sources": [],
  "claims": [],
  "media_tickets": [],
  "satellite_artifacts": [],
  "contradictions": [],
  "coverage": {
    "queries_exhausted": false,
    "incident_media_target": 20,
    "incident_media_count": 0,
    "time_qualified": false,
    "spatially_usable": false,
    "coverage_ready": false,
    "missing_dimensions": []
  },
  "source_registry_revision": "...",
  "bundle_sha256": "..."
}
```

The durable store keeps source and media URLs, hashes, metadata, claims,
derivation receipts, model/provider revisions, contradictions, and acquisition
journals. It does not keep scraped article bodies, public-media binaries, full
transcripts, or model prompts. User media follows its explicit republication
consent. Satellite products and derived perimeter tiles follow their dedicated
retention rules.

## Handoff and evaluation isolation

Only `coverage_ready=true` starts the corresponding spatial-analysis handoff.
Text-only chronology facts can still be published through their own reviewed
path; they are not converted into geometry.

The published/reference perimeter used to score the end-to-end test is loaded
only after the produced daily perimeter package and all hashes are frozen. It is
never exposed to search planning, extraction, vision, geography, supervision,
or deterministic Part.4 construction.

## Operational bounds

- Web acquisition, parsing, hashing, keyframe extraction, and orchestration run
  on scale-to-zero CPU workers.
- Managed text/VL calls require a configured cost gate and provider receipt.
- Satellite discovery uses free structured APIs within their documented quotas;
  raster requests are bounded by AOI, resolution, selected bands, and account
  quota.
- Optional GPU inference remains disabled until its endpoint and cost are
  explicitly authorised.
- Every retry records the missing dimension and changes the acquisition wave;
  repeating the same empty query is not a retry strategy.

## Acceptance checks

A real end-to-end acquisition test must prove:

1. the target was generated automatically from an incident analysis window;
2. no manual candidate, source URL, query plan, or evidence JSON was injected;
3. admitted sources and media can be replayed from their tickets and hashes;
4. at least 20 valid incident media tickets were collected or the run remains
   visibly partial;
5. claims preserve source and temporal references;
6. public raw content and transcripts are absent from durable storage;
7. satellite artifacts carry usable georeferencing and signed band manifests;
8. downstream stages receive only coverage-ready daily bundles;
9. the published perimeter remained inaccessible until prediction freeze;
10. failures and partial provider outputs appear in the acquisition journal.

## Interface references

- [Copernicus Data Space STAC](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)
- [Copernicus Sentinel Hub Process API](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html)
- [Copernicus quotas and limitations](https://documentation.dataspace.copernicus.eu/Quotas.html)
- [NASA FIRMS area API](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
