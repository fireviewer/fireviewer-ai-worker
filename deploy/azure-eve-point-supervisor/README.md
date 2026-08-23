# FireViewer Eve point supervisor on Azure CPU

This Container App runs Eve on the public container port and a loopback-only Python supervision
API. Eve can only search the durable `EventEvidence` memory and ask the Python service to assess
one existing deterministic point. It cannot create maps, perimeters, polygons or source GPS
coordinates.

The managed VL provider is the active EU Bedrock inference profile
`eu.mistral.pixtral-large-2502-v1:0`. Azure uses the dedicated managed identity
`id-fireviewer-eve-bedrock` and AWS role `fireviewer-eve-pixtral`; no static AWS credential is
stored. The IAM policy permits only `bedrock:InvokeModel` for the exact inference profile and its
pinned Pixtral foundation-model routes.

The first deployment keeps `FIREVIEWER_POINT_PUBLICATION_ENABLED=false`. A managed assessment is
therefore returned as `held_for_review` until a calibrated confidence exists and the backend
publication gates are enabled. A simulated assessment is structurally ineligible regardless of
its score.

Provision or update the cross-cloud role after the Azure identity exists:

```powershell
.\deploy\azure-eve-point-supervisor\provision-bedrock-role.ps1
```

The script never invokes Bedrock and cannot create or start a GPU endpoint.
