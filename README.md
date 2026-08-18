# yup-actions

Reusable GitHub Actions workflows and CMake artifact-layout helpers for EHL audio plugins built with [YUP](https://github.com/kunitoki/yup).

## Artifact layout

Plugin repositories vendor `cmake/EhlYupArtifactLayout.cmake` and `cmake/StageYupProducts.cmake`. Building the common `ehl_stage_products` target creates:

```text
artifacts/
└── plugin-release/
    └── <platform-arch>/
        ├── standalone/
        ├── vst3/
        ├── au/           # macOS only
        └── ARTIFACTS.txt
```

`build/` remains an implementation detail for CMake and dependency output. Humans and packaging automation consume `artifacts/`.

## Reusable CI

Caller repositories keep a small trigger wrapper and call the central workflow from a job:

```yaml
jobs:
  ci:
    uses: EsionHsrahLatigid/yup-actions/.github/workflows/plugin-ci.yml@<commit-sha>
    with:
      product_name: BlackThrum
      product_slug: blackthrum
      cmake_option_prefix: BLACKTHRUM
      windows_debug_targets_json: '["blackthrum_engine_tests"]'
      windows_release_targets_json: '["ehl_stage_products","blackthrum_engine_tests","blackthrum_plugin_bridge_tests"]'
```

Pin callers to a full commit SHA. The reusable workflow provides change classification, macOS arm64 and Windows x64 build/test/package jobs, compiler caching on macOS, checksummed latest ZIP artifacts, and a stable summary check. Both platform jobs initialize direct Git submodules, allowing plugin repositories to pin public shared modules without fetching nested submodules or adding cross-repository credentials.

`plugin-release.yml` promotes the exact successful `main` CI artifacts for a version tag without rebuilding platform bundles. It remains available during the credential migration window.

`plugin-release-signed.yml` is the fail-closed public-release path. It preserves exact CI artifact provenance, signs macOS `.app`, `.vst3`, and `.component` bundles with Developer ID Application, submits a temporary ZIP to Apple notarization, staples every accepted bundle, recreates the final ZIP, and publishes only after re-verification. Callers pin the workflow to a full commit SHA and explicitly map these secrets:

- `MACOS_CERTIFICATE_P12_BASE64`
- `MACOS_CERTIFICATE_PASSWORD`
- `APPLE_TEAM_ID`
- `APPLE_API_KEY_ID`
- `APPLE_API_ISSUER_ID`
- `APPLE_API_PRIVATE_KEY_P8_BASE64`

For EHL releases, the certificate, Team ID, and App Store Connect Team API key must all belong to ISHII 2bit Program Office. Do not migrate callers until those secrets are configured; after migration, the unsigned workflow must no longer be used for public releases.

Before migration, configure a protected `release` environment in every caller repository with tag/branch restrictions and required reviewers. Keep the six signing values as organization or repository secrets explicitly mapped by the caller; do not duplicate same-named environment secrets. Signed runs for the same repository and tag are serialized without cancelling an in-flight notarization.

Set `publish_release: false` on `plugin-release-signed.yml` callers for a non-publishing canary. A tag-based canary continues to accept an existing semver `tag_name`. To verify the current `main` CI artifact without creating a tag, pass its lowercase 40-character commit as `canary_sha` and leave `tag_name` empty. This tagless mode rejects publication, requires `canary_sha` to equal GitHub's current `main` HEAD, resolves exactly one successful canonical `main` push CI run, and verifies the unexpired macOS artifact, `SHA256SUMS.txt`, checksum, and inner ZIP before requesting access to the protected `release` environment. Canary runs sign, notarize, staple, independently reverify, and upload the macOS candidate while skipping Windows preparation and every GitHub Release mutation.

## Local staging

After the helper is included and the common target is registered, use the explicit local-install preset:

```sh
cmake --preset plugin-install
cmake --build --preset plugin-install --parallel
ctest --preset plugin-install --output-on-failure
```

`plugin-install` inherits `plugin-release`, includes `ehl_stage_products`, and explicitly sets `EHL_COPY_PLUGIN_AFTER_BUILD=ON`. This avoids an older CMake cache retaining `OFF`. On local macOS builds, the target refreshes the human-facing tree and replaces the exact matching user-installed bundles with physical copies from the staged tree:

```text
~/Library/Audio/Plug-Ins/
├── VST3/<slug>_vst3_plugin.vst3
└── Components/<slug>_au_plugin.component
```

Standalone applications remain in `artifacts/`. CI and non-macOS builds use `plugin-release` and do not install user plugins. Repositories that do not yet expose `plugin-install` can force the same behavior with:

```sh
cmake --preset plugin-release -DEHL_COPY_PLUGIN_AFTER_BUILD=ON
cmake --preset plugin-release \
  -DEHL_COPY_PLUGIN_AFTER_BUILD=ON \
  -DEHL_USER_VST3_DIR=/alternate/VST3 \
  -DEHL_USER_AU_DIR=/alternate/Components
```

Use `-DEHL_COPY_PLUGIN_AFTER_BUILD=OFF` when staging without touching the current user's plugin folders is intentional.

The repository CI runs `tests/TestStageAndInstall.cmake` with synthetic bundles to prove staging, physical copy, exact replacement of an existing matching bundle, manifest recording, and the disabled path without writing to a runner's real plugin folders.

## License

MIT. YUP and downloaded plugin SDKs retain their own licenses.
