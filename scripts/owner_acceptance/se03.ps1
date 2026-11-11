<#
.SYNOPSIS
  SE-03 owner acceptance helper (Windows PowerShell 5.1 or PowerShell 7).

.DESCRIPTION
  Runs ONLY local, read-only-to-your-data checks on the wholly synthetic SE-03 remote-MCP scenario (a fictional owner and agent, in one local process):
    1. preflight (git, Python 3.12+, tested commit),
    2. creates a private virtual environment inside the evidence folder,
    3. installs ONLY the hash-locked dependencies (pip --require-hashes) into that environment,
    4. runs the SE-03 unit/negative/integration tests (a real MCP client over a local TLS test server on 127.0.0.1),
    5. replays the synthetic scenario and compares every outcome and hash with the pinned values.
  It opens a loopback-only test server (127.0.0.1, random port) for a few seconds and never exposes it; it never starts a tunnel, never contacts an identity provider, never reads your SketchUp or client
  files, never needs a secret, and writes only inside -EvidenceDir. Delete that folder to clean up.

.PARAMETER TestedSha
  The full 40-character commit SHA the cloud CI tested (given in docs/stable/owner-handoff/SE-03.md).

.PARAMETER EvidenceDir
  Output folder (default: %USERPROFILE%\se03-evidence). Must be empty or not exist.

.PARAMETER SelfTest
  Only checks this script's own helper functions (used by CI). Touches nothing.
#>
[CmdletBinding()]
param(
    [string]$TestedSha = "0000000000000000000000000000000000000000",
    [string]$EvidenceDir = (Join-Path $env:USERPROFILE "se03-evidence"),
    [switch]$SelfTest
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$Results = New-Object System.Collections.ArrayList

function Add-Result([string]$Step, [string]$Status, [string]$Detail) {
    [void]$Results.Add([pscustomobject]@{ Step = $Step; Status = $Status; Detail = $Detail })
    Write-Host ("[{0}] {1} - {2}" -f $Status, $Step, $Detail)
}

function Protect-Text([string]$Text) {
    # Redact the user's profile path and name so the log is safe to paste.
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $t = $Text
    foreach ($pair in @(@($env:USERPROFILE, "<HOME>"), @($env:USERNAME, "<USER>"), @($env:COMPUTERNAME, "<PC>"))) {
        if ($pair[0] -and $pair[0].Length -ge 3) {
            $t = [regex]::Replace($t, [regex]::Escape($pair[0]), $pair[1], "IgnoreCase")
        }
    }
    return $t
}

function Get-OverallVerdict($Items) {
    $bad = @($Items | Where-Object { $_.Status -eq "FAIL" })
    if ($bad.Count -gt 0) { return "FAIL" }
    $notRun = @($Items | Where-Object { $_.Status -eq "NOT_RUN" })
    if ($notRun.Count -gt 0) { return "NOT_RUN" }
    return "PASS"
}

function Get-AutomatedVerdict($Items) {
    # The owner's manual review row is always NOT_RUN until the owner does it; it must not make
    # the automated part read NOT_RUN when every automated step passed.
    return Get-OverallVerdict @($Items | Where-Object { $_.Step -notlike "owner manual*" })
}

if ($SelfTest) {
    $fake = [pscustomobject]@{ Step = "x"; Status = "PASS"; Detail = "" }
    $manual = [pscustomobject]@{ Step = "owner manual review (receipt.json)"; Status = "NOT_RUN"; Detail = "" }
    if ((Get-AutomatedVerdict @($fake, $manual)) -ne "PASS") { throw "automated verdict must ignore the manual NOT_RUN row" }
    if ((Get-OverallVerdict @($fake, $manual)) -ne "NOT_RUN") { throw "overall verdict must still show NOT_RUN" }
    $failed = [pscustomobject]@{ Step = "x"; Status = "FAIL"; Detail = "" }
    if ((Get-AutomatedVerdict @($failed, $manual)) -ne "FAIL") { throw "automated verdict must show FAIL" }
    if ((Get-OverallVerdict @($fake)) -ne "PASS") { throw "verdict logic broken (PASS)" }
    $fake2 = [pscustomobject]@{ Step = "y"; Status = "FAIL"; Detail = "" }
    if ((Get-OverallVerdict @($fake, $fake2)) -ne "FAIL") { throw "verdict logic broken (FAIL)" }
    $probe = "path " + $env:USERPROFILE + "\secret"
    if ((Protect-Text $probe) -match [regex]::Escape($env:USERPROFILE)) { throw "redaction broken" }
    Write-Host "SE03_SELFTEST=PASS"
    exit 0
}

function Stop-WithFail([string]$Step, [string]$Detail) {
    Add-Result $Step "FAIL" $Detail
    Write-Summary
    exit 1
}

function Write-Summary {
    $verdict = Get-AutomatedVerdict $Results
    $lines = @("SE-03 owner acceptance result", "Tested SHA: $TestedSha", "Verdict (automated part): $verdict", "")
    foreach ($r in $Results) { $lines += ("{0,-8} {1} :: {2}" -f $r.Status, $r.Step, (Protect-Text $r.Detail)) }
    $lines += ""
    $lines += "Manual owner review (receipt.json + real Claude Code / Codex over OAuth, S5 probe): NOT_RUN until you do it."
    if (Test-Path $EvidenceDir) {
        $lines | Set-Content -Path (Join-Path $EvidenceDir "se03-result.txt") -Encoding UTF8
    }
    Write-Host ""
    Write-Host "=== Paste this one line back to the agent ==="
    Write-Host ("SE-03 owner run: automated={0}; sha={1}; manual-review=<PASS|FAIL|NOT_RUN>; notes=<none>" -f $verdict, $TestedSha)
}

# ---- Step 0: location --------------------------------------------------------
$repo = (Get-Location).Path
if (-not (Test-Path (Join-Path $repo "service\app.py"))) {
    Write-Host "STOP: run this from the root of the sibambo-bomc-builder folder (where README.md is)."
    exit 2
}
if ($TestedSha -notmatch '^[0-9a-f]{40}$' -or $TestedSha -eq ("0" * 40)) {
    Write-Host "STOP: pass the real 40-character SHA with -TestedSha (see SE-03.md)."
    exit 2
}

# ---- Step 1: evidence folder ---------------------------------------------------
if ((Test-Path $EvidenceDir) -and (@(Get-ChildItem -Force $EvidenceDir).Count -gt 0)) {
    Write-Host "STOP: $EvidenceDir is not empty. Pick another folder with -EvidenceDir or delete it first."
    exit 2
}
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
Add-Result "evidence folder" "PASS" $EvidenceDir

# ---- Step 2: git + commit ------------------------------------------------------
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Stop-WithFail "git installed" "git not found. Install Git for Windows, then retry." }
$head = (& git rev-parse HEAD).Trim()
$dirty = (& git status --porcelain) -join "`n"
if ($dirty) { Stop-WithFail "clean working tree" "You have local changes. Run: git stash  (or use a fresh clone)." }
& git merge-base --is-ancestor $TestedSha $head 2>$null
if ($LASTEXITCODE -ne 0) { Stop-WithFail "tested commit" "HEAD $head does not contain tested commit $TestedSha." }
$changed = @(& git diff --name-only "$TestedSha..$head")
$outside = @($changed | Where-Object { $_ -notmatch '^(docs/stable/|scripts/owner_acceptance/|.github/workflows/se03-remote-mcp.yml$)' })
if ($outside.Count -gt 0) { Stop-WithFail "only docs/helper changed after tested commit" ("Unexpected changes: " + ($outside -join ", ")) }
Add-Result "tested commit" "PASS" "HEAD=$head contains $TestedSha (docs/helper-only delta)"

# ---- Step 3: Python 3.12+ ---------------------------------------------------------
$py = $null
foreach ($candidate in @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.14"), @("python"), @("python3"))) {
    $cmd = Get-Command $candidate[0] -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $extra = @()
    if ($candidate.Count -gt 1) { $extra = $candidate[1..($candidate.Count - 1)] }
    $v = & $candidate[0] @extra -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v) {
        $parts = $v.Trim().Split(".")
        if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 12)) { $py = @($candidate[0]) + $extra; break }
    }
}
if (-not $py) { Stop-WithFail "Python 3.12+" "Install Python 3.12 or newer from python.org (tick 'Add to PATH'), open a NEW PowerShell, retry." }
Add-Result "Python 3.12+" "PASS" ("Python " + $v.Trim())

function Invoke-Py([string[]]$Arguments, [string]$LogName) {
    $exe = $py[0]
    $pre = @()
    if ($py.Count -gt 1) { $pre = $py[1..($py.Count - 1)] }
    $log = Join-Path $EvidenceDir $LogName
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $exe @pre @Arguments 2>&1 | Out-String
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    (Protect-Text $output) | Set-Content -Path $log -Encoding UTF8
    return $code
}

# ---- Step 4: private venv + the single pinned dependency ------------------------
$venv = Join-Path $EvidenceDir "venv"
if ((Invoke-Py @("-m", "venv", $venv) "log-venv.txt") -ne 0) { Stop-WithFail "create venv" "See log-venv.txt" }
$vpy = Join-Path $venv "Scripts\python.exe"
$py = @($vpy)
if ((Invoke-Py @("scripts/check_hash_lock.py", "service/requirements.lock") "log-hashlock.txt") -ne 0) {
    Stop-WithFail "lock file is fully hashed" "See log-hashlock.txt"
}
Add-Result "lock file is fully hashed" "PASS" "service/requirements.lock"
if ((Invoke-Py @("-m", "pip", "install", "--disable-pip-version-check", "--require-hashes", "-r", "service/requirements.lock") "log-pip.txt") -ne 0) {
    Stop-WithFail "install hash-locked dependencies" "pip failed (network/proxy, or a Python version without wheels? use Python 3.12 or 3.13). See log-pip.txt; retry once, then report FAIL."
}
Add-Result "hash-locked dependencies (mcp 2.3.0)" "PASS" "installed in private venv only, pip --require-hashes"

# ---- Step 5: unit + negative tests --------------------------------------------------
$code = Invoke-Py @("-m", "unittest", "discover", "-s", "tests", "-p", "test_remote_mcp*.py", "-v") "log-unittest.txt"
if ($code -ne 0) { Stop-WithFail "SE-03 unit/negative tests" "See log-unittest.txt" }
Add-Result "SE-03 unit/negative tests" "PASS" "tests/test_remote_mcp.py and tests/test_remote_mcp_guide.py OK"

# ---- Step 6: evidence + hash check ------------------------------------------------------
$out = Join-Path $EvidenceDir "synthetic-remote"
$code = Invoke-Py @("-m", "examples.se03_evidence", "--out-dir", $out, "--check", "docs/stable/owner-handoff/se03-expected.json") "log-evidence.txt"
if ($code -ne 0) { Stop-WithFail "remote-MCP evidence + pinned hashes" "See log-evidence.txt (look for lines starting with FAIL:)" }
Add-Result "remote-MCP evidence + pinned hashes" "PASS" "SE03_RESULT=PASS"

Add-Result "owner manual review (receipt.json)" "NOT_RUN" "Do SOP section 'Review manual' and report PASS or FAIL"

Write-Summary
Write-Host ""
Write-Host "Evidence folder: $EvidenceDir  (open receipt.json)"
exit 0
