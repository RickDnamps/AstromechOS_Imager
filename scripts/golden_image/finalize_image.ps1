# finalize_image.ps1 -- Copy + SHA256 + sidecar for a Golden Image.
#
# Runs ON THE PC IN POWERSHELL. After pishrink produced K:\<role>_golden.img.gz
# (via wsl_pishrink.sh), this script:
#   1. Copies K:\<role>_golden.img.gz -> J:\R2-D2_Build\images\
#      with the canonical naming AstromechOS_<Role>_<DD-MM-YYYY>.img.gz
#   2. Computes SHA256 of the destination file
#   3. Writes the .sha256 sidecar in standard sha256sum format
#      (<lowercase-hex>  <basename>)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File finalize_image.ps1 -Role master
#   powershell -ExecutionPolicy Bypass -File finalize_image.ps1 -Role slave
#
# See docs/GOLDEN_IMAGE_BUILD.md for the full workflow.

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('master','slave')]
    [string]$Role,

    [string]$SourceDrive = 'K:',
    [string]$DestDir     = 'J:\R2-D2_Build\images',
    [string]$Date        = (Get-Date -Format 'dd-MM-yyyy')
)

$ErrorActionPreference = 'Stop'

# Canonical names
$RoleCap = (Get-Culture).TextInfo.ToTitleCase($Role)  # master -> Master
$SrcImg  = Join-Path $SourceDrive "${Role}_golden.img.gz"
$DstName = "AstromechOS_${RoleCap}_${Date}.img.gz"
$DstImg  = Join-Path $DestDir $DstName
$DstSha  = "${DstImg}.sha256"

Write-Host "=== finalize_image.ps1 role=$Role date=$Date ===" -ForegroundColor Cyan

# --- 1. Verify source ---
if (-not (Test-Path $SrcImg)) {
    Write-Host "ERROR: source $SrcImg not found." -ForegroundColor Red
    Write-Host "       Did you run wsl_pishrink.sh ${Role}_golden.img first?"
    exit 1
}
$srcSize = (Get-Item $SrcImg).Length
Write-Host "  Source: $SrcImg ($srcSize bytes)"

# --- 2. Verify destination dir ---
if (-not (Test-Path $DestDir)) {
    Write-Host "  Creating $DestDir"
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

# --- 3. Copy ---
Write-Host ""
Write-Host "[1/3] Copy to $DstImg" -ForegroundColor Yellow
Copy-Item -Path $SrcImg -Destination $DstImg -Force
$dstSize = (Get-Item $DstImg).Length
if ($srcSize -ne $dstSize) {
    Write-Host "  ERROR: copy size mismatch ($srcSize vs $dstSize)" -ForegroundColor Red
    exit 1
}
Write-Host "  done ($dstSize bytes)" -ForegroundColor Green

# --- 4. Compute SHA256 (Get-FileHash is fast on NVMe ~7s for 1.3 GB) ---
Write-Host ""
Write-Host "[2/3] Compute SHA256" -ForegroundColor Yellow
$startTime = Get-Date
$hash = (Get-FileHash -Path $DstImg -Algorithm SHA256).Hash.ToLower()
$elapsed = ((Get-Date) - $startTime).TotalSeconds
Write-Host ("  hash: {0}" -f $hash)
Write-Host ("  computed in {0:N1}s" -f $elapsed) -ForegroundColor Green

# --- 5. Write sidecar in sha256sum format ---
# Standard format: "<hex>  <basename>" (two spaces between).
# The binary-mode marker (*) is optional and not used by most tools.
Write-Host ""
Write-Host "[3/3] Write .sha256 sidecar" -ForegroundColor Yellow
$sidecarLine = "$hash  $DstName"
Set-Content -Path $DstSha -Value $sidecarLine -Encoding ascii -NoNewline
Add-Content -Path $DstSha -Value "`n" -Encoding ascii
Write-Host "  $DstSha"
Write-Host "  content: $(Get-Content $DstSha -Raw)" -ForegroundColor Green

# --- 6. Summary ---
Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Get-ChildItem $DestDir -Filter "AstromechOS_${RoleCap}_${Date}*" | Format-Table Name, Length, LastWriteTime -AutoSize
