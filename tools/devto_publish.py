#!/usr/bin/env python3
"""Publish one reviewed technical DEV.to article, idempotently and fail-closed.

No external dependencies. Production API host is fixed; credentials come from
DEVTO_API_KEY and must never be committed to a repository or printed.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY_URL = "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE"
DEFAULT_MANIFEST = "docs/devto/cpu-rendering-evidence.json"
DEVTO_API_BASE = "https://dev.to/api"
REPO_ROOT = Path(__file__).resolve().parents[1]


class DevtoError(Exception):
    """Safe-to-print publisher failure without request secrets."""


def load_article(manifest_path, repo_root=REPO_ROOT):
    """Validate article metadata and source. Reject frontmatter overrides."""
    root = Path(repo_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(root / "docs/devto") or manifest_path.suffix != ".json":
        raise DevtoError("Manifest must be a JSON file inside docs/devto")
    try:
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise DevtoError("Cannot read valid JSON metadata") from None
    if not isinstance(metadata, dict) or set(metadata) != {
        "title", "description", "tags", "markdown_file"
    }:
        raise DevtoError("Manifest must contain title, description, tags and markdown_file only")

    title = metadata["title"]
    description = metadata["description"]
    tags = metadata["tags"]
    relative = metadata["markdown_file"]
    if not isinstance(title, str) or not (20 <= len(title.strip()) <= 120):
        raise DevtoError("Title must contain 20-120 characters")
    if not isinstance(description, str) or not (30 <= len(description.strip()) <= 160):
        raise DevtoError("Description must contain 30-160 characters")
    if (not isinstance(tags, list) or not (1 <= len(tags) <= 4)
            or any(not isinstance(tag, str) or re.fullmatch(r"[a-z0-9]+", tag) is None
                   for tag in tags) or len(set(tags)) != len(tags)):
        raise DevtoError("Tags must be 1-4 distinct lowercase alphanumeric values")
    if not isinstance(relative, str) or re.fullmatch(r"docs/devto/[a-z0-9-]+\.md", relative) is None:
        raise DevtoError("Article must be a Markdown file directly inside docs/devto")
    source = (root / relative).resolve()
    if not source.is_relative_to(root / "docs/devto"):
        raise DevtoError("Markdown source escapes docs/devto")
    try:
        body = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise DevtoError("Markdown source could not be read") from None
    if len(body.strip()) < 1000:
        raise DevtoError("Article must contain at least 1000 characters of substantive content")
    if body.lstrip("\ufeff\n\r \t").startswith("---"):
        raise DevtoError("Markdown frontmatter could override publication safety settings")
    return {
        "title": title.strip(), "description": description.strip(),
        "tags": ",".join(tags), "body_markdown": body,
        "canonical_url": f"{REPOSITORY_URL}/blob/main/{relative}",
    }


def request_json(method, endpoint, token, payload=None, api_base=DEVTO_API_BASE):
    headers = {"api-key": token, "Accept": "application/vnd.forem.api-v1+json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps({"article": payload}).encode("utf-8")
    request = Request(api_base + endpoint, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Never log request objects, response bodies or authorization headers.
        raise DevtoError(f"DEV.to API rejected request (HTTP {exc.code})") from None
    except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
        raise DevtoError("DEV.to API request or response failed") from None
    return result


def check_auth(token, api_base=DEVTO_API_BASE):
    """Read-only authenticated probe. Never logs secret, article bodies, or user data."""
    token = token.strip() if isinstance(token, str) else ""
    if not token:
        raise DevtoError("DEVTO_API_KEY is missing; configure a GitHub Actions secret")
    found = request_json("GET", "/articles/me/all?per_page=1&page=1", token,
                         api_base=api_base)
    if not isinstance(found, list):
        raise DevtoError("Unexpected DEV.to article list response")
    return True


def publication_state(item):
    """Resolve state from Forem's list representation, or block unsafe PUT."""
    explicit = item.get("published")
    has_date = "published_at" in item
    date = item.get("published_at")
    if explicit is not None and type(explicit) is not bool:
        raise DevtoError("Invalid DEV.to publication state; refusing update")
    if has_date and date is not None and (not isinstance(date, str) or not date.strip()):
        raise DevtoError("Invalid DEV.to publication timestamp; refusing update")
    dated = (date is not None) if has_date else None
    if explicit is None and dated is None:
        raise DevtoError("Missing DEV.to publication state; refusing update")
    if explicit is not None and dated is not None and explicit != dated:
        raise DevtoError("Inconsistent DEV.to publication state; refusing update")
    return explicit if explicit is not None else dated


def sync_article(manifest_path, token, publish=False, repo_root=REPO_ROOT,
                 api_base=DEVTO_API_BASE):
    article = load_article(manifest_path, repo_root=repo_root)
    token = token.strip() if isinstance(token, str) else ""
    if not token:
        raise DevtoError("DEVTO_API_KEY is missing; configure a GitHub Actions secret")

    matches = []
    # Scan all relevant pages before creating; duplicates are not safe to guess.
    for page in range(1, 11):
        found = request_json("GET", f"/articles/me/all?per_page=100&page={page}",
                             token, api_base=api_base)
        if not isinstance(found, list) or len(found) > 100:
            raise DevtoError("Unexpected DEV.to article list response")
        matches.extend(item for item in found
                       if isinstance(item, dict)
                       and item.get("canonical_url") == article["canonical_url"])
        if len(found) < 100:
            break
    else:
        raise DevtoError("Article search exceeded safe pagination limit")

    if len(matches) > 1:
        raise DevtoError("Multiple articles have the same canonical URL; refusing update")

    existing = matches[0] if matches else None
    article["published"] = bool(publish or (existing and publication_state(existing)))
    if existing:
        article_id = existing.get("id")
        if type(article_id) is not int or article_id < 1:
            raise DevtoError("DEV.to article identity is invalid")
        result = request_json("PUT", f"/articles/{article_id}", token, article,
                              api_base=api_base)
        operation = "updated"
    else:
        result = request_json("POST", "/articles", token, article,
                              api_base=api_base)
        operation = "created"
    if not isinstance(result, dict) or type(result.get("id")) is not int:
        raise DevtoError("DEV.to did not confirm an article ID")
    url = result.get("url")
    if url is not None and (not isinstance(url, str) or not url.startswith("https://dev.to/")):
        raise DevtoError("DEV.to returned an unexpected article URL")
    return {"operation": operation, "id": result["id"],
            "url": url, "published": article["published"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--check", action="store_true", help="Validate offline, without credentials")
    parser.add_argument("--auth-check", action="store_true",
                        help="Verify API credentials via read-only GET without publication")
    parser.add_argument("--publish", action="store_true", help="Explicitly publish publicly")
    args = parser.parse_args(argv)
    try:
        if sum((args.check, args.auth_check, args.publish)) > 1:
            raise DevtoError("--check, --auth-check and --publish are mutually exclusive")
        if args.check:
            load_article(args.manifest)
            print("DEVTO_VALIDATION_OK")
            return 0
        if args.auth_check:
            check_auth(os.environ.get("DEVTO_API_KEY", ""))
            print("DEVTO_AUTH_OK")
            return 0
        result = sync_article(args.manifest, token=os.environ.get("DEVTO_API_KEY", ""),
                              publish=args.publish)
        if result["operation"] == "skipped":
            print("DEVTO_SKIPPED: DEV.to sync skipped (not publishing)")
            return 0
        print(f"DEVTO_{result['operation'].upper()} id={result['id']} published={result['published']}")
        if result["url"]:
            print(f"Article: {result['url']}")
        return 0
    except DevtoError as exc:
        print(f"DEVTO_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
