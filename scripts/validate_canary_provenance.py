#!/usr/bin/env python3
"""Validate and resolve a tagless signed-release canary from current main CI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


FULL_SHA = re.compile(r"[0-9a-f]{40}")
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)")


class CanaryValidationError(RuntimeError):
    """Raised when the requested canary cannot be proven safe."""


class GitHubApi(Protocol):
    def json(self, endpoint: str) -> object: ...

    def tsv(self, endpoint: str, jq_filter: str) -> list[str]: ...

    def download(self, endpoint: str, destination: Path) -> None: ...


class GitHubCli:
    """Minimal fail-closed wrapper around the authenticated GitHub CLI."""

    @staticmethod
    def _run(arguments: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["gh", "api", *arguments],
            check=False,
            capture_output=True,
            text=text,
        )
        if result.returncode != 0:
            raise CanaryValidationError(
                f"GitHub API request failed with exit code {result.returncode}"
            )
        return result

    def json(self, endpoint: str) -> object:
        result = self._run([endpoint])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise CanaryValidationError("GitHub API returned invalid JSON") from error

    def tsv(self, endpoint: str, jq_filter: str) -> list[str]:
        result = self._run(["--paginate", endpoint, "--jq", jq_filter])
        return [line for line in result.stdout.splitlines() if line]

    def download(self, endpoint: str, destination: Path) -> None:
        with destination.open("wb") as output:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "-H",
                    "Accept: application/vnd.github+json",
                    endpoint,
                ],
                check=False,
                stdout=output,
                stderr=subprocess.PIPE,
            )
        if result.returncode != 0:
            destination.unlink(missing_ok=True)
            raise CanaryValidationError(
                f"GitHub artifact download failed with exit code {result.returncode}"
            )


@dataclass(frozen=True)
class CanaryResult:
    run_id: str
    version: str
    mac_id: str


def require_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CanaryValidationError(f"{context} response is not an object")
    return value


def require_full_sha(value: object, context: str) -> str:
    if not isinstance(value, str) or FULL_SHA.fullmatch(value) is None:
        raise CanaryValidationError(f"{context} must be a lowercase 40-character SHA")
    return value


def validate_request(tag_name: str, canary_sha: str, publish_release: str) -> None:
    if tag_name:
        raise CanaryValidationError("tag_name and canary_sha are mutually exclusive")
    if publish_release != "false":
        raise CanaryValidationError("canary_sha requires publish_release=false")
    require_full_sha(canary_sha, "canary_sha")


def project_version(source: str, product_name: str) -> str:
    pattern = re.compile(
        rf"^\s*project\s*\(\s*{re.escape(product_name)}\s+VERSION\s+"
        r"([0-9]+\.[0-9]+\.[0-9]+)(?:\s|\))"
    )
    versions: list[str] = []
    for line in source.splitlines():
        match = pattern.match(line.split("#", 1)[0])
        if match:
            versions.append(match.group(1))
    if not versions:
        raise CanaryValidationError(
            f"CMakeLists.txt has no project({product_name} VERSION x.y.z) declaration"
        )
    if len(set(versions)) != 1:
        raise CanaryValidationError("CMake project version declarations disagree")
    return versions[0]


def decode_cmake_contents(response: object) -> str:
    payload = require_mapping(response, "CMakeLists.txt")
    encoded = payload.get("content")
    if not isinstance(encoded, str):
        raise CanaryValidationError("CMakeLists.txt response has no base64 content")
    try:
        compact = "".join(encoded.split())
        return base64.b64decode(compact, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise CanaryValidationError("CMakeLists.txt content is not valid base64 UTF-8") from error


def unique_successful_main_run(lines: list[str], target_sha: str) -> str:
    matches: list[str] = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 8:
            raise CanaryValidationError("workflow run response has an invalid shape")
        run_id, name, path, branch, head_sha, event, status, conclusion = fields
        if (
            name == "CI"
            and path == ".github/workflows/ci.yml"
            and branch == "main"
            and head_sha == target_sha
            and event == "push"
            and status == "completed"
            and conclusion == "success"
        ):
            matches.append(run_id)
    if len(matches) != 1:
        raise CanaryValidationError(
            "expected exactly one successful main push CI run for canary_sha"
        )
    if not matches[0].isdigit():
        raise CanaryValidationError("successful CI run ID is not numeric")
    return matches[0]


def unique_macos_artifact(lines: list[str], product_name: str) -> str:
    expected_name = f"{product_name}-latest-macos-arm64"
    matches: list[str] = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 3:
            raise CanaryValidationError("artifact response has an invalid shape")
        artifact_id, name, expired = fields
        if name == expected_name and expired == "false":
            matches.append(artifact_id)
    if len(matches) != 1:
        raise CanaryValidationError(
            "expected exactly one unexpired macOS artifact for the exact CI run"
        )
    if not matches[0].isdigit():
        raise CanaryValidationError("macOS artifact ID is not numeric")
    return matches[0]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_macos_artifact(archive_path: Path, product_name: str, scratch: Path) -> None:
    expected_zip = f"{product_name}-latest-macos-arm64.zip"
    expected_entries = {expected_zip, "SHA256SUMS.txt"}
    try:
        with zipfile.ZipFile(archive_path) as artifact:
            entries = artifact.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) != 2 or set(names) != expected_entries:
                raise CanaryValidationError(
                    "macOS artifact must contain only the platform ZIP and SHA256SUMS.txt"
                )
            if any(entry.is_dir() for entry in entries):
                raise CanaryValidationError("macOS artifact contains an unexpected directory")

            manifest_info = artifact.getinfo("SHA256SUMS.txt")
            if manifest_info.file_size > 4096:
                raise CanaryValidationError("SHA256SUMS.txt is unexpectedly large")
            manifest = artifact.read(manifest_info).decode("utf-8")

            inner_zip = scratch / expected_zip
            with artifact.open(expected_zip) as source, inner_zip.open("wb") as output:
                shutil.copyfileobj(source, output)
    except (KeyError, UnicodeDecodeError, zipfile.BadZipFile) as error:
        raise CanaryValidationError("macOS artifact archive is invalid") from error

    manifest_lines = manifest.splitlines()
    if len(manifest_lines) != 1:
        raise CanaryValidationError("SHA256SUMS.txt must contain exactly one line")
    match = MANIFEST_LINE.fullmatch(manifest_lines[0])
    if match is None:
        raise CanaryValidationError("SHA256SUMS.txt has an invalid format")
    expected_hash, manifest_name = match.groups()
    if manifest_name != expected_zip:
        raise CanaryValidationError("SHA256SUMS.txt names the wrong platform ZIP")
    if file_sha256(inner_zip) != expected_hash:
        raise CanaryValidationError("macOS platform ZIP does not match SHA256SUMS.txt")
    try:
        with zipfile.ZipFile(inner_zip) as product_archive:
            if product_archive.testzip() is not None:
                raise CanaryValidationError("macOS platform ZIP has a CRC failure")
    except zipfile.BadZipFile as error:
        raise CanaryValidationError("macOS platform ZIP is invalid") from error


def resolve_canary(
    client: GitHubApi,
    repository: str,
    product_name: str,
    tag_name: str,
    canary_sha: str,
    publish_release: str,
) -> CanaryResult:
    validate_request(tag_name, canary_sha, publish_release)

    main_response = require_mapping(
        client.json(f"repos/{repository}/git/ref/heads/main"), "main ref"
    )
    main_object = require_mapping(main_response.get("object"), "main ref object")
    if main_object.get("type") != "commit":
        raise CanaryValidationError("GitHub main ref does not point to a commit")
    main_sha = require_full_sha(main_object.get("sha"), "GitHub main HEAD")
    if main_sha != canary_sha:
        raise CanaryValidationError("canary_sha does not equal GitHub main HEAD")

    cmake_source = decode_cmake_contents(
        client.json(f"repos/{repository}/contents/CMakeLists.txt?ref={canary_sha}")
    )
    version = project_version(cmake_source, product_name)

    run_lines = client.tsv(
        (
            f"repos/{repository}/actions/runs?branch=main&event=push&"
            f"head_sha={canary_sha}&per_page=100"
        ),
        (
            ".workflow_runs[] | [.id, .name, .path, .head_branch, .head_sha, "
            ".event, .status, .conclusion] | @tsv"
        ),
    )
    run_id = unique_successful_main_run(run_lines, canary_sha)

    artifact_lines = client.tsv(
        f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        ".artifacts[] | [.id, .name, .expired] | @tsv",
    )
    mac_id = unique_macos_artifact(artifact_lines, product_name)

    with tempfile.TemporaryDirectory(prefix="yup-canary-") as temporary_directory:
        scratch = Path(temporary_directory)
        artifact_archive = scratch / "macos-artifact.zip"
        client.download(
            f"repos/{repository}/actions/artifacts/{mac_id}/zip", artifact_archive
        )
        verify_macos_artifact(artifact_archive, product_name, scratch)

    return CanaryResult(run_id=run_id, version=version, mac_id=mac_id)


def write_github_output(path: Path, result: CanaryResult) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"run_id={result.run_id}\n")
        output.write("tag_name=\n")
        output.write(f"version={result.version}\n")
        output.write(f"mac_id={result.mac_id}\n")
        output.write("windows_id=\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--tag-name", default="")
    parser.add_argument("--canary-sha", required=True)
    parser.add_argument("--publish-release", choices=("true", "false"), required=True)
    parser.add_argument("--github-output", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = resolve_canary(
            GitHubCli(),
            args.repository,
            args.product_name,
            args.tag_name,
            args.canary_sha,
            args.publish_release,
        )
        write_github_output(args.github_output, result)
    except (CanaryValidationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print("mode=canary")
    print(f"target_sha={args.canary_sha}")
    print(f"run_id={result.run_id}")
    print(f"mac_id={result.mac_id}")
    print(f"version={result.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
