"""labinacan's commands: ``deploy`` and the mounting of ``social`` (#6628)."""

import click
from click.testing import CliRunner

from labinacan import cli as lab
from labinacan.sync import r2
from labinacan.sync.r2 import SyncPlan


def test_site_commands_give_deploy_the_projects_site_url():
    def url():
        return "https://x.org/"

    deploy, social, literature_map = lab.site_commands("LAB_URL", url)
    option = next(p for p in deploy.params if p.name == "site_url")
    assert (option.envvar, option.default) == ("LAB_URL", url)
    assert social is lab.social_group
    assert literature_map is lab.literature_map_command


def test_literature_map_runs_the_generator(monkeypatch):
    from labinacan import literature_map

    ran = []
    monkeypatch.setattr(literature_map, "main", lambda: ran.append(True))
    result = CliRunner().invoke(lab.literature_map_command, [])
    assert result.exit_code == 0 and ran == [True]


def test_literature_map_names_the_extra_when_a_library_is_missing(monkeypatch):
    from labinacan import literature_map

    def main():
        raise ModuleNotFoundError("No module named 'umap'")

    monkeypatch.setattr(literature_map, "main", main)
    result = CliRunner().invoke(lab.literature_map_command, [])
    assert result.exit_code == 1
    assert "No module named 'umap'" in result.output and "labinacan[map]" in result.output


def _deploy(monkeypatch, tmp_path, env, urls, rclone=None, extra=()):
    """Run ``deploy`` with a stand-in for R2 and Cloudflare; return what each got."""
    import shutil

    seen = {}
    monkeypatch.setattr(shutil, "which", lambda name: rclone if name == "rclone" else None)
    monkeypatch.setattr(r2.R2Config, "from_env", classmethod(lambda cls: "config"))
    monkeypatch.setattr(r2, "make_client", lambda config: seen.update(client=config) or "client")

    def sync(dist, bucket, client, *, prefix, delete, dry_run, log, uploader):
        seen["sync"] = (dist, bucket, client, prefix, delete, dry_run, log)
        seen["uploader"] = uploader
        return SyncPlan(uploads=["p/a.html"])

    monkeypatch.setattr(r2, "sync_directory", sync)

    def targets(plan, site_url, prefix):
        seen["targets"] = (site_url, prefix)
        return urls

    def purge(zone, token, found):
        seen["purge"] = (zone, token, found)

    monkeypatch.setattr(r2, "purge_targets", targets)
    monkeypatch.setattr(r2, "purge_cloudflare_cache", purge)
    group = click.Group(commands=lab.site_commands("LAB_URL", lambda: "https://x.org/"))
    args = ["deploy", "--dist-dir", str(tmp_path), "--bucket", "b", "--prefix", "p/", "--delete",
            *extra]  # fmt: skip
    result = CliRunner().invoke(group, args, env=env)
    return result, seen


def test_deploy_syncs_then_purges_the_changed_urls(monkeypatch, tmp_path):
    env = {"CF_ZONE_ID": "z", "CF_API_TOKEN": "t"}
    result, seen = _deploy(monkeypatch, tmp_path, env, ["https://x.org/p/a.html"])
    assert result.exit_code == 0, result.output
    assert seen["client"] == "config"
    assert seen["sync"] == (tmp_path, "b", "client", "p/", True, False, click.echo)
    assert seen["targets"] == ("https://x.org/", "p/")
    assert seen["purge"] == ("z", "t", ["https://x.org/p/a.html"])
    assert result.output == (
        "Uploading with boto3\n"
        "Uploaded 1, unchanged 0, deleted 0, derived skipped 0\n"
        "Purged 1 URLs from the Cloudflare cache\n"
    )


def test_deploy_says_when_nothing_needs_a_purge(monkeypatch, tmp_path):
    result, seen = _deploy(monkeypatch, tmp_path, {"CF_ZONE_ID": "z", "CF_API_TOKEN": "t"}, [])
    assert result.output.endswith("Nothing changed; no cache purge.\n") and "purge" not in seen


def test_deploy_purges_nothing_without_both_cloudflare_secrets(monkeypatch, tmp_path):
    for env in ({"CF_API_TOKEN": "t"}, {"CF_ZONE_ID": "z"}):
        result, seen = _deploy(monkeypatch, tmp_path, env, ["u"])
        assert result.exit_code == 0 and "targets" not in seen and "purge" not in seen


def test_deploy_uploads_with_rclone_when_it_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(r2, "rclone_uploader", lambda config, path: ("rclone", config, path))
    result, seen = _deploy(monkeypatch, tmp_path, {}, [], rclone="/bin/rclone")
    assert result.exit_code == 0, result.output
    assert seen["uploader"] == ("rclone", "config", "/bin/rclone")
    assert result.output.startswith("Uploading with rclone\n")
    result, seen = _deploy(monkeypatch, tmp_path, {}, [], rclone="/bin/rclone",
                           extra=["--uploader", "boto"])  # fmt: skip
    assert seen["uploader"] is None and result.output.startswith("Uploading with boto3\n")


def test_deploy_refuses_rclone_when_it_is_not_installed(monkeypatch, tmp_path):
    result, seen = _deploy(monkeypatch, tmp_path, {}, [], extra=["--uploader", "rclone"])
    assert result.exit_code == 1 and "rclone is not installed" in result.output
    assert "sync" not in seen
