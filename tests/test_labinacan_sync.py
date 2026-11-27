"""labinacan's sync to R2: keys under a prefix, cache rules, deletes and their batches (#6628)."""

from labinacan.sync.r2 import IMMUTABLE_CACHE, SHORT_CACHE, file_md5, sync_directory


class FakeR2:
    """A bucket that records each list, upload and delete."""

    def __init__(self, remote):
        self.remote, self.calls = remote, []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):  # noqa: N803 (boto3's names)
        self.calls.append(("list", Bucket, Prefix))
        return [{"Contents": [{"Key": k, "ETag": f'"{e}"'} for k, e in self.remote.items()]}]

    def put_object(self, **kw):
        self.calls.append(("put", kw["Bucket"], kw["Key"], kw["CacheControl"]))

    def delete_objects(self, **kw):
        self.calls.append(("delete", kw["Bucket"], kw["Delete"]))


def _site(tmp_path):
    site = tmp_path / "dist"
    (site / "data" / "snapshots").mkdir(parents=True)
    (site / "index.html").write_text("home")
    (site / "data" / "snapshots" / "r.parquet").write_text("rows")
    return site


def _unchanged(site):
    """The bucket's ETags for the site's two files as they are: nothing to upload."""
    snapshot = site / "data" / "snapshots" / "r.parquet"
    return {
        "index.html": file_md5(site / "index.html"),
        "data/snapshots/r.parquet": file_md5(snapshot),
    }


def test_a_prefix_gets_its_slash_and_each_key_its_cache_rule(tmp_path):
    site, logged = _site(tmp_path), []
    remote = {"p/old.html": "0", "p/data/snapshots/old.parquet": "0"}  # the second is protected
    client = FakeR2(remote)
    plan = sync_directory(site, "b", client, prefix="p", delete=True, log=logged.append)
    assert client.calls[0] == ("list", "b", "p/")
    assert logged == [
        f"upload  p/data/snapshots/r.parquet  [{IMMUTABLE_CACHE}]",
        f"upload  p/index.html  [{SHORT_CACHE}]",
        "delete  p/old.html",
    ]
    assert client.calls[1:] == [
        ("put", "b", "p/data/snapshots/r.parquet", IMMUTABLE_CACHE),
        ("put", "b", "p/index.html", SHORT_CACHE),
        ("delete", "b", {"Objects": [{"Key": "p/old.html"}], "Quiet": True}),
    ]
    assert plan.deletes == ["p/old.html"]


def test_a_dry_run_logs_and_changes_nothing(tmp_path):
    client = FakeR2({"old.html": "0"})
    sync_directory(_site(tmp_path), "b", client, delete=True, dry_run=True)
    assert [c[0] for c in client.calls] == ["list"]


def test_deletes_go_in_batches_of_a_thousand(tmp_path):
    site = _site(tmp_path)
    remote = {f"gone/{i:04}.html": "0" for i in range(1001)}
    remote |= _unchanged(site)
    client = FakeR2(remote)
    sync_directory(site, "b", client, delete=True)
    batches = [c[2]["Objects"] for c in client.calls if c[0] == "delete"]
    assert [len(b) for b in batches] == [1000, 1]
    assert batches[1] == [{"Key": "gone/1000.html"}]


def test_a_change_to_derived_files_alone_is_skipped_and_logged(tmp_path):
    site, logged = _site(tmp_path), []
    (site / "pagefind").mkdir()
    (site / "pagefind" / "x.js").write_text("index")
    remote = _unchanged(site)
    client = FakeR2(remote)
    sync_directory(site, "b", client, log=logged.append)
    assert logged == ["skip    pagefind/x.js  (derived; no source file changed)"]
    assert [c[0] for c in client.calls] == ["list"]


def test_a_prefix_that_ends_in_a_slash_keeps_one(tmp_path):
    client = FakeR2({})
    sync_directory(_site(tmp_path), "b", client, prefix="p/", dry_run=True)
    assert client.calls == [("list", "b", "p/")]


# Faster uploads: rclone, a pool as wide as the threads, and one purge for a big change.

import json  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

from labinacan.sync import r2  # noqa: E402


def _config():
    return r2.R2Config("acct", "key-id", "secret")


def test_rclone_uploads_assets_before_pages_with_each_groups_headers(tmp_path):
    site = _site(tmp_path)
    (site / "app.css").write_text("css")
    calls = []

    def run(cmd, env, check):
        listing = cmd[cmd.index("--files-from-raw") + 1]
        calls.append((cmd, env, Path(listing).read_text().split()))
        return subprocess.CompletedProcess(cmd, 0)

    upload = r2.rclone_uploader(_config(), "/bin/rclone", run=run)
    keys = ["p/index.html", "p/app.css", "p/data/snapshots/r.parquet"]
    upload(site, "b", {}, keys, "p/")
    assert [files for _, _, files in calls] == [["data/snapshots/r.parquet"], ["app.css"],
                                                ["index.html"]]  # fmt: skip
    cmd, env, _ = calls[0]
    assert cmd[:4] == ["/bin/rclone", "copy", str(site), ":s3:b/p"]
    assert "Cache-Control: " + IMMUTABLE_CACHE in cmd and "--s3-upload-cutoff" in cmd
    assert "Cache-Control: " + SHORT_CACHE in calls[2][0]
    assert "Content-Type: text/html; charset=utf-8" in calls[2][0] or any(
        a.startswith("Content-Type: text/html") for a in calls[2][0]
    )
    # The secret goes in the environment, never on the command line.
    assert env["RCLONE_S3_SECRET_ACCESS_KEY"] == "secret" and "secret" not in " ".join(cmd)
    assert env["RCLONE_S3_ENDPOINT"] == "https://acct.r2.cloudflarestorage.com"


def test_a_failed_rclone_run_stops_the_sync_and_names_no_secret(tmp_path):
    site = _site(tmp_path)
    run = lambda cmd, env, check: subprocess.CompletedProcess(cmd, 1)  # noqa: E731
    upload = r2.rclone_uploader(_config(), "rclone", run=run)
    try:
        upload(site, "b", {}, ["index.html"], "")
    except r2.SyncError as exc:
        assert "rclone could not upload 1 files" in str(exc) and "secret" not in str(exc)
    else:
        raise AssertionError("no SyncError")


def test_the_sync_hands_its_uploads_to_the_uploader(tmp_path):
    site = _site(tmp_path)
    got = []
    fake = FakeR2({})
    r2.sync_directory(site, "b", fake, uploader=lambda *args: got.append(args))
    assert got[0][0] == site and got[0][1] == "b" and sorted(got[0][3]) == [
        "data/snapshots/r.parquet", "index.html"]  # fmt: skip
    assert not [c for c in fake.calls if c[0] == "put"]


def test_the_client_keeps_a_connection_for_each_upload_thread():
    client = r2.make_client(_config())
    assert client.meta.config.max_pool_connections == max(10, r2.UPLOAD_WORKERS)


def _purges(urls):
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"success": true}'

    def opener(request, timeout):
        sent.append(json.loads(request.data))
        return Response()

    r2.purge_cloudflare_cache("z", "t", urls, opener=opener)
    return sent


def test_a_big_change_purges_the_zone_in_one_request():
    urls = [f"https://x.org/{i}.html" for i in range(r2.PURGE_ALL_ABOVE + 1)]
    assert _purges(urls) == [{"purge_everything": True}]


def test_a_small_change_purges_its_urls_in_batches():
    urls = [f"https://x.org/{i}.html" for i in range(r2.PURGE_BATCH + 1)]
    sent = _purges(urls)
    assert [len(s["files"]) for s in sent] == [r2.PURGE_BATCH, 1]
    assert len(_purges(urls[: r2.PURGE_ALL_ABOVE])) > 1  # at the line, still by URL
