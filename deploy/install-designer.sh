#!/usr/bin/env bash
# Install an immutable copy of the route solver before restarting FlightCost.
set -euo pipefail
revision=${1:?Designer commit required}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
root=/srv/fca/designer
dest="$root/$revision"
mkdir -p "$root"
if [[ ! -d "$dest" ]]; then
    stage=$(mktemp -d "$root/.install.XXXXXXXX")
    trap 'rm -rf -- "$stage"' EXIT
    git -C "$stage" init -q
    git -C "$stage" fetch --quiet --depth=1 https://github.com/BormatovD/OpenAircraftCreator.git "$revision"
    git -C "$stage" checkout --quiet --detach FETCH_HEAD
    test "$(git -C "$stage" rev-parse HEAD)" = "$revision"
    test -s "$stage/scripts/flightcost-route.ts"
    chmod 755 "$stage"
    # Another deploy may already have installed the same immutable revision.
    mv -T "$stage" "$dest" || test -d "$dest"
fi
test "$(git -C "$dest" rev-parse HEAD)" = "$revision"
test -r "$dest/scripts/flightcost-route.ts"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 18) ? 0 : 1)'
