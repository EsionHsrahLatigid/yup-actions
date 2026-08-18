#!/usr/bin/env python3
"""Regression tests for tagless signed-release canary provenance."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/validate_canary_provenance.py"
SPEC = importlib.util.spec_from_file_location("validate_canary_provenance", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SHA = "a" * 40
OTHER_SHA = "b" * 40
PRODUCT = "Fixture"


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)
    return output.getvalue()


def valid_artifact() -> bytes:
    product_zip = zip_bytes({"Fixture.app/Contents/MacOS/Fixture": b"executable"})
    product_name = f"{PRODUCT}-latest-macos-arm64.zip"
    manifest = f"{hashlib.sha256(product_zip).hexdigest()}  {product_name}\n".encode()
    return zip_bytes({product_name: product_zip, "SHA256SUMS.txt": manifest})


class FakeGitHubApi:
    def __init__(self) -> None:
        cmake = b"project(Fixture VERSION 0.1.1 LANGUAGES C CXX)\n"
        self.main_sha = SHA
        self.cmake_content = base64.b64encode(cmake).decode()
        self.run_lines = [
            f"123\tCI\t.github/workflows/ci.yml\tmain\t{SHA}\tpush\tcompleted\tsuccess"
        ]
        self.artifact_lines = ["456\tFixture-latest-macos-arm64\tfalse"]
        self.artifact = valid_artifact()

    def json(self, endpoint: str) -> object:
        if endpoint.endswith("/git/ref/heads/main"):
            return {"object": {"type": "commit", "sha": self.main_sha}}
        if "/contents/CMakeLists.txt?ref=" in endpoint:
            return {"content": self.cmake_content}
        raise AssertionError(f"unexpected JSON endpoint: {endpoint}")

    def tsv(self, endpoint: str, jq_filter: str) -> list[str]:
        del jq_filter
        if "/actions/runs?" in endpoint:
            return self.run_lines
        if "/artifacts?" in endpoint:
            return self.artifact_lines
        raise AssertionError(f"unexpected TSV endpoint: {endpoint}")

    def download(self, endpoint: str, destination: Path) -> None:
        if endpoint != "repos/owner/repo/actions/artifacts/456/zip":
            raise AssertionError(f"unexpected download endpoint: {endpoint}")
        destination.write_bytes(self.artifact)


class CanaryProvenanceTests(unittest.TestCase):
    def resolve(self, client: FakeGitHubApi | None = None):
        return MODULE.resolve_canary(
            client or FakeGitHubApi(),
            "owner/repo",
            PRODUCT,
            "",
            SHA,
            "false",
        )

    def assert_rejected(self, client: FakeGitHubApi, message: str) -> None:
        with self.assertRaisesRegex(MODULE.CanaryValidationError, message):
            self.resolve(client)

    def test_accepts_exact_current_main_ci_artifact_with_manifest(self) -> None:
        result = self.resolve()
        self.assertEqual(result.run_id, "123")
        self.assertEqual(result.mac_id, "456")
        self.assertEqual(result.version, "0.1.1")

    def test_writes_only_nonpublishing_canary_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "github-output"
            MODULE.write_github_output(output, self.resolve())
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "run_id=123\ntag_name=\nversion=0.1.1\nmac_id=456\nwindows_id=\n",
            )

    def test_rejects_tag_name_with_canary_sha(self) -> None:
        with self.assertRaisesRegex(MODULE.CanaryValidationError, "mutually exclusive"):
            MODULE.resolve_canary(
                FakeGitHubApi(),
                "owner/repo",
                PRODUCT,
                "v0.1.1",
                SHA,
                "false",
            )

    def test_rejects_canary_when_publication_is_enabled(self) -> None:
        with self.assertRaisesRegex(MODULE.CanaryValidationError, "publish_release=false"):
            MODULE.resolve_canary(
                FakeGitHubApi(), "owner/repo", PRODUCT, "", SHA, "true"
            )

    def test_rejects_noncanonical_canary_sha(self) -> None:
        for invalid_sha in ("a" * 39, "A" * 40, "g" * 40):
            with self.subTest(invalid_sha=invalid_sha):
                with self.assertRaisesRegex(
                    MODULE.CanaryValidationError, "lowercase 40-character SHA"
                ):
                    MODULE.resolve_canary(
                        FakeGitHubApi(),
                        "owner/repo",
                        PRODUCT,
                        "",
                        invalid_sha,
                        "false",
                    )

    def test_rejects_sha_that_is_not_github_main_head(self) -> None:
        client = FakeGitHubApi()
        client.main_sha = OTHER_SHA
        self.assert_rejected(client, "does not equal GitHub main HEAD")

    def test_rejects_no_exact_successful_main_push_ci(self) -> None:
        client = FakeGitHubApi()
        client.run_lines = []
        self.assert_rejected(client, "exactly one successful main push CI")

    def test_rejects_multiple_exact_successful_main_push_ci_runs(self) -> None:
        client = FakeGitHubApi()
        client.run_lines.append(client.run_lines[0].replace("123", "124", 1))
        self.assert_rejected(client, "exactly one successful main push CI")

    def test_rejects_success_from_noncanonical_workflow(self) -> None:
        client = FakeGitHubApi()
        client.run_lines = [
            f"123\tCI\t.github/workflows/other.yml\tmain\t{SHA}\tpush\tcompleted\tsuccess"
        ]
        self.assert_rejected(client, "exactly one successful main push CI")

    def test_rejects_missing_macos_artifact(self) -> None:
        client = FakeGitHubApi()
        client.artifact_lines = ["789\tFixture-latest-windows-x64\tfalse"]
        self.assert_rejected(client, "exactly one unexpired macOS artifact")

    def test_rejects_expired_macos_artifact(self) -> None:
        client = FakeGitHubApi()
        client.artifact_lines = ["456\tFixture-latest-macos-arm64\ttrue"]
        self.assert_rejected(client, "exactly one unexpired macOS artifact")

    def test_rejects_artifact_without_sha256_manifest(self) -> None:
        client = FakeGitHubApi()
        product_name = f"{PRODUCT}-latest-macos-arm64.zip"
        client.artifact = zip_bytes({product_name: zip_bytes({"file": b"data"})})
        self.assert_rejected(client, "platform ZIP and SHA256SUMS.txt")

    def test_rejects_malformed_sha256_manifest(self) -> None:
        client = FakeGitHubApi()
        product_name = f"{PRODUCT}-latest-macos-arm64.zip"
        product_zip = zip_bytes({"file": b"data"})
        client.artifact = zip_bytes(
            {product_name: product_zip, "SHA256SUMS.txt": b"not-a-manifest\n"}
        )
        self.assert_rejected(client, "invalid format")

    def test_rejects_manifest_hash_mismatch(self) -> None:
        client = FakeGitHubApi()
        product_name = f"{PRODUCT}-latest-macos-arm64.zip"
        product_zip = zip_bytes({"file": b"data"})
        client.artifact = zip_bytes(
            {
                product_name: product_zip,
                "SHA256SUMS.txt": f"{'0' * 64}  {product_name}\n".encode(),
            }
        )
        self.assert_rejected(client, "does not match SHA256SUMS.txt")

    def test_rejects_invalid_inner_platform_zip(self) -> None:
        client = FakeGitHubApi()
        product_name = f"{PRODUCT}-latest-macos-arm64.zip"
        invalid_zip = b"not a ZIP"
        manifest = f"{hashlib.sha256(invalid_zip).hexdigest()}  {product_name}\n".encode()
        client.artifact = zip_bytes(
            {product_name: invalid_zip, "SHA256SUMS.txt": manifest}
        )
        self.assert_rejected(client, "platform ZIP is invalid")

    def test_rejects_missing_or_conflicting_cmake_version(self) -> None:
        for cmake_source in (
            b"project(Other VERSION 0.1.1)\n",
            b"project(Fixture VERSION 0.1.1)\nproject(Fixture VERSION 0.1.2)\n",
        ):
            with self.subTest(cmake_source=cmake_source):
                client = FakeGitHubApi()
                client.cmake_content = base64.b64encode(cmake_source).decode()
                with self.assertRaises(MODULE.CanaryValidationError):
                    self.resolve(client)


if __name__ == "__main__":
    unittest.main()
