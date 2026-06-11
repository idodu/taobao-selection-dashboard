param(
    [string]$Repository = "idodu/taobao-selection-dashboard"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required."
}

gh auth status --hostname github.com 1>$null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run: gh auth login"
}

$secureKey = Read-Host "Enter ELIM_API_KEY (input is hidden)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "ELIM_API_KEY cannot be empty."
    }

    $plainKey | gh secret set ELIM_API_KEY --repo $Repository
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to save ELIM_API_KEY to GitHub Secrets."
    }
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    $plainKey = $null
    $secureKey.Dispose()
}

Write-Host "ELIM_API_KEY saved. Starting the first full 1688 SKU refresh..."
gh workflow run daily-update.yml --repo $Repository --ref master -f full_refresh=true
if ($LASTEXITCODE -ne 0) {
    throw "Secret was saved, but the workflow could not be started."
}

Start-Sleep -Seconds 3
$runId = gh run list --repo $Repository --workflow daily-update.yml --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId'
if ([string]::IsNullOrWhiteSpace($runId)) {
    throw "Workflow started, but its run ID could not be found."
}

Write-Host "Watching workflow run $runId..."
gh run watch $runId --repo $Repository --exit-status
if ($LASTEXITCODE -ne 0) {
    throw "The first 1688 refresh failed. Inspect the workflow logs for details."
}

Write-Host "1688 refresh and GitHub Pages deployment completed."
