#!/bin/sh
# Build the CAD-code evaluation's images on the Mac. Each tag is what a results row
# records as `image`, beside its id (`image_id`).
#
#   build.sh            the CadQuery image, model-performance/cadquery:2.8.0
#   build.sh v2         the v2 image (#40) on top of it: refused unless the local
#                       2.8.0 tag is the image pinned below
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# The CadQuery image every v2 run stands on: its id when the v1 runs were made.
BASE=model-performance/cadquery:2.8.0
BASE_ID=sha256:1f29a53a3ca6e85ac7b977a82f98fa6f495f5166060575d17b4e283d7e55bc5e
V2=model-performance/cadquery:2.8.0-v2
if [ "${1:-}" = "v2" ]; then
    found=$(docker image inspect --format '{{.Id}}' "$BASE" 2>/dev/null || true)
    if [ "$found" != "$BASE_ID" ]; then
        echo "refused: $BASE is ${found:-not built}, not the pinned $BASE_ID" >&2
        exit 2
    fi
    # The pinned id, by a tag named for it, so FROM is that image and no other.
    base_tag="model-performance/cadquery:base-${BASE_ID#sha256:}"
    base_tag=${base_tag%"${base_tag#*:base-????????????}"}
    docker tag "$BASE_ID" "$base_tag"
    docker build --build-arg BASE="$base_tag" --build-arg BASE_ID="$found" \
        -f "$here/Dockerfile.v2" -t "$V2" "$here"
    docker image inspect --format '{{.Id}}' "$V2"
    exit 0
fi
tag=${1:-$BASE}
docker build -t "$tag" "$here"
docker image inspect --format '{{.Id}}' "$tag"
