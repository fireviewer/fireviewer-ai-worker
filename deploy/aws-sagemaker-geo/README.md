# FireViewer Geo GPU on SageMaker

This deployment is independent from the Part.1 map-builder resources. It owns a
dedicated private ECR repository, S3 bucket and least-privilege SageMaker
execution role for the MegaLoc/Prithvi inference image.

Provision the non-compute resources from PowerShell:

```powershell
.\deploy\aws-sagemaker-geo\provision.ps1
```

Provisioning does not call `CreateEndpoint` and cannot start a billable GPU.
The future asynchronous endpoint is prepared separately and must retain
`MinCapacity=0`, `MaxCapacity=1`. Its first `ml.g4dn.2xlarge` start is a single,
explicitly authorized smoke test.

After the Azure geo CPU identity exists, provision its separate cross-cloud role:

```powershell
.\deploy\aws-sagemaker-geo\provision-async-invoker-role.ps1
```

This role is federated only to `id-fireviewer-geo-cpu`. It can upload under
`async/input/`, invoke one exact Async endpoint revision, and read only its
`async/output/` and `async/failure/` objects. It cannot create, update or invoke
another endpoint.

The deployment sequence is:

1. `provision.ps1`: ECR, S3 and the isolated SageMaker role only.
2. `build-and-push.ps1`: push the already tested local image under an immutable tag.
3. `publish-model.ps1`: verify the immutable ECR digest, upload the
   digest-qualified model archive, create a SageMaker Model that references the
   image by digest and an Async endpoint configuration, but no endpoint.
4. `activate-paid-smoke.ps1 -AuthorizePaidSmoke`: the only script allowed to call
   `CreateEndpoint`; it immediately registers `MinCapacity=0`, `MaxCapacity=1`
   and queues exactly one named smoke request.

Build the single-platform SageMaker image with provenance attestations disabled
so the ECR tag resolves directly to an amd64 image manifest:

```powershell
docker build --platform linux/amd64 --provenance=false --file Dockerfile.sagemaker-geo --tag fireviewer-geo-gpu:local .
```

Before an immutable ECR push, run the complete local vulnerability gate without
enabling paid Amazon Inspector scanning:

```powershell
docker scout cves --format sarif --output fireviewer-geo.sarif.json local://fireviewer-geo-gpu:local
docker scout cves --format markdown --output fireviewer-geo.md local://fireviewer-geo-gpu:local
```

The runtime image intentionally removes `pip`, `setuptools`, `wheel` and Ubuntu
development headers after the dependency check. Reintroducing build tools into
the final layer requires a new scan. Remaining Torch/CUDA findings must be
handled through a separately qualified base-image upgrade, not an in-place
runtime package replacement.
