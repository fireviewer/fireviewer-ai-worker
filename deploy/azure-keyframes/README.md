# FireViewer CPU keyframe worker

`Dockerfile.keyframes-cpu` builds a non-root Linux CPU service around
`OpenCvVideoFrameDecoder` and `VideoKeyframeExtractor`.

The build is an acceptance gate, not just an import check. Its test stage installs
`opencv-python-headless==4.13.0.92`, imports OpenCV, writes a real MJPG video, reopens it, samples
the expected frames and verifies the input SHA-256. The final stage cannot build unless that test
stage produced its success marker.

The service exposes:

- `GET /healthz`;
- authenticated `POST /v1/event-evidence/keyframes` with only `{"candidate_id":"EC-..."}`.

It reads retained user videos from backend `EventEvidence`, downloads them to an isolated
temporary directory, checks their SHA-256, emits 5 to 15 scene-aware keyframe tickets and deletes
all temporary frame bytes at the end of the request.

The image is ready but is not deployed. The current backend has no durable derived-keyframe sink,
so the service deliberately reports `requires_durable_sink_before_yolo=true` and does not pretend
that YOLO can consume unpublished keyframe identifiers. That sink must be added before wiring this
service to the existing YOLO CPU Container App.
