# process_image.ps1 - All-in-one Golden Image processing: pishrink + move + sha256.
#
# Replaces wsl_pishrink.sh + finalize_image.ps1 with a single command.
#
# Usage:
#   & "J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\process_image.ps1" -Role master
#   & "J:\R2-D2_Build\AstroMechOS_Imager\scripts\golden_image\process_image.ps1" -Role slave -SrcDrive L:

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('master','slave')]
    [string]$Role,

    [string]$SrcDrive = 'L:',
    [string]$DestDir  = 'J:\R2-D2_Build\images',
    [string]$Date     = (Get-Date -Format 'dd-MM-yyyy')
)

$ErrorActionPreference = 'Stop'

$RoleCap = (Get-Culture).TextInfo.ToTitleCase($Role)
$ImgName = "AstromechOS_${RoleCap}_${Date}.img"
$GzName  = "${ImgName}.gz"
$SrcImg  = Join-Path $SrcDrive $ImgName
$SrcGz   = Join-Path $SrcDrive $GzName
$DstGz   = Join-Path $DestDir $GzName
$DstSha  = "${DstGz}.sha256"

$ScriptPath = "/mnt/j/R2-D2_Build/AstroMechOS_Imager/scripts/golden_image/wsl_pishrink.sh"

Write-Host "=== process_image.ps1 role=$Role date=$Date ===" -ForegroundColor Cyan
Write-Host "  Source : $SrcImg"
Write-Host "  Output : $DstGz"
Write-Host ""

if (-not (Test-Path $SrcImg)) {
    Write-Host "ERROR: source not found: $SrcImg" -ForegroundColor Red
    exit 1
}
$srcSizeGB = [math]::Round((Get-Item $SrcImg).Length / 1GB, 2)
Write-Host ("  Raw .img size: {0} GB" -f $srcSizeGB)

# [1/3] Pishrink inside WSL Debian
Write-Host ""
Write-Host "[1/3] Pishrink via WSL Debian (15-35 min)" -ForegroundColor Yellow
$wslCmd = "mkdir -p /mnt/k && (mountpoint -q /mnt/k || mount -t drvfs ${SrcDrive} /mnt/k) && bash ${ScriptPath} ${ImgName}"
wsl -d Debian -u root -- bash -c $wslCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pishrink exit $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

if (-not (Test-Path $SrcGz)) {
    Write-Host "ERROR: pishrink ok but $SrcGz not found." -ForegroundColor Red
    exit 1
}

# [2/3] Move to DestDir
Write-Host ""
Write-Host "[2/3] Move to $DestDir" -ForegroundColor Yellow
if (-not (Test-Path $DestDir)) { New-Item -ItemType Directory -Path $DestDir -Force | Out-Null }
Move-Item -Path $SrcGz -Destination $DstGz -Force
$dstSizeGB = [math]::Round((Get-Item $DstGz).Length / 1GB, 3)
Write-Host ("  Moved ({0} GB)" -f $dstSizeGB) -ForegroundColor Green

# [3/3] SHA256 + sidecar
Write-Host ""
Write-Host "[3/3] SHA256 + sidecar" -ForegroundColor Yellow
$t0 = Get-Date
$hash = (Get-FileHash -Path $DstGz -Algorithm SHA256).Hash.ToLower()
$secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
Write-Host ("  Hash: {0} ({1} s)" -f $hash, $secs)

$line = "$hash  $GzName"
Set-Content -Path $DstSha -Value $line -Encoding ascii -NoNewline
Add-Content -Path $DstSha -Value "`n" -Encoding ascii -NoNewline
Write-Host "  Sidecar: $DstSha" -ForegroundColor Green
Get-Content $DstSha

Write-Host ""
Write-Host ("=== DONE - {0} Golden Image ready ===" -f $RoleCap) -ForegroundColor Green
Write-Host ("    {0} ({1} GB)" -f $DstGz, $dstSizeGB)
Write-Host ("    {0}" -f $DstSha)
