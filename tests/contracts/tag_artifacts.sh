set -euo pipefail
artifacts="$(gh api --paginate "repos/$GH_REPO/actions/runs/$RUN_ID/artifacts?per_page=100" --jq '.artifacts[] | [.id, .name, .expired] | @tsv')"
if [[ "$PUBLISH_RELEASE" == true ]]; then
  [[ "$(wc -l <<< "$artifacts" | tr -d ' ')" == 2 ]]
fi
mac_id="$(awk -F '\t' -v name="${PRODUCT}-latest-macos-arm64" '$2 == name && $3 == "false" { print $1 }' <<< "$artifacts")"
windows_id="$(awk -F '\t' -v name="${PRODUCT}-latest-windows-x64" '$2 == name && $3 == "false" { print $1 }' <<< "$artifacts")"
[[ "$mac_id" =~ ^[0-9]+$ ]]
if [[ "$PUBLISH_RELEASE" == true ]]; then
  [[ "$windows_id" =~ ^[0-9]+$ ]]
fi
printf 'mac_id=%s\nwindows_id=%s\n' "$mac_id" "$windows_id" >> "$GITHUB_OUTPUT"
