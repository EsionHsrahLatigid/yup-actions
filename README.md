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

After the helper is included and the common target is registered:

```sh
cmake --preset plugin-release
cmake --build --preset plugin-release --parallel
```

The build preset should include `ehl_stage_products`, so the human-facing tree is refreshed automatically. On local macOS builds outside CI, that target also replaces the exact matching user-installed bundles with physical copies from the staged tree:

```text
~/Library/Audio/Plug-Ins/
├── VST3/<slug>_vst3_plugin.vst3
└── Components/<slug>_au_plugin.component
```

Standalone applications remain in `artifacts/`. CI and non-macOS builds do not install user plugins. Override the local behavior when needed:

```sh
cmake --preset plugin-release -DEHL_COPY_PLUGIN_AFTER_BUILD=OFF
cmake --preset plugin-release \
  -DEHL_USER_VST3_DIR=/alternate/VST3 \
  -DEHL_USER_AU_DIR=/alternate/Components
```

The repository CI runs `tests/TestStageAndInstall.cmake` with synthetic bundles to prove staging, physical copy, exact replacement of an existing matching bundle, manifest recording, and the disabled path without writing to a runner's real plugin folders.

## License

MIT. YUP and downloaded plugin SDKs retain their own licenses.
