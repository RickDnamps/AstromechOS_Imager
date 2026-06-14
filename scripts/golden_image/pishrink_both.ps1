# pishrink_both.ps1 — Official Golden Image pishrink pipeline (Master + Slave).
#
# Reads .img files from SSD (I:), copies to J:\R2-D2_Build\images\, runs pishrink
# inside WSL Debian (-a -z for parallel pigz + auto-expand), generates SHA256 sidecar.
#
# Anti-regression invariants (gravé dans le béton via marathon 2026-06-02→07):
#   - $ExpectedSize is AUTO-DETECTED from (Get-Item).Length on the SSD .img
#     (NEVER hardcode; breaks at every SD size swap)
#   - Uses `wsl -d Debian -u root -- bash -c "cd ... && pishrink ..."` — proven
#     pattern from marathon. Bare `wsl ... pishrink` fails on WSL path translation.
#   - gzip integrity check (`gzip -t`) AFTER pishrink — guards against silent
#     corruption (rare but happened on USB-SATA bridge thermal saturation events).
#   - Intermediate .img on J: removed after gz produced (saves 60+ GB transient).
#
# PREREQS — see ./README.md

$ErrorActionPreference = 'Stop'
$DestDir = 'J:\R2-D2_Build\images'
$SrcDrive = 'I:'
$Date = '13-06-2026'

Write-Host ""
Write-Host "=== I: contents ===" -ForegroundColor Cyan
Get-ChildItem "$SrcDrive\AstromechOS_*.img" -ErrorAction SilentlyContinue | Format-Table Name, @{N='Size_GB';E={[math]::Round($_.Length/1GB,2)}}, LastWriteTime -AutoSize

# Process function inline — anti-regression: auto-detect size from I: source .img file
$roles = @('Master', 'Slave')

foreach ($RoleCap in $roles) {
    $ImgName = "AstromechOS_${RoleCap}_${Date}.img"
    $SrcImgEarly = Join-Path $SrcDrive $ImgName
    if (-not (Test-Path $SrcImgEarly)) {
        Write-Host "ERROR: $SrcImgEarly not found" -ForegroundColor Red
        exit 1
    }
    $ExpectedSize = (Get-Item $SrcImgEarly).Length
    Write-Host "  Auto-detected $RoleCap size: $ExpectedSize bytes ($([math]::Round($ExpectedSize/1GB,2)) GB)" -ForegroundColor DarkCyan
    $GzName  = "${ImgName}.gz"
    $SrcImg  = Join-Path $SrcDrive $ImgName
    $DstImg  = Join-Path $DestDir $ImgName
    $DstGz   = Join-Path $DestDir $GzName
    $DstSha  = "${DstGz}.sha256"

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "=== $RoleCap pishrink ===" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan

    if (-not (Test-Path $SrcImg)) {
        Write-Host "ERROR: $SrcImg not found" -ForegroundColor Red
        exit 1
    }
    $srcSize = (Get-Item $SrcImg).Length
    $srcGB = [math]::Round($srcSize / 1GB, 2)
    if ($srcSize -ne $ExpectedSize) {
        Write-Host "ERROR: size mismatch expected $ExpectedSize got $srcSize" -ForegroundColor Red
        exit 2
    }
    Write-Host "  Source verified: $srcGB GB" -ForegroundColor Green

    # Cleanup stale
    Write-Host "[0/3] Cleanup stale outputs" -ForegroundColor DarkGray
    if (Test-Path $DstGz)  { Remove-Item $DstGz -Force }
    if (Test-Path $DstSha) { Remove-Item $DstSha -Force }
    if (Test-Path $DstImg) { Remove-Item $DstImg -Force }

    # Copy
    Write-Host "[1/3] Copy $SrcImg -> $DstImg" -ForegroundColor Yellow
    $t0 = Get-Date
    Copy-Item -Path $SrcImg -Destination $DstImg -Force
    $cpSecs = [math]::Round(((Get-Date)-$t0).TotalSeconds, 0)
    $dstSize = (Get-Item $DstImg).Length
    if ($dstSize -ne $srcSize) {
        Write-Host "ERROR: copy size mismatch" -ForegroundColor Red
        exit 3
    }
    Write-Host "  Copy OK ($srcGB GB in ${cpSecs}s)"

    # Pishrink
    Write-Host "[2/3] WSL pishrink -a -z" -ForegroundColor Yellow
    $t0 = Get-Date
    wsl -d Debian -u root -- bash -c "cd /mnt/j/R2-D2_Build/images && /usr/local/bin/pishrink -a -z $ImgName"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: pishrink failed exit $LASTEXITCODE" -ForegroundColor Red
        exit 4
    }
    $pSecs = [math]::Round(((Get-Date)-$t0).TotalSeconds, 0)
    Write-Host "  Pishrink OK in ${pSecs}s"

    # gzip integrity check
    wsl -d Debian -u root -- gzip -t "/mnt/j/R2-D2_Build/images/$GzName"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: gzip integrity fail" -ForegroundColor Red
        exit 5
    }

    if (-not (Test-Path $DstGz)) {
        Write-Host "ERROR: $DstGz not found post-pishrink" -ForegroundColor Red
        exit 6
    }
    $gzSize = (Get-Item $DstGz).Length
    $gzGB = [math]::Round($gzSize / 1GB, 2)
    Write-Host "  Output gz: $gzGB GB"

    # Remove intermediate .img
    Remove-Item $DstImg -Force -ErrorAction SilentlyContinue

    # SHA256
    Write-Host "[3/3] SHA256 sidecar" -ForegroundColor Yellow
    $hash = (Get-FileHash -Path $DstGz -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path $DstSha -Value "$hash  $GzName" -Encoding ascii -NoNewline
    Add-Content -Path $DstSha -Value "`n" -Encoding ascii -NoNewline
    Write-Host "  Hash: $hash"

    Write-Host "  $RoleCap raw $srcGB GB -> gz $gzGB GB" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "=== BOTH DONE ===" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Get-ChildItem "$DestDir\AstromechOS_*$Date*" | Sort-Object Name | Format-Table Name, @{N='Size_GB';E={[math]::Round($_.Length/1GB,2)}}, LastWriteTime -AutoSize

# Release WSL's auto-mount of the SSD (/mnt/i) so the operator can unplug the SSD
# without Windows popping "Please insert a disk into drive I:" — that dialog fires
# when a process still holds a now-empty removable drive letter (WSL keeps /mnt/i
# mounted). Safe here: pishrink has finished, nothing else runs in WSL.
Write-Host ""
Write-Host "Releasing WSL drive mounts (wsl --shutdown) — SSD is safe to unplug now." -ForegroundColor DarkGray
wsl --shutdown
