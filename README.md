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

`plugin-release.yml` promotes the exact successful `main` CI artifacts for a version tag without rebuilding platform bundles.

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
