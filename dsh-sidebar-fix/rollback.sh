#!/usr/bin/env bash
# rollback.sh — restore the DSH "desktop" profile to the exact state captured by
# apply.sh, then remove the snapshot so a repeated rollback is a harmless no-op.
#
# Safe in every sequence:
#   * no snapshot              -> prints "nothing to do", exits 0
#   * apply failed part-way    -> snapshot is intact, profile is restored
#   * rollback failed part-way -> snapshot is KEPT, so it can simply be re-run
#   * rollback twice           -> second run is a no-op (snapshot already gone)
#
# Restores: package.json, pnpm-lock.yaml, pnpm-workspace.yaml, cordis.yml,
# cordis.patch.yml, and node_modules/dsh-better-sidebar.
#
# Usage:  ./rollback.sh [--keep-snapshot]
set -uo pipefail

PROFILE="${PROFILE:-/Users/houyuan/.dsh/profiles/desktop}"
PKG="dsh-better-sidebar"
SNAPDIR="$PROFILE/.dsh-repair-snapshot"
SNAP_MARKER="$SNAPDIR/SNAPSHOT_OK"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$HERE/tools.cjs"
SNAP_FILES=(package.json pnpm-lock.yaml pnpm-workspace.yaml cordis.yml cordis.patch.yml)

KEEP_SNAPSHOT=0
for arg in "$@"; do
  case "$arg" in
    --keep-snapshot) KEEP_SNAPSHOT=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf '[WARN] ignoring unknown argument: %s\n' "$arg" >&2 ;;
  esac
done

say() { printf '\n== %s ==\n' "$*"; }
info() { printf '   %s\n' "$*"; }
warn() { printf '   [WARN] %s\n' "$*"; }
fail() { printf '\n[FAIL] %s\n' "$*" >&2; }

say "0. Parameters"
info "PROFILE = $PROFILE"
info "SNAPDIR = $SNAPDIR"

say "1. Is there anything to roll back?"
if [ ! -e "$SNAPDIR" ]; then
  info "no snapshot found — nothing to roll back (this is the normal state after a successful rollback)."
  exit 0
fi
if [ ! -f "$SNAPDIR/package.json" ]; then
  fail "snapshot directory exists but contains no package.json: $SNAPDIR"
  info "Refusing to guess a restore. Inspect it manually:"
  ls -la "$SNAPDIR" 2>/dev/null | sed 's/^/        /'
  exit 1
fi

NODE_BIN="$(command -v node || true)"
[ -n "$NODE_BIN" ] || { fail "node not found on PATH"; exit 1; }
[ -f "$TOOLS" ] || { fail "missing helper $TOOLS (keep tools.cjs next to this script)"; exit 1; }

PNPM_BIN="$(command -v pnpm || true)"
if [ -z "$PNPM_BIN" ]; then
  for candidate in \
    "/Users/houyuan/Library/Application Support/DSH Desktop/runtime-commands/bin/pnpm" \
    "$HOME/Library/Application Support/DSH Desktop/runtime-commands/bin/pnpm"
  do
    if [ -x "$candidate" ]; then PNPM_BIN="$candidate"; break; fi
  done
fi

if [ -f "$SNAPDIR/MANIFEST.txt" ]; then
  info "snapshot manifest:"
  sed 's/^/        /' "$SNAPDIR/MANIFEST.txt"
else
  warn "no MANIFEST.txt in the snapshot"
fi

if [ ! -f "$SNAP_MARKER" ]; then
  warn "no SNAPSHOT_OK marker: this snapshot is incomplete (apply stopped before finishing)."
  warn "File copies in it were taken BEFORE any mutation, so restoring them is still correct."
  INCOMPLETE=1
else
  INCOMPLETE=0
fi

FROM_SPEC=""
FROM_RESOLVED=""
if [ -f "$SNAPDIR/MANIFEST.txt" ]; then
  FROM_SPEC="$(sed -n 's/^from_spec=//p' "$SNAPDIR/MANIFEST.txt" | head -1)"
  FROM_RESOLVED="$(sed -n 's/^from_resolved=//p' "$SNAPDIR/MANIFEST.txt" | head -1)"
fi

say "2. Restoring configuration files"
for f in "${SNAP_FILES[@]}"; do
  if [ -f "$SNAPDIR/$f" ]; then
    cp -p "$SNAPDIR/$f" "$PROFILE/$f" || { fail "could not restore $f — snapshot kept at $SNAPDIR"; exit 1; }
    cmp -s "$SNAPDIR/$f" "$PROFILE/$f" || { fail "restored $f does not match the snapshot — snapshot kept"; exit 1; }
    info "restored $f"
  else
    info "skipped $f (not present in the snapshot)"
  fi
done

say "3. Restoring node_modules/$PKG"
if [ -d "$SNAPDIR/node_modules-$PKG" ]; then
  rm -rf "$PROFILE/node_modules/$PKG" || { fail "could not clear node_modules/$PKG — snapshot kept"; exit 1; }
  cp -R "$SNAPDIR/node_modules-$PKG" "$PROFILE/node_modules/$PKG" \
    || { fail "could not restore node_modules/$PKG — snapshot kept"; exit 1; }
  info "restored node_modules/$PKG ($(node -e "console.log(require('$PROFILE/node_modules/$PKG/package.json').version)" 2>/dev/null || echo '?'))"
else
  warn "snapshot holds no node_modules/$PKG copy — relying on pnpm install only"
fi

say "4. Reconciling node_modules to the restored lockfile"
RC=1
if [ -n "$PNPM_BIN" ] && [ -f "$PROFILE/pnpm-lock.yaml" ]; then
  ( cd "$PROFILE" && "$PNPM_BIN" install --prefer-offline ); RC=$?
  if [ $RC -ne 0 ]; then
    info "pnpm install exited $RC — retrying with --frozen-lockfile"
    ( cd "$PROFILE" && "$PNPM_BIN" install --frozen-lockfile ); RC=$?
  fi
else
  warn "pnpm unavailable or lockfile missing — skipping the install step"
fi
if [ $RC -ne 0 ]; then
  warn "pnpm install did not succeed (exit $RC). The files and package directory are already restored;"
  warn "if the version check below passes, the profile is usable and you can ignore this."
fi

say "5. Verification"
RESTORED_SPEC="$("$NODE_BIN" "$TOOLS" show "$PROFILE/package.json" 2>/dev/null || echo '?')"
RESTORED_RESOLVED="$("$NODE_BIN" "$TOOLS" resolved "$PROFILE" 2>/dev/null || echo '?')"
info "declared = $RESTORED_SPEC"
info "resolved = $RESTORED_RESOLVED"
[ -n "$FROM_SPEC" ] && info "expected declared = $FROM_SPEC"
[ -n "$FROM_RESOLVED" ] && info "expected resolved = $FROM_RESOLVED"

VERIFY_OK=1
if [ -n "$FROM_SPEC" ] && [ "$RESTORED_SPEC" != "$FROM_SPEC" ]; then
  fail "declared version is '$RESTORED_SPEC', expected '$FROM_SPEC'"; VERIFY_OK=0
fi
if [ -n "$FROM_RESOLVED" ] && [ "$RESTORED_RESOLVED" != "$FROM_RESOLVED" ]; then
  fail "resolved version is '$RESTORED_RESOLVED', expected '$FROM_RESOLVED'"; VERIFY_OK=0
fi

if [ $VERIFY_OK -ne 1 ]; then
  fail "rollback did not reach the snapshotted state. The snapshot is KEPT at $SNAPDIR"
  info "Fix the cause (likely pnpm/network) and re-run ./rollback.sh — it is safe to repeat."
  exit 1
fi

say "6. Result"
info "profile restored to the pre-apply state"

if [ "$KEEP_SNAPSHOT" -eq 1 ] || [ "$INCOMPLETE" -eq 1 ]; then
  info "snapshot kept at $SNAPDIR (--keep-snapshot / incomplete snapshot)"
  info "Delete that directory yourself once you are satisfied; a later rollback would reuse it."
else
  rm -rf "$SNAPDIR" && info "snapshot removed — a second rollback will be a no-op"
fi

say "7. Next step"
info "Fully quit and reopen DSH Desktop so the running process picks the restored tree up."
