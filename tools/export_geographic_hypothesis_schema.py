from __future__ import annotations

import json
from pathlib import Path

from firewarning_worker.mvp.contracts import GeographicHypothesisResultV1

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "contracts"
    / "geographic-hypotheses"
    / "v1"
    / "geographic-hypotheses.schema.json"
)


def rendered_schema() -> str:
    return (
        json.dumps(
            GeographicHypothesisResultV1.model_json_schema(
                by_alias=True,
                mode="serialization",
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered_schema(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
