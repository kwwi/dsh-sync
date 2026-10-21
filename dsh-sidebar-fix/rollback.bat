@echo off
rem =====================================================================
rem rollback.bat - Windows counterpart of rollback.sh
rem
rem Restores the DSH profile to the exact state captured by apply.bat,
rem then removes the snapshot so a repeated rollback is a harmless no-op.
rem
rem Safe in every sequence:
rem   * no snapshot              -^> "nothing to do", exit 0
rem   * apply failed part-way    -^> snapshot is intact, profile is restored
rem   * rollback failed part-way -^> snapshot is KEPT, re-run it
rem   * rollback twice           -^> second run is a no-op
rem
rem Usage: rollback.bat [--keep-snapshot]
rem =====================================================================
setlocal enabledelayedexpansion

if "%PROFILE%"=="" set "PROFILE=%USERPROFILE%\.dsh\profiles\desktop"
set "PKG=dsh-better-sidebar"
set "SNAPDIR=%PROFILE%\.dsh-repair-snapshot"
set "SNAP_MARKER=%SNAPDIR%\SNAPSHOT_OK"
set "HERE=%~dp0"
set "TOOLS=%HERE%tools.cjs"
set "KEEP_SNAPSHOT=0"
if /I "%~1"=="--keep-snapshot" set "KEEP_SNAPSHOT=1"

echo.
echo == 0. Parameters ==
echo    PROFILE = %PROFILE%
echo    SNAPDIR = %SNAPDIR%

echo.
echo == 1. Is there anything to roll back? ==
if not exist "%SNAPDIR%" (
  echo    no snapshot found - nothing to roll back ^(normal state after a successful rollback^).
  endlocal
  exit /b 0
)
if not exist "%SNAPDIR%\package.json" (
  echo [FAIL] snapshot directory exists but contains no package.json: %SNAPDIR%
  echo    Refusing to guess a restore. Inspect it manually.
  dir /b "%SNAPDIR%"
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

set "INCOMPLETE=0"
if not exist "%SNAP_MARKER%" (
  set "INCOMPLETE=1"
  echo    [WARN] no SNAPSHOT_OK marker: this snapshot is incomplete ^(apply stopped before finishing^).
  echo    [WARN] File copies in it were taken BEFORE any mutation, so restoring them is still correct.
)

set "FROM_SPEC="
set "FROM_RESOLVED="
if exist "%SNAPDIR%\MANIFEST.txt" (
  for /f "usebackq tokens=1,* delims==" %%a in ("%SNAPDIR%\MANIFEST.txt") do (
    if /I "%%a"=="from_spec" set "FROM_SPEC=%%b"
    if /I "%%a"=="from_resolved" set "FROM_RESOLVED=%%b"
  )
)

echo.
echo == 2. Restoring configuration files ==
for %%f in (package.json pnpm-lock.yaml pnpm-workspace.yaml cordis.yml cordis.patch.yml) do (
  if exist "%SNAPDIR%\%%f" (
    copy /Y "%SNAPDIR%\%%f" "%PROFILE%\%%f" >nul
    if errorlevel 1 (
      echo [FAIL] could not restore %%f - snapshot kept at %SNAPDIR%
      exit /b 1
    )
    fc /b "%SNAPDIR%\%%f" "%PROFILE%\%%f" >nul
    if errorlevel 1 (
      echo [FAIL] restored %%f does not match the snapshot - snapshot kept
      exit /b 1
    )
    echo    restored %%f
  )
)

echo.
echo == 3. Restoring node_modules\%PKG% ==
if exist "%SNAPDIR%\node_modules-%PKG%" (
  if exist "%PROFILE%\node_modules\%PKG%" rmdir /S /Q "%PROFILE%\node_modules\%PKG%"
  xcopy "%SNAPDIR%\node_modules-%PKG%" "%PROFILE%\node_modules\%PKG%" /E /I /Y /Q >nul
  if errorlevel 1 (
    echo [FAIL] could not restore node_modules\%PKG% - snapshot kept
    exit /b 1
  )
  echo    restored node_modules\%PKG%
) else (
  echo    [WARN] snapshot holds no node_modules\%PKG% copy - relying on pnpm install only
)

echo.
echo == 4. Reconciling node_modules to the restored lockfile ==
set "RC=1"
if not "%PNPM_BIN%"=="" if exist "%PROFILE%\pnpm-lock.yaml" (
  pushd "%PROFILE%"
  call "%PNPM_BIN%" install --prefer-offline
  set "RC=!errorlevel!"
  if not "!RC!"=="0" (
    echo    pnpm install exited !RC! - retrying with --frozen-lockfile
    call "%PNPM_BIN%" install --frozen-lockfile
    set "RC=!errorlevel!"
  )
  popd
) else (
  echo    [WARN] pnpm unavailable or lockfile missing - skipping the install step
)
if not "!RC!"=="0" (
  echo    [WARN] pnpm install did not succeed ^(exit !RC!^). Files are already restored;
  echo    [WARN] if the version check below passes, the profile is usable.
)

echo.
echo == 5. Verification ==
for /f "delims=" %%v in ('node "%TOOLS%" show "%PROFILE%\package.json"') do set "RESTORED_SPEC=%%v"
for /f "delims=" %%v in ('node "%TOOLS%" resolved "%PROFILE%"') do set "RESTORED_RESOLVED=%%v"
echo    declared = !RESTORED_SPEC!
echo    resolved = !RESTORED_RESOLVED!
if not "%FROM_SPEC%"=="" echo    expected declared = %FROM_SPEC%
if not "%FROM_RESOLVED%"=="" echo    expected resolved = %FROM_RESOLVED%

set "VERIFY_OK=1"
if not "%FROM_SPEC%"=="" if not "!RESTORED_SPEC!"=="%FROM_SPEC%" (
  echo [FAIL] declared version is !RESTORED_SPEC!, expected %FROM_SPEC%
  set "VERIFY_OK=0"
)
if not "%FROM_RESOLVED%"=="" if not "!RESTORED_RESOLVED!"=="%FROM_RESOLVED%" (
  echo [FAIL] resolved version is !RESTORED_RESOLVED!, expected %FROM_RESOLVED%
  set "VERIFY_OK=0"
)

if not "!VERIFY_OK!"=="1" (
  echo [FAIL] rollback did not reach the snapshotted state. The snapshot is KEPT at %SNAPDIR%
  echo    Fix the cause ^(likely pnpm/network^) and re-run rollback.bat - it is safe to repeat.
  exit /b 1
)

echo.
echo == 6. Result ==
echo    profile restored to the pre-apply state
if "%KEEP_SNAPSHOT%"=="1" (
  echo    snapshot kept at %SNAPDIR% ^(--keep-snapshot^)
) else (
  if "%INCOMPLETE%"=="1" (
    echo    snapshot kept at %SNAPDIR% ^(incomplete snapshot - inspect before removing^)
  ) else (
    rmdir /S /Q "%SNAPDIR%"
    echo    snapshot removed - a second rollback will be a no-op
  )
)

echo.
echo == 7. Next step ==
echo    Fully quit and reopen DSH Desktop so the running process picks the restored tree up.

endlocal
exit /b 0
