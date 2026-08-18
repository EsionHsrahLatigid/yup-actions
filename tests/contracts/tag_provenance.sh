set -euo pipefail
[[ "$TAG_NAME" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
version="${TAG_NAME#v}"

target_type="$(gh api "repos/$GH_REPO/git/ref/tags/$TAG_NAME" --jq '.object.type')"
target_sha="$(gh api "repos/$GH_REPO/git/ref/tags/$TAG_NAME" --jq '.object.sha')"
depth=0
while [[ "$target_type" == tag ]]; do
  depth=$((depth + 1))
  [[ "$depth" -le 5 ]]
  tag_object="$(gh api "repos/$GH_REPO/git/tags/$target_sha")"
  target_type="$(jq -r '.object.type' <<< "$tag_object")"
  target_sha="$(jq -r '.object.sha' <<< "$tag_object")"
done
[[ "$target_type" == commit ]]

cmake_source="$(gh api "repos/$GH_REPO/contents/CMakeLists.txt?ref=$target_sha" --jq '.content' | base64 --decode)"
mapfile -t cmake_versions < <(
  sed -nE "/^[[:space:]]*#/d; s/^[[:space:]]*project[[:space:]]*\\([[:space:]]*${PRODUCT}[[:space:]]+VERSION[[:space:]]+([0-9]+\\.[0-9]+\\.[0-9]+)[[:space:])]+.*$/\\1/p" \
    <<< "$cmake_source"
)
[[ "${#cmake_versions[@]}" -gt 0 ]]
for cmake_version in "${cmake_versions[@]}"; do
  [[ "$cmake_version" == "$version" ]]
done

runs="$(gh api --paginate \
  "repos/$GH_REPO/actions/runs?branch=main&event=push&head_sha=$target_sha&per_page=100" \
  --jq '.workflow_runs[] | select(.name == "CI" and .path == ".github/workflows/ci.yml" and .head_branch == "main" and .head_sha == "'"$target_sha"'" and .event == "push" and .status == "completed" and .conclusion == "success") | [.id, .head_sha] | @tsv')"
[[ -n "$runs" ]]
[[ "$(wc -l <<< "$runs" | tr -d ' ')" == 1 ]]
IFS=$'\t' read -r run_id run_sha <<< "$runs"
[[ "$run_sha" == "$target_sha" ]]

{
  printf 'run_id=%s\n' "$run_id"
  printf 'tag_name=%s\n' "$TAG_NAME"
  printf 'version=%s\n' "$version"
} >> "$GITHUB_OUTPUT"
