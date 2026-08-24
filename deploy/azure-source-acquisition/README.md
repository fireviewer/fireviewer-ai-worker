# FireViewer source acquisition CPU worker

The worker performs bounded HTTPS search, pagination, URL/SHA deduplication and direct
page-by-page publication to backend `EventEvidence`. It accepts either a real event candidate or
an immutable incident-day analysis window. Queries and domain policies are built automatically
from that durable target; callers cannot submit a manual acquisition plan.

Production collection has no fixed media-count target. It continues in evidence-gap waves until
the incident lifecycle, temporal coverage, source independence and visual/satellite dimensions
converge, or until an explicit safety ceiling is reached. The historic 20-media corpus remains a
local benchmark convention only.

Public page text and up to four public images may be sent transiently to the configured
`MultimodalEvidenceProvider`. The first provider is Pixtral Large on Amazon Bedrock through the
provider-neutral Converse API. Azure Container Apps obtains short-lived AWS credentials by
exchanging its dedicated managed-identity token with AWS STS. No static AWS key is stored.

Retention is fail-closed:

- no scraped HTML or article body is persisted;
- no transcript is persisted;
- no public media binary is persisted;
- source and media tickets retain URL, publisher, timestamps, hashes and provenance;
- failures and partial or missing results use the durable journal;
- satellite binaries, perimeter tiles and explicitly republishable user media remain separate.

## Deployment contract

Deploy the worker behind internal TLS ingress with scale-to-zero enabled. Use a dedicated Azure
managed identity and an AWS role restricted to the selected inference profile; never store a
static AWS credential in the app configuration. Keep `FIREVIEWER_MULTIMODAL_ENABLED=false` until
the first paid inference is explicitly authorized. This permits health, durable candidate reads,
automatic planning and the Azure-to-AWS STS exchange to be checked without invoking the model.

The event-candidate endpoint is `POST /v1/event-evidence/research`:

```json
{"candidate_id":"EC-..."}
```

The incident-day endpoint is `POST /v1/incident-day/research`:

```json
{"analysis_id":"AN-..."}
```

The backend checksum is the precondition for each durable research page. The generated plan is
stable across retries, resumes from the `next_cursor` stored in `EventEvidence`, and replays the
same `page_id` idempotently.
