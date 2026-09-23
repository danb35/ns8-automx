#!/bin/bash

#
# Copyright (C) 2023 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

# Terminate on error
set -e

# Prepare variables for later use
images=()
# The image will be pushed to GitHub container registry
repobase="${REPOBASE:-ghcr.io/nethserver}"
# Configure the image name
reponame="automx"

# Create a new empty container image
container=$(buildah from scratch)

# Reuse existing nodebuilder-automx container, to speed up builds
if ! buildah containers --format "{{.ContainerName}}" | grep -q nodebuilder-automx; then
    echo "Pulling NodeJS runtime..."
    buildah from --name nodebuilder-automx -v "${PWD}:/usr/src:Z" docker.io/library/node:lts
fi

echo "Build static UI files with node..."
buildah run \
    --workingdir=/usr/src/ui \
    --env="NODE_OPTIONS=--openssl-legacy-provider" \
    nodebuilder-automx \
    sh -c "corepack enable && yarn install && yarn build"

# Add imageroot directory to the container image
buildah add "${container}" imageroot /imageroot
buildah add "${container}" ui/dist /ui

# Build the automx application image from source (see Containerfile).
# Upstream publishes ghcr.io/croessner/automx, but neither of its (pre-release)
# tags installs the "ldap" extra or the native libraries it needs to compile
# (DESIGN.md 4.5, VERIFY item 4), so we build our own instead of referencing
# a third-party org.nethserver.images entry. It's published as a second image
# under the same ref/tag as this module (see the CI tagging loop below), and
# imageroot/systemd/user/automx-app.service runs it directly by name.
imagetag=$(printf '%s' "${IMAGETAG:-latest}" | tr '/' '-')
automxappimage="${repobase}/automx-app"
buildah build --tag "${automxappimage}" -f Containerfile .
images+=("${automxappimage}")

# Smoke-check the built image against a synthetic config (DESIGN.md 9.1:
# "build image, run automx config validate and automx render
# autoconfig|autodiscover|mobileconfig against rendered configs with a
# synthetic address"). The fixture is the same shape render-automx-conf
# itself produces; no state/ldap-lookup.json exists here, so this also
# exercises automx-ldap-lookup's fallback path (DESIGN.md 3.3) on every
# build, not just the render logic in isolation (tests/unit/ covers that).
echo "Smoke-checking the automx-app image against a synthetic config..."
smokecontainer=$(buildah from "${automxappimage}")
smokeemail="dan@ci-smoke-test.test"
buildah copy "${smokecontainer}" tests/fixtures/synthetic-automx.conf /etc/automx/automx.conf
buildah run "${smokecontainer}" -- \
    automx config validate --config /etc/automx/automx.conf --domain ci-smoke-test.test
buildah run "${smokecontainer}" -- \
    automx render autoconfig --config /etc/automx/automx.conf --email "${smokeemail}" >/dev/null
buildah run "${smokecontainer}" -- \
    automx render autodiscover --config /etc/automx/automx.conf --email "${smokeemail}" --schema outlook >/dev/null
buildah run "${smokecontainer}" -- \
    automx render mobileconfig --config /etc/automx/automx.conf --email "${smokeemail}" >/dev/null
buildah rm "${smokecontainer}" >/dev/null

buildah config --entrypoint=/ \
    --label="org.nethserver.authorizations=traefik@node:routeadm node:reader cluster:accountconsumer dnshelper@cluster:dnswriter mail@any:mailadm" \
    --label="org.nethserver.tcp-ports-demand=1" \
    --label="org.nethserver.rootfull=0" \
    --label="org.nethserver.min-core=3.20.1" \
    --label="org.nethserver.images=${automxappimage}:${imagetag}" \
    "${container}"
# Commit the image
buildah commit "${container}" "${repobase}/${reponame}"

# Append the image URL to the images array
images+=("${repobase}/${reponame}")

#
# Setup CI when pushing to Github. 
# Warning! docker::// protocol expects lowercase letters (,,)
if [[ -n "${CI}" ]]; then
    # Set output value for Github Actions
    printf "images=%s\n" "${images[*],,}" >> "${GITHUB_OUTPUT}"
else
    # Just print info for manual push
    printf "Publish the images with:\n\n"
    for image in "${images[@],,}"; do printf "  buildah push %s docker://%s:%s\n" "${image}" "${image}" "${IMAGETAG:-latest}" ; done
    printf "\n"
fi
