#!/usr/bin/env bash
# Create a minimal owm workspace for local exploration.
# Usage: ./scripts/seed-ws.sh [TARGET_DIR]
#
# Produces:
#   <TARGET_DIR>/
#     workspace.toml
#     instances/          <- owm create will write here
#     _repos/odoo.git     <- bare repos (real git, toy content)
#     _repos/product-core.git
#     _proxy/             <- owm create writes nginx blocks here
#     _shared/ _dumps/ _archive/ owm.log
#
# After running, cd into TARGET_DIR and use owm commands directly.
# Full materialise (owm create without --toml-only) requires postgres.
set -euo pipefail

WS="${1:-$HOME/tmp/owm-test-ws}"

if [[ -e "$WS" ]]; then
  echo "error: $WS already exists — remove it first or pass a different path." >&2
  echo "       rm -rf $WS" >&2
  exit 1
fi

echo "Seeding workspace at $WS ..."

mkdir -p "$WS"/{instances,_repos,_shared,_dumps,_archive,_proxy}
touch "$WS/owm.log"

# Toy upstream repos — one commit each so worktree add works
UPSTREAM="$WS/_upstream"
mkdir -p "$UPSTREAM"

for name in odoo product-core; do
  up="$UPSTREAM/$name"
  mkdir -p "$up"
  git -C "$up" init -q -b main
  git -C "$up" config user.email "seed@owm.test"
  git -C "$up" config user.name "owm-seed"
  echo "# $name" > "$up/README.md"
  git -C "$up" add README.md
  git -C "$up" commit -q -m "seed: initial"
  git clone --bare -q "$up" "$WS/_repos/$name.git"
  echo "  + _repos/$name.git"
done

cat > "$WS/workspace.toml" <<TOML
[repos]
odoo = "$WS/_repos/odoo.git"
product-core = "$WS/_repos/product-core.git"

[clusters]
"19" = {pg_version = "16", port = 5432}
TOML
echo "  + workspace.toml"

echo ""
echo "Done. Try it:"
echo ""
echo "  cd $WS"
echo ""
echo "  # Write an instance.toml (no I/O, always safe):"
echo "  owm create feat-test odoo=main:shared product-core=feat-test:main --toml-only"
echo ""
echo "  # Inspect what was written:"
echo "  cat instances/feat-test/instance.toml"
echo ""
echo "  # Materialise (requires postgres on port 5432):"
echo "  owm create feat-test"
echo ""
echo "  # From inside the instance dir — no name needed:"
echo "  cd instances/feat-test"
echo "  owm status"
echo ""
echo "Note: run owm via 'uv run owm' if it's not on PATH."
