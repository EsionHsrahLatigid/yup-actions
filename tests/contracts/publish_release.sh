set -euo pipefail
mac_zip="${PRODUCT}-${VERSION}-macos-arm64.zip"
windows_zip="${PRODUCT}-${VERSION}-windows-x64.zip"
if gh release view "$TAG_NAME" >/dev/null 2>&1; then
  is_draft="$(gh release view "$TAG_NAME" --json isDraft --jq '.isDraft')"
  [[ "$is_draft" == true ]]
else
  gh release create "$TAG_NAME" --verify-tag --draft \
    --title "$PRODUCT $VERSION" --generate-notes
fi
while IFS= read -r existing_asset; do
  [[ -z "$existing_asset" ]] || gh release delete-asset "$TAG_NAME" "$existing_asset" --yes
done < <(gh release view "$TAG_NAME" --json assets --jq '.assets[].name')
gh release upload "$TAG_NAME" \
  "release-candidates/$mac_zip" \
  "release-candidates/$windows_zip" --clobber
mapfile -t published_assets < <(gh release view "$TAG_NAME" --json assets --jq '.assets[].name' | LC_ALL=C sort)
[[ "${#published_assets[@]}" == 2 ]]
[[ "${published_assets[0]}" == "$mac_zip" ]]
[[ "${published_assets[1]}" == "$windows_zip" ]]
gh release edit "$TAG_NAME" --draft=false
