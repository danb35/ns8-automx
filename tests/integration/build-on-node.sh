#!/bin/bash
#
# Build ns8-automx's two images (the module agent image and automx-app,
# see build-images.sh/DESIGN.md 4.5) on an NS8 node, from local storage
# only: add-module pulls an image only when it is missing locally, so no
# registry is needed. Needs buildah and outbound internet access on the
# node (build-images.sh's automx-app build clones automx's source and pip
# installs packages; its UI build step pulls the node:lts image and runs
# yarn install) -- unlike ns8-dnshelper's equivalent script, this can't
# avoid needing the real build machinery on the node, since automx-app is
# built from source rather than being a small static binary.
#
#   tests/integration/build-on-node.sh <node address> [tag]
#
# The images are localhost/automx:<tag> and localhost/automx-app:<tag>.
# NS8 cannot update to an image URL the instance already has (its cleanup
# step needs the previous URL) -- to update an installed instance in
# place, build a NEW tag and run update-module with it; update-on-node.sh
# does the build and the update.
set -euo pipefail
node=${1:?usage: build-on-node.sh <node address> [tag]}
tag=${2:-test}
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
# Everything build-images.sh needs: source ui/ (it builds ui/dist itself,
# the same as a real CI publish -- no local Node toolchain required here),
# imageroot/, the Containerfile, and tests/fixtures/ for its own
# synthetic-config smoke check.
cp -R "$root/imageroot" "$root/ui" "$root/tests" "$root/Containerfile" "$root/build-images.sh" "$stage/"

COPYFILE_DISABLE=1 tar --no-xattrs -C "$stage" -cf - . | ssh "root@$node" '
    set -e
    rm -rf /root/automx-it && mkdir /root/automx-it
    tar -C /root/automx-it -xf -
    cd /root/automx-it
    REPOBASE=localhost bash build-images.sh
    # build-images.sh commits/builds untagged (defaults to :latest) outside
    # CI -- retag explicitly so update-on-node.sh can hand NS8 a URL it has
    # not seen before (it refuses to "update" to the image it already runs).
    podman tag localhost/automx:latest localhost/automx:'"$tag"'
    podman tag localhost/automx-app:latest localhost/automx-app:'"$tag"'
    cd / && rm -rf /root/automx-it
    podman images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | grep "^localhost/automx"'
