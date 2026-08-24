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
temporary directory, checks their SHA-256 and selects 5 to 15 scene-aware keyframes. Every PNG is
then written to the backend's immutable derived-keyframe sink before the worker returns. Temporary
video and frame bytes are deleted at the end of the request.

Each successful write advances the `EventEvidence` revision. Retries regenerate deterministic
keyframe identifiers and replay the same writes safely. The next YOLO CPU stage reads the persisted
keyframes through the normal backend snapshot and never relies on worker-local files.
