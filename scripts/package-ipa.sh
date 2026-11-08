#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?This script is intended for the macOS GitHub Actions runner}"
: "${GITHUB_WORKSPACE:?This script is intended for the macOS GitHub Actions runner}"

APP="$RUNNER_TEMP/build/Build/Products/Release-iphoneos/MediaDownloaderIOS.app"
if [ ! -d "$APP" ]; then
  echo "ERRO: Aplicativo compilado nao foi encontrado em $APP" >&2
  exit 1
fi
if [ ! -f "$APP/MediaDownloaderIOS" ]; then
  echo "ERRO: O aplicativo compilado nao contem o executavel iOS." >&2
  exit 1
fi
STAGE="$RUNNER_TEMP/ipa-stage"
mkdir -p "$STAGE/Payload"
/usr/bin/ditto "$APP" "$STAGE/Payload/MediaDownloaderIOS.app"
cd "$STAGE"
/usr/bin/zip -qry "$GITHUB_WORKSPACE/MediaDownloader_iPhone_UNSIGNED.ipa" Payload
/usr/bin/unzip -t "$GITHUB_WORKSPACE/MediaDownloader_iPhone_UNSIGNED.ipa"
echo "IPA NAO ASSINADO GERADO: $GITHUB_WORKSPACE/MediaDownloader_iPhone_UNSIGNED.ipa"
