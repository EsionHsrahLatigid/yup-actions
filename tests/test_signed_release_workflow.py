#!/usr/bin/env python3
"""Regression tests for the signed reusable release workflow contract."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/validate_signed_release_workflow.py"
WORKFLOW = ROOT / ".github/workflows/plugin-release-signed.yml"
CONTRACTS = ROOT / "tests/contracts"
SPEC = importlib.util.spec_from_file_location("validate_signed_release_workflow", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SignedReleaseWorkflowTests(unittest.TestCase):
    def validate_mutation(self, old: str, new: str, message: str) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(old, source)
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow = Path(temporary_directory) / "workflow.yml"
            workflow.write_text(source.replace(old, new, 1), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.WorkflowValidationError, message):
                MODULE.validate_workflow(workflow, CONTRACTS)

    def test_current_workflow_satisfies_contract(self) -> None:
        MODULE.validate_workflow(WORKFLOW, CONTRACTS)

    def test_rejects_tag_provenance_drift(self) -> None:
        self.validate_mutation(
            '.path == ".github/workflows/ci.yml"',
            '.path == ".github/workflows/other.yml"',
            "tag provenance script changed",
        )

    def test_rejects_publish_path_drift(self) -> None:
        self.validate_mutation(
            "gh release create \"$TAG_NAME\" --verify-tag --draft",
            "gh release create \"$TAG_NAME\" --draft",
            "publication script changed",
        )

    def test_rejects_tag_artifact_resolution_drift(self) -> None:
        self.validate_mutation(
            'if [[ "$PUBLISH_RELEASE" == true ]]; then',
            'if [[ "$PUBLISH_RELEASE" == false ]]; then',
            "tag artifact resolution changed",
        )

    def test_rejects_canary_with_publication_guard_removed(self) -> None:
        self.validate_mutation(
            '--publish-release "$PUBLISH_RELEASE"',
            '--publish-release "false"',
            "canary validator is missing",
        )

    def test_rejects_unpinned_self_checkout(self) -> None:
        self.validate_mutation(
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
            "actions/checkout@v6",
            "full commit SHA",
        )


if __name__ == "__main__":
    unittest.main()
