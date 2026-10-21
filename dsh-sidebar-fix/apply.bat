@echo off
rem =====================================================================
rem apply.bat - Windows counterpart of apply.sh
rem
rem Fixes the one flagged error in the DSH profile: dsh-better-sidebar
rem 0.28.0 declares peer contracts newer than this deployment's core.
rem The single change is pinning that dependency to TARGET_VERSION, then
rem reconciling node_modules with pnpm.
rem
rem It does NOT touch dsh.profile.bundles order, cordis.patch.yml,
rem cordis.yml, other plugins, the harness, or the core packages.
rem
rem Idempotency: a snapshot is created only when none exists; an existing
rem snapshot is never overwritten. On any failure the snapshot is kept so
rem rollback.bat can restore the pre-apply state.
rem
rem Usage: apply.bat
rem        set PROFILE=C:\Users\me\.dsh\profiles\desktop && apply.bat
rem        set TARGET_VERSION=0.15.2 && apply.bat
rem =====================================================================
setlocal enabledelayedexpansion

if "%PROFILE%"=="" set "PROFILE=%USERPROFILE%\.dsh\profiles\desktop"
if "%TARGET_VERSION%"=="" set "TARGET_VERSION=0.17.1"
set "PKG=dsh-better-sidebar"
set "SNAPDIR=%PROFILE%\.dsh-repair-snapshot"
set "SNAP_MARKER=%SNAPDIR%\SNAPSHOT_OK"
set "HERE=%~dp0"
set "TOOLS=%HERE%tools.cjs"

echo.
echo == 0. Parameters ==
echo    PROFILE        = %PROFILE%
echo    TARGET_VERSION = %TARGET_VERSION%
echo    SNAPDIR        = %SNAPDIR%

echo.
echo == 1. Preconditions ==
if not exist "%PROFILE%\package.json" (
  echo [FAIL] missing %PROFILE%\package.json
  exit /b 1
)
if not exist "%TOOLS%" (
  echo [FAIL] missing helper %TOOLS% ^(keep tools.cjs next to this script^)
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [FAIL] node not found on PATH
  exit /b 1
)

set "PNPM_BIN="
where pnpm >nul 2>nul
if not errorlevel 1 (
  set "PNPM_BIN=pnpm"
) else (
  if exist "%APPDATA%\DSH Desktop\runtime-commands\bin\pnpm.cmd" set "PNPM_BIN=%APPDATA%\DSH Desktop\runtime-commands\bin\pnpm.cmd"
)
if "%PNPM_BIN%"=="" (
  echo [FAIL] pnpm not found ^(PATH or DSH runtime-commands^); cannot reconcile node_modules
  exit /b 1
)

for /f "delims=" %%v in ('node "%TOOLS%" show "%PROFILE%\package.json"') do set "CURRENT_SPEC=%%v"
for /f "delims=" %%v in ('node "%TOOLS%" resolved "%PROFILE%"') do set "CURRENT_RESOLVED=%%v"
for /f "delims=" %%v in ('node "%TOOLS%" nested "%PROFILE%"') do set "NESTED_VERSION=%%v"
echo    declared       = %PKG%@%CURRENT_SPEC%
echo    resolved       = %CURRENT_RESOLVED%   ^(what the loader actually imports^)
echo    aggregate copy = %NESTED_VERSION%   ^(nested under @linxin666/dsh-web-ui-all^)

echo.
echo == 2. Snapshot guard ==
if exist "%SNAPDIR%" (
  echo [FAIL] a snapshot already exists: %SNAPDIR%
  echo    apply has already run ^(or a previous run stopped part-way^).
  echo    Refusing to overwrite it - the pre-apply state would be lost.
  echo    Next step: run rollback.bat first, or inspect and remove that directory yourself.
  dir /b "%SNAPDIR%"
  exit /b 3
)
echo    no snapshot yet - this run will create one

echo.
echo == 3. Already at target? ==
if "%CURRENT_SPEC%"=="%TARGET_VERSION%" if "%CURRENT_RESOLVED%"=="%TARGET_VERSION%" (
  echo    %PKG% is already %TARGET_VERSION% ^(declared and resolved^). Nothing to do.
  echo    No snapshot created, because no file will change; rollback.bat will be a no-op.
  exit /b 0
)

echo.
echo == 4. Preflight: is the target version reachable? ==
where curl >nul 2>nul
if errorlevel 1 (
  echo    curl not available - skipping the reachability check
) else (
  for /f "delims=" %%c in ('curl -sS -I -m 20 -o NUL -w "%%{http_code}" "https://registry.npmjs.org/%PKG%/-/%PKG%-%TARGET_VERSION%.tgz"') do set "CODE=%%c"
  echo    HEAD tarball -^> !CODE!
  if not "!CODE!"=="200" (
    echo [FAIL] cannot reach %PKG%@%TARGET_VERSION% tarball ^(status !CODE!^). Nothing was changed.
    exit /b 1
  )
)

echo.
echo == 5. Creating the snapshot ==
mkdir "%SNAPDIR%" 2>nul
for %%f in (package.json pnpm-lock.yaml pnpm-workspace.yaml cordis.yml cordis.patch.yml) do (
  if exist "%PROFILE%\%%f" (
    copy /Y "%PROFILE%\%%f" "%SNAPDIR%\%%f" >nul
    if errorlevel 1 (
      echo [FAIL] could not copy %%f into the snapshot
      exit /b 1
    )
    fc /b "%PROFILE%\%%f" "%SNAPDIR%\%%f" >nul
    if errorlevel 1 (
      echo [FAIL] snapshot verification failed for %%f - aborting before any change
      exit /b 1
    )
    echo    saved %%f
  )
)
if exist "%PROFILE%\node_modules\%PKG%" (
  echo    saving node_modules\%PKG% ^(offline restore fallback^)...
  xcopy "%PROFILE%\node_modules\%PKG%" "%SNAPDIR%\node_modules-%PKG%" /E /I /Y /Q >nul
  if errorlevel 1 (
    echo [FAIL] could not copy node_modules\%PKG% into the snapshot
    exit /b 1
  )
)
> "%SNAPDIR%\MANIFEST.txt" (
  echo profile=%PROFILE%
  echo package=%PKG%
  echo from_spec=%CURRENT_SPEC%
  echo from_resolved=%CURRENT_RESOLVED%
  echo to_version=%TARGET_VERSION%
  echo nested_aggregate_copy=%NESTED_VERSION%
)
rem marker written LAST: its presence means "this snapshot is complete"
type nul > "%SNAP_MARKER%"
echo    snapshot complete: %SNAPDIR%

echo.
echo == 6. Applying the single change ==
node "%TOOLS%" pin "%PROFILE%\package.json" %TARGET_VERSION%
if errorlevel 1 (
  echo [FAIL] could not rewrite package.json. Snapshot kept - run rollback.bat
  exit /b 1
)

echo.
echo == 7. Reconciling node_modules ^(pnpm install^) ==
pushd "%PROFILE%"
call "%PNPM_BIN%" install --prefer-offline
set "RC=!errorlevel!"
if not "!RC!"=="0" (
  echo    first attempt exited !RC! - retrying without --prefer-offline
  call "%PNPM_BIN%" install
  set "RC=!errorlevel!"
)
popd
if not "!RC!"=="0" (
  echo [FAIL] pnpm install failed ^(exit !RC!^).
  echo    package.json now points at %TARGET_VERSION%, but node_modules was not reconciled.
  echo    Snapshot kept at %SNAPDIR% - run rollback.bat to restore the pre-apply state.
  exit /b 1
)

echo.
echo == 8. Verification ==
for /f "delims=" %%v in ('node "%TOOLS%" resolved "%PROFILE%"') do set "NEW_RESOLVED=%%v"
for /f "delims=" %%v in ('node "%TOOLS%" show "%PROFILE%\package.json"') do set "NEW_SPEC=%%v"
echo    declared = !NEW_SPEC!
echo    resolved = !NEW_RESOLVED!
if not "!NEW_RESOLVED!"=="%TARGET_VERSION%" (
  echo [FAIL] resolved version is !NEW_RESOLVED!, expected %TARGET_VERSION%.
  echo    Snapshot kept at %SNAPDIR% - run rollback.bat to restore the pre-apply state.
  exit /b 1
)
echo    OK - %PKG% now resolves to %TARGET_VERSION%, matching this deployment's core 0.1.1-rc.2 / cordis 4.0.1

echo.
echo == 9. Next step ==
echo    1^) Fully quit and reopen DSH Desktop, so the running process loads the new tree.
echo    2^) Re-run the profile diagnostics and confirm the 13 risk items are gone.
echo    3^) If anything looks wrong: rollback.bat

endlocal
exit /b 0
