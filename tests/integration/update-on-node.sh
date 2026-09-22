#!/bin/bash
#
# Build new automx/automx-app images on a node and update an installed
# instance to them in place, keeping its state/domains.json and
# state/settings.json.
#
#   tests/integration/update-on-node.sh <node address> <module id> <new tag>
#
# The tag must be new for that instance (NS8 refuses to update to the
# image URL it already runs).
set -euo pipefail
node=${1:?usage: update-on-node.sh <node address> <module id> <new tag>}
module=${2:?usage: update-on-node.sh <node address> <module id> <new tag>}
tag=${3:?usage: update-on-node.sh <node address> <module id> <new tag>}
here=$(cd "$(dirname "$0")" && pwd)

"$here/build-on-node.sh" "$node" "$tag" >/dev/null
ssh "root@$node" "
    set -e
    # The module's own rootless podman storage is separate from root's --
    # both images (the agent image update-module installs directly, and
    # automx-app, pulled via the org.nethserver.images mechanism) need to
    # already be there, since 'localhost/...' is not a reachable registry
    # from inside that context.
    podman save localhost/automx:$tag | runagent -m $module podman load >/dev/null
    podman save localhost/automx-app:$tag | runagent -m $module podman load >/dev/null
    echo '{\"module_url\":\"localhost/automx:$tag\",\"instances\":[\"$module\"]}' \
        | api-cli run update-module --data - >/dev/null
    podman rmi localhost/automx:$tag localhost/automx-app:$tag >/dev/null 2>&1 || true
    echo \"$module now runs \$(redis-cli HGET module/$module/environment IMAGE_URL)\""
