#
# Copyright (C) 2026 Dan Brown
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Builds automx (https://github.com/croessner/automx) from a pinned upstream
# source ref, with the "ldap" extra enabled. Upstream publishes
# ghcr.io/croessner/automx, but neither of its two (pre-release) tags installs
# python-ldap or the native libraries it needs to compile — see DESIGN.md
# section 4.5 and VERIFY item 4. This image is built and published by
# build-images.sh as a second image alongside the module's own agent image,
# and is what imageroot/systemd/user/automx-app.service actually runs.
#
# Pinned to the v3.0.0-beta.3 tag (commit 627e7a655e0a...), the latest
# automx 3.x pre-release at the time this was written. Bump AUTOMX_REF when
# upstream cuts a new release; Renovate does not track this automatically
# (it has no upstream image tag to follow here), so this needs a manual bump
# tracked the same way as any other pinned source dependency.

FROM python:3.14.7-slim-trixie AS builder

ARG AUTOMX_REF=v3.0.0-beta.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libldap-dev \
        libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth=1 --branch="${AUTOMX_REF}" \
        https://github.com/croessner/automx.git .

RUN python -m venv /opt/automx \
    && /opt/automx/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/automx/bin/pip install --no-cache-dir '.[ldap]' dnspython==2.8.0

FROM python:3.14.7-slim-trixie AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libldap2 \
        libsasl2-2 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 automx \
    && useradd --uid 10001 --gid automx --no-create-home --home-dir /nonexistent automx \
    && mkdir -p /etc/automx \
    && chown automx:automx /etc/automx

COPY --from=builder /opt/automx /opt/automx

# Static helper scripts (DESIGN.md 3.3, 5.4), baked into the image since
# they're code, not per-instance state:
#  - automx-ldap-lookup: the script-backend lookup helper automx itself
#    invokes as a subprocess.
#  - automx-dns-check: the no-dnshelper DNS status check (5.4), invoked by
#    the host-side check-dns action via a one-off `podman run --rm`.
COPY --chmod=0755 imageroot/bin/automx-ldap-lookup /usr/local/bin/automx-ldap-lookup
COPY --chmod=0755 imageroot/bin/automx-dns-check /usr/local/bin/automx-dns-check

ENV PATH="/opt/automx/bin:${PATH}" \
    AUTOMX_CONFIG=/etc/automx/automx.conf

USER automx:automx
WORKDIR /nonexistent
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready')" || exit 1

ENTRYPOINT ["tini", "--", "automx"]
CMD ["serve", "--config", "/etc/automx/automx.conf", "--host", "0.0.0.0", "--port", "8000"]
