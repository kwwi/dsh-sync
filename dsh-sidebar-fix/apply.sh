#!/usr/bin/env bash
# apply.sh — fix the ONE flagged error in the DSH "desktop" profile:
#
#   dsh-better-sidebar 0.28.0 declares peer contracts for @deepseek-ai/dsh-*
#   ^0.2.1-rc.1 and @deepseek-ai/cordis ^4.0.5, but this deployment ships
#   @deepseek-ai/dsh-* 0.1.1-rc.2 and @deepseek-ai/cordis 4.0.1.
#
# The single change: pin that one dependency to TARGET_VERSION (0.17.1 — the
# newest sidebar release still on the 0.1.x core line), then reconcile
# node_modules from the profile's lockfile with pnpm.
#
# It does NOT touch: dsh.profile.bundles order, cordis.patch.yml, cordis.yml,
# any other plugin, the harness, or the core packages.
#
# Idempotency contract
#   * A snapshot is created ONLY when none exists yet; an existing snapshot is
#     never overwritten (it means apply already ran — roll it back first).
#   * Every mutation happens after the snapshot is complete and verified.
#   * If any step fails, the snapshot stays in place so rollback.sh restores
#     exactly the pre-apply state.
#
# Usage:  ./apply.sh              (uses the defaults below)
#         PROFILE=/path TARGET_VERSION=0.15.2 ./apply.sh
set -uo pipefail

PROFILE="${PROFILE:-/Users/houyuan/.dsh/profiles/desktop}"
TARGET_VERSION="${TARGET_VERSION:-0.17.1}"
PKG="dsh-better-sidebar"
AGGREGATE="@linxin666/dsh-web-ui-all"

SNAPDIR="$PROFILE/.dsh-repair-snapshot"
SNAP_MARKER="$SNAPDIR/SNAPSHOT_OK"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$HERE/tools.cjs"
SNAP_FILES=(package.json pnpm-lock.yaml pnpm-workspace.yaml cordis.yml cordis.patch.yml)

say() { printf '\n== %s ==\n' "$*"; }
info() { printf '   %s\n' "$*"; }
fail() { printf '\n[FAIL] %s\n' "$*" >&2; }

say "0. Parameters"
info "PROFILE        = $PROFILE"
info "TARGET_VERSION = $TARGET_VERSION"
info "SNAPDIR        = $SNAPDIR"

say "1. Preconditions"
[ -d "$PROFILE" ] || { fail "profile directory not found: $PROFILE"; exit 1; }
[ -f "$PROFILE/package.json" ] || { fail "missing $PROFILE/package.json"; exit 1; }
[ -f "$TOOLS" ] || { fail "missing helper $TOOLS (keep tools.cjs next to this script)"; exit 1; }
NODE_BIN="$(command -v node || true)"
[ -n "$NODE_BIN" ] || { fail "node not found on PATH"; exit 1; }
info "node           = $NODE_BIN ($("$NODE_BIN" --version))"

PNPM_BIN="$(command -v pnpm || true)"
if [ -z "$PNPM_BIN" ]; then
  for candidate in \
    "/Users/houyuan/Library/Application Support/DSH Desktop/runtime-commands/bin/pnpm" \
    "$HOME/Library/Application Support/DSH Desktop/runtime-commands/bin/pnpm"
  do
    if [ -x "$candidate" ]; then PNPM_BIN="$candidate"; break; fi
  done
fi
[ -n "$PNPM_BIN" ] || { fail "pnpm not found (PATH or DSH runtime-commands); cannot reconcile node_modules"; exit 1; }
info "pnpm           = $PNPM_BIN ($("$PNPM_BIN" --version 2>/dev/null | tail -1))"

CURRENT_SPEC="$("$NODE_BIN" "$TOOLS" show "$PROFILE/package.json")" \
  || { fail "could not read the declared $PKG version"; exit 1; }
CURRENT_RESOLVED="$("$NODE_BIN" "$TOOLS" resolved "$PROFILE")"
NESTED_VERSION="$("$NODE_BIN" "$TOOLS" nested "$PROFILE")"
info "declared       = $PKG@$CURRENT_SPEC"
info "resolved       = $CURRENT_RESOLVED   (what the loader actually imports)"
info "aggregate copy = $NESTED_VERSION   (nested under $AGGREGATE; not what rows resolve to)"

say "2. Snapshot guard"
if [ -e "$SNAPDIR" ]; then
  fail "a snapshot already exists: $SNAPDIR"
  info "apply has already run (or a previous run stopped part-way)."
  info "Refusing to overwrite it — otherwise the pre-apply state would be lost."
  info "Next step: run ./rollback.sh first, or inspect and remove that directory yourself:"
  ls -la "$SNAPDIR" 2>/dev/null | sed 's/^/        /'
  exit 3
fi
info "no snapshot yet — this run will create one"

say "3. Already at target?"
if [ "$CURRENT_SPEC" = "$TARGET_VERSION" ] && [ "$CURRENT_RESOLVED" = "$TARGET_VERSION" ]; then
  info "$PKG is already $TARGET_VERSION (declared and resolved). Nothing to do."
  info "No snapshot created, because no file will change; rollback.sh will be a no-op."
  exit 0
fi
info "current state differs from target — proceeding"

say "4. Preflight: is the target version reachable?"
if command -v curl >/dev/null 2>&1; then
  TARBALL="https://registry.npmjs.org/$PKG/-/$PKG-$TARGET_VERSION.tgz"
  CODE="$(curl -sS -I -m 20 -o /dev/null -w '%{http_code}' "$TARBALL" 2>/dev/null || echo 000)"
  info "HEAD $TARBALL -> $CODE"
  if [ "$CODE" != "200" ]; then
    fail "cannot reach $PKG@$TARGET_VERSION tarball (status $CODE). Nothing was changed."
    exit 1
  fi
else
  info "curl not available — skipping the reachability check"
fi

say "5. Creating the snapshot"
mkdir -p "$SNAPDIR" || { fail "cannot create $SNAPDIR"; exit 1; }
for f in "${SNAP_FILES[@]}"; do
  if [ -f "$PROFILE/$f" ]; then
    cp -p "$PROFILE/$f" "$SNAPDIR/$f" || { fail "could not copy $f into the snapshot"; rmdir "$SNAPDIR" 2>/dev/null; exit 1; }
    info "saved $f"
  fi
done
if [ -d "$PROFILE/node_modules/$PKG" ]; then
  info "saving node_modules/$PKG (offline restore fallback)..."
  cp -R "$PROFILE/node_modules/$PKG" "$SNAPDIR/node_modules-$PKG" \
    || { fail "could not copy node_modules/$PKG into the snapshot"; exit 1; }
  info "saved node_modules/$PKG ($(du -sh "$PROFILE/node_modules/$PKG" 2>/dev/null | cut -f1))"
fi

# Verify every copied file byte-for-byte before any mutation.
for f in "${SNAP_FILES[@]}"; do
  [ -f "$SNAPDIR/$f" ] || continue
  cmp -s "$PROFILE/$f" "$SNAPDIR/$f" || { fail "snapshot verification failed for $f — aborting before any change"; exit 1; }
done
info "snapshot verified"

{
  printf 'created=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf 'profile=%s\n' "$PROFILE"
  printf 'package=%s\n' "$PKG"
  printf 'from_spec=%s\n' "$CURRENT_SPEC"
  printf 'from_resolved=%s\n' "$CURRENT_RESOLVED"
  printf 'to_version=%s\n' "$TARGET_VERSION"
  printf 'nested_aggregate_copy=%s\n' "$NESTED_VERSION"
} > "$SNAPDIR/MANIFEST.txt" || { fail "could not write the snapshot manifest"; exit 1; }
cat "$SNAPDIR/MANIFEST.txt" | sed 's/^/   /'

# The marker is written LAST: its presence means "this snapshot is complete".
: > "$SNAP_MARKER" || { fail "could not write the snapshot marker"; exit 1; }
info "snapshot complete: $SNAPDIR"

say "6. Applying the single change"
"$NODE_BIN" "$TOOLS" pin "$PROFILE/package.json" "$TARGET_VERSION" \
  || { fail "could not rewrite package.json. Snapshot kept — run ./rollback.sh"; exit 1; }
info "declared now: $("$NODE_BIN" "$TOOLS" show "$PROFILE/package.json")"

say "7. Reconciling node_modules (pnpm install)"
cd "$PROFILE" || { fail "cannot enter $PROFILE"; exit 1; }
"$PNPM_BIN" install --prefer-offline
RC=$?
if [ $RC -ne 0 ]; then
  info "first attempt exited $RC — retrying without --prefer-offline"
  "$PNPM_BIN" install
  RC=$?
fi
if [ $RC -ne 0 ]; then
  fail "pnpm install failed (exit $RC)."
  info "package.json now points at $TARGET_VERSION, but node_modules was not reconciled."
  info "Snapshot kept at $SNAPDIR — run ./rollback.sh to restore the pre-apply state."
  exit 1
fi

say "8. Verification"
NEW_RESOLVED="$("$NODE_BIN" "$TOOLS" resolved "$PROFILE")"
NEW_SPEC="$("$NODE_BIN" "$TOOLS" show "$PROFILE/package.json")"
info "declared = $NEW_SPEC"
info "resolved = $NEW_RESOLVED"
if [ "$NEW_RESOLVED" != "$TARGET_VERSION" ]; then
  fail "resolved version is $NEW_RESOLVED, expected $TARGET_VERSION."
  info "Snapshot kept at $SNAPDIR — run ./rollback.sh to restore the pre-apply state."
  exit 1
fi
info "OK — $PKG now resolves to $TARGET_VERSION, matching this deployment's core 0.1.1-rc.2 / cordis 4.0.1"

say "9. What changed"
info "profile/package.json : dependencies.$PKG  $CURRENT_SPEC -> $TARGET_VERSION"
info "profile/pnpm-lock.yaml, node_modules/$PKG : reconciled by pnpm"
info "unchanged: dsh.profile.bundles order, cordis.patch.yml, cordis.yml, other plugins, core packages"

say "10. Next step"
info "1) Fully quit and reopen DSH Desktop, so the running process loads the new tree."
info "2) Re-run the profile diagnostics and confirm the 13 risk items are gone."
info "3) If anything looks wrong: ./rollback.sh"
