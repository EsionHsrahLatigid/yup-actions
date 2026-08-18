#!/usr/bin/env python3
"""Validate the fail-closed contract of the signed reusable release workflow."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


class WorkflowValidationError(RuntimeError):
    """Raised when a required signed-release control is absent or changed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowValidationError(message)


def extract_step(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    marker = f"      - name: {name}"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise WorkflowValidationError(f"missing workflow step: {name}") from error
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("      - name:"):
            end = index
            break
        if lines[index] and not lines[index].startswith("      "):
            end = index
            break
    return "\n".join(lines[start:end]) + "\n"


def extract_run_script(step: str, name: str) -> str:
    lines = step.splitlines()
    try:
        start = lines.index("        run: |") + 1
    except ValueError as error:
        raise WorkflowValidationError(f"step has no literal run script: {name}") from error
    script: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        script.append(line[10:] if line else "")
    return "\n".join(script).rstrip() + "\n"


def validate_workflow(workflow_path: Path, contracts_dir: Path) -> None:
    workflow = workflow_path.read_text(encoding="utf-8")

    require("secrets: inherit" not in workflow, "secrets: inherit is forbidden")
    require(
        re.search(r"cancel-in-progress:\s*false", workflow) is not None,
        "release concurrency must not cancel in-progress notarization",
    )
    require(
        re.search(
            r"uses:\s+EsionHsrahLatigid/ehl-macos-signing-action@[0-9a-f]{40}",
            workflow,
        )
        is not None,
        "macOS signing action must be pinned to a full commit SHA",
    )
    require(
        re.search(
            r"\n      canary_sha:\n"
            r"(?:        .*\n)*?        required: false\n"
            r"        default: ''\n"
            r"        type: string\n",
            workflow,
        )
        is not None,
        "workflow_call must expose optional string canary_sha with an empty default",
    )
    require(
        "group: release-${{ github.repository }}-${{ inputs.canary_sha != '' && inputs.canary_sha || inputs.tag_name != '' && inputs.tag_name || github.ref_name }}"
        in workflow,
        "release concurrency must include canary_sha without weakening tag serialization",
    )

    tag_step = extract_step(workflow, "Resolve tag and successful CI run")
    require(
        "        if: ${{ inputs.canary_sha == '' }}\n" in tag_step,
        "tag provenance must run only when canary_sha is empty",
    )
    expected_tag_script = (contracts_dir / "tag_provenance.sh").read_text(
        encoding="utf-8"
    )
    require(
        extract_run_script(tag_step, "Resolve tag and successful CI run")
        == expected_tag_script,
        "tag provenance script changed from the locked release contract",
    )

    artifact_step = extract_step(workflow, "Resolve exact artifact IDs")
    require(
        "        if: ${{ inputs.canary_sha == '' }}\n" in artifact_step,
        "tag artifact resolution must run only when canary_sha is empty",
    )
    expected_artifact_script = (contracts_dir / "tag_artifacts.sh").read_text(
        encoding="utf-8"
    )
    require(
        extract_run_script(artifact_step, "Resolve exact artifact IDs")
        == expected_artifact_script,
        "tag artifact resolution changed from the locked release contract",
    )

    checkout_step = extract_step(workflow, "Checkout reusable workflow implementation")
    require(
        "        if: ${{ inputs.canary_sha != '' }}\n" in checkout_step,
        "self-checkout must be restricted to canary mode",
    )
    require(
        re.search(r"uses:\s+actions/checkout@[0-9a-f]{40}", checkout_step) is not None,
        "canary self-checkout must be pinned to a full commit SHA",
    )
    for expected in (
        "          repository: ${{ job.workflow_repository }}",
        "          ref: ${{ job.workflow_sha }}",
        "          persist-credentials: false",
    ):
        require(expected in checkout_step, f"canary self-checkout is missing: {expected}")

    canary_step = extract_step(workflow, "Resolve and validate current-main canary")
    require(
        "        if: ${{ inputs.canary_sha != '' }}\n" in canary_step,
        "canary validator must run only when canary_sha is non-empty",
    )
    for expected in (
        "--tag-name \"$TAG_NAME\"",
        "--canary-sha \"$CANARY_SHA\"",
        "--publish-release \"$PUBLISH_RELEASE\"",
        "--github-output \"$GITHUB_OUTPUT\"",
    ):
        require(expected in canary_step, f"canary validator is missing: {expected}")

    for output in ("mac_id", "run_id", "tag_name", "version", "windows_id"):
        require(
            f"steps.canary.outputs.{output}" in workflow,
            f"provenance job does not forward canary output: {output}",
        )

    prepare_windows = workflow.split("  prepare-windows:\n", 1)[1].split(
        "\n  publish:\n", 1
    )[0]
    require(
        "    if: ${{ inputs.publish_release }}" in prepare_windows,
        "Windows candidate preparation must remain publication-only",
    )
    require(
        re.search(
            r"\n      publish_release:\n"
            r"(?:        .*\n)*?        required: false\n"
            r"        default: true\n"
            r"        type: boolean\n",
            workflow,
        )
        is not None,
        "publish_release must remain an enabled-by-default boolean for tag releases",
    )
    publish_job = workflow.split("  publish:\n", 1)[1]
    require(
        "    if: ${{ inputs.publish_release }}" in publish_job,
        "GitHub Release mutation must remain publication-only",
    )
    publish_step = extract_step(workflow, "Publish release")
    expected_publish_script = (contracts_dir / "publish_release.sh").read_text(
        encoding="utf-8"
    )
    require(
        extract_run_script(publish_step, "Publish release") == expected_publish_script,
        "GitHub Release publication script changed from the locked release contract",
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "workflow",
        nargs="?",
        default=repo_root / ".github/workflows/plugin-release-signed.yml",
        type=Path,
    )
    parser.add_argument(
        "--contracts-dir",
        default=repo_root / "tests/contracts",
        type=Path,
    )
    args = parser.parse_args()

    try:
        validate_workflow(args.workflow, args.contracts_dir)
    except (OSError, WorkflowValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"workflow={args.workflow.resolve()}")
    print("canary_sha=valid")
    print("tag_release_contract=locked")
    print("status=valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
