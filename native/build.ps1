# native/build.ps1 -- compile astro_flash.dll with MSVC (no CMake needed).
#
#   .\native\build.ps1            # Phase 0 minimal DLL -> vendor\astro_flash.dll
#
# Locates VS BuildTools via vswhere when present, else falls back to the
# known 18/BuildTools path. Invokes vcvars64.bat in a cmd subshell so the
# INCLUDE/LIB/PATH env is set, then cl.exe.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $PSScriptRoot "astro_flash\src"
$incDir = Join-Path $PSScriptRoot "astro_flash\include"
$vendor = Join-Path $root "vendor"
$outDll = Join-Path $vendor "astro_flash.dll"

if (-not (Test-Path $vendor)) { New-Item -ItemType Directory -Path $vendor | Out-Null }

# Locate vcvars64.bat
$vcvars = $null
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $install = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($install) {
        $cand = Join-Path $install "VC\Auxiliary\Build\vcvars64.bat"
        if (Test-Path $cand) { $vcvars = $cand }
    }
}
if (-not $vcvars) {
    $fallback = "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $fallback) { $vcvars = $fallback }
}
if (-not $vcvars) { throw "vcvars64.bat not found. Install VS BuildTools VC++ x64." }
Write-Host "Using vcvars: $vcvars"

# Phase 0 source set
$sources = @( Join-Path $srcDir "astro_phase0.cpp" )
$srcArg = ($sources | ForEach-Object { '"' + $_ + '"' }) -join " "

# cl.exe command line
$clCmd = 'cl /nologo /LD /O2 /std:c++17 /MD /EHsc /DASTRO_FLASH_BUILD ' +
         '/I "' + $incDir + '" ' + $srcArg + ' ' +
         '/link /OUT:"' + $outDll + '" bcrypt.lib shell32.lib ole32.lib'

$tmpObjDir = Join-Path $PSScriptRoot "build_obj"
if (-not (Test-Path $tmpObjDir)) { New-Item -ItemType Directory -Path $tmpObjDir | Out-Null }

$full = 'call "' + $vcvars + '" && cd /d "' + $tmpObjDir + '" && ' + $clCmd
Write-Host "Compiling..."
cmd /c $full
if ($LASTEXITCODE -ne 0) { throw "cl.exe failed with exit code $LASTEXITCODE" }

if (Test-Path $outDll) {
    $sz = (Get-Item $outDll).Length
    Write-Host ("Built: " + $outDll + " (" + $sz + " bytes)")
} else {
    throw "Build reported success but output DLL is missing."
}
