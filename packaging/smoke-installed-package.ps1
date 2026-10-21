param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$InstallDirectory
)

$ErrorActionPreference = "Stop"
$dataDirectory = Join-Path $env:LOCALAPPDATA "OfficeAI"
$markerPath = Join-Path $dataDirectory "installer-smoke-test.marker"

if (Test-Path $dataDirectory) {
    throw "Expected a clean runner without an existing OfficeAI user-data directory"
}
New-Item -ItemType Directory -Force -Path $dataDirectory | Out-Null
Set-Content -Path $markerPath -Value "preserve-user-data" -NoNewline

try {
    $install = Start-Process -FilePath $InstallerPath -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$InstallDirectory`""
    ) -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw "Silent installation failed: $($install.ExitCode)" }

    $app = Join-Path $InstallDirectory "OfficeAI.exe"
    $frontend = Join-Path $InstallDirectory "_internal/frontend/dist/index.html"
    if (-not (Test-Path $app)) { throw "Installed application executable was not found" }
    if (-not (Test-Path $frontend)) { throw "Installed frontend bundle was not found" }

    $smoke = Start-Process -FilePath $app -ArgumentList "--self-test" -PassThru -NoNewWindow
    if (-not $smoke.WaitForExit(30000)) {
        $smoke.Kill()
        throw "Packaged application failed to serve the local UI/API within 30 seconds"
    }
    $smoke.Refresh()
    if ($smoke.ExitCode -ne 0) { throw "Packaged application self-test failed with exit code $($smoke.ExitCode)" }

    $uninstaller = Join-Path $InstallDirectory "unins000.exe"
    if (-not (Test-Path $uninstaller)) { throw "Uninstaller was not installed" }
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw "Silent uninstall failed: $($uninstall.ExitCode)" }
    if (-not (Test-Path $markerPath)) { throw "Uninstall removed the user-data marker" }
}
finally {
    if (Test-Path $markerPath) { Remove-Item $markerPath -Force }
    if ((Test-Path $dataDirectory) -and -not (Get-ChildItem $dataDirectory -Force | Select-Object -First 1)) {
        Remove-Item $dataDirectory -Force
    }
}
