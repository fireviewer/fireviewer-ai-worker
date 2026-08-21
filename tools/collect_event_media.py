from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_MEDIA_BYTES = 16 * 1024 * 1024
MEDIA_PER_CASE = 20
MEDIA_PER_SOURCE = 8
KEYWORDS = ("incend", "feu", "fum", "fire", "smoke", "flamme", "wildfire")
EXCLUDED_IMAGE_TOKENS = ("logo", "avatar", "icon", "emoji", "pixel", "tracking", "favicon")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.candidates: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content")
            if key and content:
                self.metadata.setdefault(key, content)
                if key in {"og:image", "twitter:image", "twitter:image:src"}:
                    self.candidates.append((0, content))
        elif tag == "video" and values.get("poster"):
            self.candidates.append((1, values["poster"]))
        elif tag == "img":
            source = (
                values.get("data-src")
                or values.get("data-lazy-src")
                or values.get("data-original")
                or values.get("src")
            )
            if source is None and values.get("srcset"):
                source = values["srcset"].split(",")[-1].strip().split(" ")[0]
            if source:
                searchable = f"{values.get('alt', '')} {values.get('title', '')} {source}".lower()
                if not any(token in searchable for token in EXCLUDED_IMAGE_TOKENS):
                    priority = 2 if any(keyword in searchable for keyword in KEYWORDS) else 3
                    self.candidates.append((priority, source))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect event-media candidates from research pages."
    )
    parser.add_argument("seeds", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument(
        "--media-per-case",
        type=int,
        default=MEDIA_PER_CASE,
        choices=range(1, 101),
    )
    parser.add_argument(
        "--media-per-source",
        type=int,
        default=MEDIA_PER_SOURCE,
        choices=range(1, 101),
    )
    return parser.parse_args()


def _validate_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("collection URLs must be plain HTTPS URLs")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("collection URL cannot target localhost")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("collection URL host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("collection URL resolved to a non-public address")


def _request(url: str, *, accept: str, max_bytes: int) -> tuple[bytes, str, str]:
    _validate_public_https(url)
    request = Request(  # noqa: S310 - scheme, credentials and public DNS validated above
        url,
        headers={
            "Accept": accept,
            "User-Agent": "Mozilla/5.0 FireViewerBenchmark/0.1",
            "Referer": f"{urlsplit(url).scheme}://{urlsplit(url).netloc}/",
        },
    )
    with urlopen(request, timeout=45) as response:  # noqa: S310 - URL validated above
        final_url = response.geturl()
        _validate_public_https(final_url)
        content_type = response.headers.get_content_type()
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("response exceeded its configured byte cap")
    return content, final_url, content_type


def _page(url: str) -> tuple[bytes, str, _PageParser]:
    content, final_url, content_type = _request(
        url,
        accept="text/html,application/xhtml+xml",
        max_bytes=MAX_PAGE_BYTES,
    )
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise ValueError(f"research page returned unsupported content type {content_type}")
    parser = _PageParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    return content, final_url, parser


def _media(url: str) -> tuple[bytes, str, str, tuple[int, int]]:
    content, final_url, content_type = _request(
        url,
        accept="image/avif,image/webp,image/png,image/jpeg",
        max_bytes=MAX_MEDIA_BYTES,
    )
    if content_type not in {"image/avif", "image/webp", "image/png", "image/jpeg"}:
        raise ValueError(f"media candidate returned unsupported content type {content_type}")
    with Image.open(BytesIO(content)) as image:
        image.verify()
        size = image.size
    if size[0] < 320 or size[1] < 180:
        raise ValueError("media candidate is below the minimum useful dimensions")
    return content, final_url, content_type, size


def _extension(content_type: str) -> str:
    return {
        "image/avif": ".avif",
        "image/webp": ".webp",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }[content_type]


def main() -> int:
    args = _arguments()
    seeds = json.loads(args.seeds.read_text(encoding="utf-8"))
    if seeds.get("schema") != "fireviewer.event-media-research-seeds.v1":
        raise ValueError("unexpected event-media seed schema")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, object]] = []
    for raw_case in seeds["cases"]:
        case_id = str(raw_case["case_id"])
        case_dir = (root / case_id).resolve()
        if root not in case_dir.parents:
            raise ValueError("case output leaves the configured root")
        case_dir.mkdir(parents=True, exist_ok=True)
        sources: list[dict[str, object]] = []
        media: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        known_media_hashes: set[str] = set()
        for page_url in raw_case["pages"]:
            try:
                page_bytes, final_page_url, parser = _page(str(page_url))
            except Exception as exc:
                errors.append(
                    {"url": str(page_url), "stage": "page", "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            source_id = f"source-{hashlib.sha256(final_page_url.encode()).hexdigest()[:16]}"
            sources.append(
                {
                    "source_id": source_id,
                    "requested_url": page_url,
                    "final_url": final_page_url,
                    "content_sha256": hashlib.sha256(page_bytes).hexdigest(),
                    "title": parser.metadata.get("og:title"),
                    "description": parser.metadata.get("og:description")
                    or parser.metadata.get("description"),
                    "published_at": parser.metadata.get("article:published_time"),
                }
            )
            ordered_candidates = sorted(
                enumerate(parser.candidates), key=lambda item: (item[1][0], item[0])
            )
            source_media_count = 0
            for _, (_, candidate) in ordered_candidates:
                if len(media) >= args.media_per_case or source_media_count >= args.media_per_source:
                    break
                media_url = urljoin(final_page_url, candidate)
                try:
                    content, final_media_url, content_type, dimensions = _media(media_url)
                except Exception as exc:
                    errors.append(
                        {
                            "url": media_url,
                            "stage": "media",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                digest = hashlib.sha256(content).hexdigest()
                if digest in known_media_hashes:
                    continue
                known_media_hashes.add(digest)
                target = case_dir / f"{len(media) + 1:02d}-{digest[:16]}{_extension(content_type)}"
                target.write_bytes(content)
                media.append(
                    {
                        "media_id": f"media-{digest[:20]}",
                        "source_id": source_id,
                        "source_page_url": final_page_url,
                        "media_url": final_media_url,
                        "relative_path": target.relative_to(root).as_posix(),
                        "sha256": digest,
                        "size_bytes": len(content),
                        "content_type": content_type,
                        "width": dimensions[0],
                        "height": dimensions[1],
                        "review_status": "not_reviewed",
                        "rights_status": "not_checked_internal_benchmark",
                    }
                )
                source_media_count += 1
        case_results.append(
            {
                "case_id": case_id,
                "source_count": len(sources),
                "media_count": len(media),
                "sources": sources,
                "media": media,
                "errors": errors,
            }
        )
    receipt = {
        "schema": "fireviewer.event-media-research-receipt.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds_sha256": hashlib.sha256(args.seeds.read_bytes()).hexdigest(),
        "media_per_case_cap": args.media_per_case,
        "media_per_source_cap": args.media_per_source,
        "cases": case_results,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
