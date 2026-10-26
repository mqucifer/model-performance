#!/bin/sh
# Build the CAD-code evaluation's image on the Mac. Its tag is what `config.toml`
# names and what each results row records as `image`.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
tag=${1:-model-performance/cadquery:2.8.0}
# Extra apt packages, for a tag that adds them: libosmesa6 for `-osmesa`.
extra=${2:-}
docker build --build-arg EXTRA_PACKAGES="$extra" -t "$tag" "$here"
docker image inspect --format '{{.Id}}' "$tag"
