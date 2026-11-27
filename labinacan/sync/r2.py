"""Delta-sync a built ``dist/`` directory to a Cloudflare R2 bucket over the S3 API.

Only files whose MD5 differs from the remote ETag are uploaded (``put_object``
always produces single-part uploads, whose ETag is the content MD5). Because the
builder is deterministic, an unchanged site syncs as a no-op: nothing is
uploaded, deleted or purged.

* Upload order: content-addressed files, then other assets, then HTML, so a page
  never references an object that has not landed yet.
* Derived prefixes (``pagefind/``) are only synced when a source file changed. The
  Pagefind index is not byte-stable across runs, so syncing it alone would churn.
* Protected prefixes (``data/snapshots/``) are never deleted: snapshot URLs are
  permanent.
* With a Cloudflare zone configured, only changed short-cache URLs are purged. Past
  :data:`PURGE_ALL_ABOVE` of them, one request purges the whole zone instead.
* Uploads go through boto3, or through rclone when it is installed
  (:func:`rclone_uploader`). rclone moves many small files faster.

Credentials come from ``CF_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID`` and
``R2_SECRET_ACCESS_KEY``; purging uses ``CF_ZONE_ID`` and ``CF_API_TOKEN``.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from labinacan.config import env
from labinacan.errors import SyncError

SHORT_CACHE = "public, max-age=3600"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
DERIVED_PREFIXES = ("pagefind/",)
PROTECTED_PREFIXES = ("data/snapshots/",)
PURGE_BATCH = 30  # Cloudflare's per-request limit for purge-by-URL
# Past this many URLs, one purge of the whole zone replaces the batches: a change to every
# page would need thousands of requests, and Cloudflare limits how fast they may come.
PURGE_ALL_ABOVE = 3000

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".parquet": "application/vnd.apache.parquet",
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
}
# Pagefind's index shards are content-addressed. Its entry files are not, so they must
# stay on the short cache: pagefind.js, pagefind-entry.json and pagefind-ui.*.
HASHED_NAME = re.compile(r"[_.-][0-9a-f]{7,}\.[A-Za-z0-9_]+$")
PAGEFIND_SHARD_SUFFIXES = {".pf_fragment", ".pf_index", ".pf_filter", ".pf_meta", ".pagefind"}


def cache_control_for(key: str) -> str:
    """Cache policy: immutable only for content-addressed files, one hour for everything else."""
    path = PurePosixPath(key)
    if key.startswith("data/snapshots/") or path.suffix in PAGEFIND_SHARD_SUFFIXES:
        return IMMUTABLE_CACHE
    if path.suffix not in {".html", ".json"} and HASHED_NAME.search(path.name):
        return IMMUTABLE_CACHE
    return SHORT_CACHE


def content_type_for(key: str) -> str:
    """The Content-Type to upload ``key`` with, from its suffix."""
    suffix = PurePosixPath(key).suffix
    return CONTENT_TYPES.get(suffix) or mimetypes.guess_type(key)[0] or "application/octet-stream"


def file_md5(path: Path) -> str:
    """The MD5 of ``path``, which equals a single-part upload's ETag."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class R2Config:
    """The R2 account and credentials to sync with."""

    account_id: str
    access_key_id: str
    secret_access_key: str

    @property
    def endpoint_url(self) -> str:
        """The account's S3 API endpoint."""
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> R2Config:
        """Read the config from the environment; raise SyncError when a variable is missing."""
        names = ("CF_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
        missing = [n for n in names if not env.get(n)]
        if missing:
            raise SyncError(f"Missing environment variables: {', '.join(missing)}")
        return cls(*(env[n] for n in names))


# A slow R2 response once failed a deploy: DeleteObjects of up to 1,000 keys passed boto's
# 60 s read timeout (#6101). Standard retries also retry a timeout.
READ_TIMEOUT_S = 300
MAX_ATTEMPTS = 6  # the first try and 5 retries


def make_client(config: R2Config) -> Any:
    """An S3 client for R2, made with ``config``, that waits and retries on a slow response."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
        config=Config(
            read_timeout=READ_TIMEOUT_S,
            retries={"mode": "standard", "total_max_attempts": MAX_ATTEMPTS},
            # botocore keeps 10 connections by default, so most upload threads would wait.
            max_pool_connections=max(10, UPLOAD_WORKERS),
        ),
    )


@dataclass
class SyncPlan:
    """What a sync uploads, deletes, leaves alone and skips."""

    uploads: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped_derived: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """True when the sync uploads or deletes anything."""
        return bool(self.uploads or self.deletes)


def local_files(dist_dir: Path, prefix: str = "") -> dict[str, Path]:
    """Every file in ``dist_dir`` by its bucket key, except dotfiles."""
    dist_dir = Path(dist_dir)
    return {
        prefix + path.relative_to(dist_dir).as_posix(): path
        for path in sorted(dist_dir.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    }


def remote_etags(client: Any, bucket: str, prefix: str = "") -> dict[str, str]:
    """The ETag of every object in ``bucket`` under ``prefix``, by key."""
    etags: dict[str, str] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            etags[obj["Key"]] = obj["ETag"].strip('"')
    return etags


def _upload_order(key: str) -> tuple[int, str]:
    if key.endswith(".html"):
        return (2, key)
    return (0 if cache_control_for(key) == IMMUTABLE_CACHE else 1, key)


def plan_sync(
    local: Mapping[str, Path],
    remote: Mapping[str, str],
    *,
    delete: bool = False,
    prefix: str = "",
    derived: Sequence[str] = DERIVED_PREFIXES,
    protected: Sequence[str] = PROTECTED_PREFIXES,
) -> SyncPlan:
    """Compare local files with the bucket, and decide what to upload and delete.

    The module docstring gives the rules.
    """
    plan = SyncPlan()

    def rel(key: str) -> str:
        return key.removeprefix(prefix)

    for key, path in local.items():
        (plan.unchanged if remote.get(key) == file_md5(path) else plan.uploads).append(key)
    if delete:
        plan.deletes = sorted(
            k for k in set(remote) - set(local) if not rel(k).startswith(tuple(protected))
        )

    # Derived files only follow a change to a source file; on their own they are churn.
    is_derived = lambda k: rel(k).startswith(tuple(derived))  # noqa: E731
    if not any(not is_derived(k) for k in plan.uploads + plan.deletes):
        plan.skipped_derived = sorted(plan.uploads + plan.deletes)
        plan.unchanged += plan.uploads
        plan.uploads, plan.deletes = [], []

    plan.uploads.sort(key=lambda k: _upload_order(rel(k)))
    return plan


UPLOAD_WORKERS = int(os.environ.get(env("UPLOAD_WORKERS"), "64"))
"""Uploads in flight at once (``$<prefix>_UPLOAD_WORKERS``, :func:`labinacan.config.env`)."""


def _upload(client, bucket: str, local: Mapping[str, Path], keys: Sequence[str], prefix: str):
    """Upload ``keys`` in parallel, in :func:`_upload_order`'s groups, one group at a time.

    One request at a time took about 8 minutes for a deploy, and much longer when every
    page changed. A boto3 client is safe to share between threads. Every asset finishes
    before the first page starts, so no page links a file that isn't there yet.
    """
    from concurrent.futures import ThreadPoolExecutor
    from itertools import groupby

    def put(key: str) -> None:
        with local[key].open("rb") as body:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type_for(key),
                CacheControl=cache_control_for(key.removeprefix(prefix)),
            )

    rank = lambda key: _upload_order(key.removeprefix(prefix))[0]  # noqa: E731
    with ThreadPoolExecutor(max_workers=max(1, UPLOAD_WORKERS)) as pool:
        for _, group in groupby(keys, key=rank):
            list(pool.map(put, group))  # waits for the group, and raises its first error


def rclone_uploader(
    config: R2Config, rclone: str = "rclone", run: Callable[..., Any] = subprocess.run
) -> Callable[..., None]:
    """An uploader for :func:`sync_directory` that copies the files with rclone.

    The files go in :func:`_upload_order`'s groups, so every asset lands before the first
    page. Within a group, one rclone run copies the files that share a Cache-Control and a
    Content-Type. Each file goes up in one part, so its ETag stays its MD5, as
    :func:`plan_sync` compares. The credentials reach rclone in its environment, never on
    its command line.

    Args:
        config: The R2 account and credentials.
        rclone: The rclone program.
        run: Runs a command (a parameter so that tests can replace it).

    Returns:
        The uploader.
    """
    from itertools import groupby

    secrets = {
        "RCLONE_S3_PROVIDER": "Cloudflare",
        "RCLONE_S3_ENDPOINT": config.endpoint_url,
        "RCLONE_S3_ACCESS_KEY_ID": config.access_key_id,
        "RCLONE_S3_SECRET_ACCESS_KEY": config.secret_access_key,
    }

    def upload(
        dist_dir: Path,
        bucket: str,
        _local: Mapping[str, Path],  # the boto uploader's argument; rclone reads dist_dir
 keys: Sequence[str],
               prefix: str) -> None:  # fmt: skip
        def headers(key: str) -> tuple[int, str, str]:
            rel = key.removeprefix(prefix)
            return _upload_order(rel)[0], cache_control_for(rel), content_type_for(rel)

        dest = f":s3:{bucket}/{prefix}".rstrip("/")
        for (_, cache, kind), group in groupby(sorted(keys, key=headers), key=headers):
            paths = [key.removeprefix(prefix) for key in group]
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
                listing.write("\n".join(paths) + "\n")
            try:
                done = run(
                    [rclone, "copy", str(dist_dir), dest, "--files-from-raw", listing.name,
                     "--no-check-dest", "--s3-no-check-bucket", "--s3-upload-cutoff", "5Gi",
                     "--transfers", str(UPLOAD_WORKERS), "--checkers", str(UPLOAD_WORKERS),
                     "--retries", str(MAX_ATTEMPTS), "--header-upload", f"Cache-Control: {cache}",
                     "--header-upload", f"Content-Type: {kind}"],
                    env={**os.environ, **secrets},
                    check=False,
                )  # fmt: skip
            finally:
                os.unlink(listing.name)
            if done.returncode != 0:
                raise SyncError(f"rclone could not upload {len(paths)} files ({kind}, {cache})")

    return upload


def sync_directory(
    dist_dir: Path,
    bucket: str,
    client: Any,
    *,
    prefix: str = "",
    delete: bool = False,
    dry_run: bool = False,
    log: Callable[[str], None] = lambda _msg: None,
    uploader: Callable[..., None] | None = None,
) -> SyncPlan:
    """Sync ``dist_dir`` to ``bucket``; with ``dry_run``, only log what would change.

    ``uploader(dist_dir, bucket, local, keys, prefix)`` uploads the changed files, for
    example :func:`rclone_uploader`'s. By default, ``client`` uploads them.
    """
    dist_dir = Path(dist_dir)
    if not dist_dir.is_dir():
        raise SyncError(f"{dist_dir} is not a directory; build the site first")
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    local = local_files(dist_dir, prefix)
    try:
        plan = plan_sync(local, remote_etags(client, bucket, prefix), delete=delete, prefix=prefix)
        for key in plan.skipped_derived:
            log(f"skip    {key}  (derived; no source file changed)")
        for key in plan.uploads:
            log(f"upload  {key}  [{cache_control_for(key.removeprefix(prefix))}]")
        if not dry_run and uploader is not None:
            uploader(dist_dir, bucket, local, plan.uploads, prefix)
        elif not dry_run:
            _upload(client, bucket, local, plan.uploads, prefix)
        for start in range(0, len(plan.deletes), 1000):  # DeleteObjects takes <= 1000 keys
            batch = plan.deletes[start : start + 1000]
            for key in batch:
                log(f"delete  {key}")
            if not dry_run:
                client.delete_objects(
                    Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True}
                )
    except SyncError:
        raise
    except Exception as exc:  # botocore raises ClientError, EndpointConnectionError, ...
        raise SyncError(f"Sync to bucket {bucket!r} failed: {exc}") from exc
    return plan


def purge_targets(plan: SyncPlan, site_url: str, prefix: str = "") -> list[str]:
    """Public URLs whose cached copies are stale after ``plan`` ran.

    Content-addressed (immutable) objects get new names when they change, so only
    short-cache objects need purging.
    """
    base = site_url.rstrip("/") + "/"
    urls = []
    for key in plan.uploads + plan.deletes:
        rel = key.removeprefix(prefix.rstrip("/") + "/" if prefix else "")
        if cache_control_for(rel) == IMMUTABLE_CACHE:
            continue
        urls.append(base + rel)
        if rel == "index.html" or rel.endswith("/index.html"):
            urls.append(base + rel.removesuffix("index.html"))
    return urls


def purge_cloudflare_cache(
    zone_id: str,
    api_token: str,
    urls: Sequence[str],
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,  # noqa: S310  (Cloudflare's https API)
) -> None:
    """Purge ``urls`` from Cloudflare's edge cache (no-op for an empty list).

    Past :data:`PURGE_ALL_ABOVE` URLs, one request purges the whole zone.
    """
    if len(urls) > PURGE_ALL_ABOVE:
        payloads = [{"purge_everything": True}]
    else:
        payloads = [
            {"files": list(urls[i : i + PURGE_BATCH])} for i in range(0, len(urls), PURGE_BATCH)
        ]
    for payload in payloads:
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener(request, timeout=30) as response:
                body = json.load(response)
        except Exception as exc:
            raise SyncError(f"Cloudflare cache purge failed: {exc}") from exc
        if not body.get("success"):
            raise SyncError(f"Cloudflare cache purge failed: {body.get('errors')}")
