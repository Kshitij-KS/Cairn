<#
.SYNOPSIS
  sync-memory.ps1 - git sync for the shared AI-agent memory (cairn or a project's memory/).
  Windows equivalent of sync-memory.sh. Windows PowerShell 5.1 and PowerShell 7+.

.DESCRIPTION
  scripts\sync-memory.ps1 pre      before a session: pull --rebase --autostash, register with
                                   Basic Memory, refresh skill copies, print a 1-line summary
  scripts\sync-memory.ps1 post     after a session: commit this tier's changes, pull --rebase, push
  scripts\sync-memory.ps1 status   dirty files, ahead/behind, registration state

  Exit codes: 0 ok, 1 error, 2 conflict, 3 secret, 4 access denied, 5 invalid note,
              6 policy cannot be enforced (guard or Python missing), 7 the push was refused because
              the branch is protected (sync-memory.py then opens a pull request), 75 another sync
              holds the lock.

  THIS FILE MUST STAY PURE ASCII. Windows PowerShell 5.1 reads a BOM-less file as Windows-1252, and
  one em dash broke parsing for everyone on Windows (audit 06-F2). tools/test_sync.py enforces it.

  2026-09 audit fixes: the git wrapper no longer calls itself and forwards every argument
  (06-F3); a missing guard or interpreter blocks the commit (06-F4); commits are built in a
  temporary index holding only this tier (06-F1, 06-F11); autostash conflicts stop with exit 2
  (06-F5); unpushed non-memory commits are never pushed (06-F6); detached HEAD is refused (06-F8);
  pull and push use the configured upstream (06-F9); a busy lock is exit 75 (06-F7).

  Env: MEMORY_SYNC_QUIET=1, MEMORY_SYNC_NO_PUSH=1, MEMORY_AGENT=<name>, MEMORY_SYNC_REMOTE (default
  origin), MEMORY_SYNC_LOCK_HELD=1 (set by sync-memory.py, which holds the lock itself),
  MEMORY_SYNC_DIRECT_PUSH=0 (commit and rebase, then leave the push to sync-memory.py's
  pull-request mode).
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)][ValidateSet('pre', 'post', 'status')][string]$Mode = 'pre'
)
$Mode = $Mode.ToLowerInvariant()

# 'Continue', not 'Stop': on Windows PowerShell 5.1 a native command writing to stderr under
# 2>&1 with EAP=Stop raises NativeCommandError. Exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'
# git writes UTF-8. Windows PowerShell decodes native output with the console code page unless told
# otherwise, which turned non-ASCII paths into different strings before any check saw them.
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$Remote = 'origin'
if ($env:MEMORY_SYNC_REMOTE) { $Remote = $env:MEMORY_SYNC_REMOTE }
$Quiet = ($env:MEMORY_SYNC_QUIET -eq '1')

function Log([string]$m)  { if (-not $Quiet) { [Console]::Out.WriteLine($m) } }
function Warn([string]$m) { [Console]::Error.WriteLine("sync-memory: WARN $m") }
function Die([string]$m, [int]$code = 1) { [Console]::Error.WriteLine("sync-memory: ERROR $m"); exit $code }

# The application, resolved once. A function named Git calling `& git` used to resolve to ITSELF
# (06-F3), so every git call failed.
$GitCmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $GitCmd) { Die 'git is not installed' }
$script:GitExe = $GitCmd.Source

# Run git with EVERY argument forwarded. No param() block on purpose: with one, PowerShell bound
# `-A` in `add -A` to a parameter instead of passing it to git (06-F3). Returns stdout+stderr lines;
# $script:GitExit holds the exit code.
function Invoke-GitNative {
  # core.quotePath=false: a quoted non-ASCII path matched no tier or secret pattern (recheck U1).
  $out = & $script:GitExe -c core.quotePath=false @args 2>&1
  $script:GitExit = $LASTEXITCODE
  return @($out | ForEach-Object { "$_" })
}

# ---------------------------------------------------------------- manifest + repo discovery
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$NotesRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path.TrimEnd('\', '/')
$Manifest  = Join-Path $NotesRoot (Join-Path '.basic-memory' 'project.json')
if (-not (Test-Path $Manifest)) { Die "manifest not found: $Manifest" }
try { $m = Get-Content $Manifest -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop } catch { Die "cannot parse $Manifest : $_" }
$ProjectName = [string]$m.name
$ProjectKind = 'team'
if ($m.kind) { $ProjectKind = [string]$m.kind }
if (-not $ProjectName) { Die "manifest has no name: $Manifest" }

$RepoRoot = Invoke-GitNative -C $NotesRoot rev-parse --show-toplevel | Select-Object -First 1
if ($script:GitExit -ne 0 -or -not $RepoRoot) { Die "$NotesRoot is not inside a git repository" }
$RepoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd('\', '/')
Set-Location $RepoRoot

$nr = $NotesRoot.Replace('\', '/'); $rr = $RepoRoot.Replace('\', '/')
if ($nr -ieq $rr) { $RelNotes = '.' }
elseif ($nr.StartsWith($rr + '/', [System.StringComparison]::OrdinalIgnoreCase)) { $RelNotes = $nr.Substring($rr.Length + 1) }
else { Die "notes root $NotesRoot is outside repo $RepoRoot" }
$Tag = "[$ProjectName]"

$Branch = Invoke-GitNative symbolic-ref -q --short HEAD | Select-Object -First 1
if ($script:GitExit -ne 0) { $Branch = '' }
Invoke-GitNative remote get-url $Remote | Out-Null
$HasRemote = ($script:GitExit -eq 0)
$Upstream = Invoke-GitNative rev-parse --abbrev-ref --symbolic-full-name '@{u}' | Select-Object -First 1
$HasUpstream = ($script:GitExit -eq 0 -and $Upstream)
if (-not $Branch -and $Mode -ne 'status') {
  Die 'HEAD is detached; check out your branch (git switch main) and run sync again' 1
}

# ---------------------------------------------------------------- guards
$GitDir = Invoke-GitNative rev-parse --absolute-git-dir | Select-Object -First 1
function RebaseInProgress { (Test-Path (Join-Path $GitDir 'rebase-merge')) -or (Test-Path (Join-Path $GitDir 'rebase-apply')) -or (Test-Path (Join-Path $GitDir 'MERGE_HEAD')) }
function Conflicted { Invoke-GitNative diff --name-only '--diff-filter=U' | Where-Object { $_ } }

function ReportConflict {
  [Console]::Error.WriteLine("`n$Tag MERGE CONFLICT - sync stopped. Nothing was force-pushed or auto-resolved.")
  [Console]::Error.WriteLine('Conflicted files:')
  Conflicted | ForEach-Object { [Console]::Error.WriteLine("  - $_") }
  [Console]::Error.WriteLine("`nResolve by hand, then:`n  git add <files>; git rebase --continue; then run sync post again")
  [Console]::Error.WriteLine("Or undo the pull entirely:`n  git rebase --abort")
  exit 2
}

if (RebaseInProgress) {
  [Console]::Error.WriteLine("$Tag a rebase/merge is already in progress - resolve it before syncing.")
  Conflicted | ForEach-Object { [Console]::Error.WriteLine("  - $_") }
  [Console]::Error.WriteLine('  git add <files>; git rebase --continue    # or: git rebase --abort')
  exit 2
}

# Lock. sync-memory.py holds it across pre + compile + expire and says so (06-F7).
$LockDir = $null
if ($env:MEMORY_SYNC_LOCK_HELD -ne '1' -and $Mode -ne 'status') {
  $LockDir = Join-Path $GitDir 'sync-memory.lock'
  try { New-Item -ItemType Directory -Path $LockDir -ErrorAction Stop | Out-Null }
  catch {
    # Stale when its owner is a process on this machine that is gone, or when it is 30 minutes old
    # and its owner is not known to be alive (06-F7: age alone freed a slow, live sync's lock).
    $item = Get-Item $LockDir -ErrorAction SilentlyContinue
    $owner = ''
    try { $owner = [string](Get-Content (Join-Path $LockDir 'owner') -Raw -ErrorAction Stop) } catch { }
    $stale = $false
    if ($owner -match 'pid=(\d+)' ) {
      $opid = [int]$Matches[1]
      $ohost = ''
      if ($owner -match 'host=(\S+)') { $ohost = $Matches[1] }
      if ($ohost -and $ohost -eq [Environment]::MachineName) {
        $stale = -not (Get-Process -Id $opid -ErrorAction SilentlyContinue)
      } elseif ($item -and $item.LastWriteTime -lt (Get-Date).AddMinutes(-30)) { $stale = $true }
    } elseif ($item -and $item.LastWriteTime -lt (Get-Date).AddMinutes(-30)) { $stale = $true }
    $tomb = "$LockDir.stale-$PID"
    $moved = $false
    if ($stale) { try { Rename-Item -Path $LockDir -NewName (Split-Path -Leaf $tomb) -ErrorAction Stop; $moved = $true } catch { } }
    if ($moved) {
      Remove-Item $tomb -Recurse -Force -ErrorAction SilentlyContinue
      New-Item -ItemType Directory -Path $LockDir -ErrorAction SilentlyContinue | Out-Null
    } else {
      $LockDir = $null
      [Console]::Error.WriteLine("$Tag another sync is running; not syncing now.")
      exit 75
    }
  }
  Set-Content -Path (Join-Path $LockDir 'owner') -Value ("pid=$PID host=" + [Environment]::MachineName + " started=" + (Get-Date).ToUniversalTime().ToString('s')) -ErrorAction SilentlyContinue
}

$TmpIndex = $null
try {

# ---------------------------------------------------------------- helpers
$script:Pulled = 0; $script:Registered = 'n/a'

function PullRebase {
  if (-not $HasRemote)   { Warn "no remote '$Remote' - working offline"; return }
  if (-not $HasUpstream) { Warn "branch '$Branch' has no upstream - skipping pull (first push will set it)"; return }
  $before = Invoke-GitNative rev-parse HEAD | Select-Object -First 1
  # No remote/branch arguments: git uses the CONFIGURED upstream (06-F9).
  $out = Invoke-GitNative pull --rebase --autostash --quiet
  if ($script:GitExit -ne 0) {
    if ((RebaseInProgress) -or (Conflicted)) { ReportConflict }
    $out | ForEach-Object { [Console]::Error.WriteLine($_) }
    Die 'git pull --rebase failed (network? auth?). Memory may be stale.'
  }
  # A failed autostash re-apply leaves conflicts while pull exits 0 (06-F5).
  if (Conflicted) { ReportConflict }
  $c = Invoke-GitNative rev-list --count "$before..HEAD" | Select-Object -First 1
  if ($c -match '^\d+$') { $script:Pulled = [int]$c } else { $script:Pulled = 0 }
}

function EnsureRegistered {
  $bm = Get-Command basic-memory -ErrorAction SilentlyContinue
  if (-not $bm) { $bm = Get-Command bm -ErrorAction SilentlyContinue }
  if (-not $bm) { Warn 'basic-memory not on PATH - skipped project registration (README step 2)'; return }
  $list = (& $bm.Source project list --json 2>$null) -join "`n"
  if ($list -match ('"name"\s*:\s*"' + [regex]::Escape($ProjectName) + '"')) { $script:Registered = 'yes'; return }
  & $bm.Source project add $ProjectName $NotesRoot 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { $script:Registered = 'added'; Log "$Tag registered Basic Memory project '$ProjectName' -> $NotesRoot" }
  else { $script:Registered = 'failed'; Warn "could not register project '$ProjectName' (run: basic-memory project add $ProjectName `"$NotesRoot`")" }
}

function RefreshSkillCopies {
  $canonical = Join-Path $NotesRoot '.agents/skills/team-memory/SKILL.md'
  if (-not (Test-Path $canonical)) { return }
  foreach ($dest in @((Join-Path $RepoRoot '.claude/skills/team-memory/SKILL.md'), (Join-Path $RepoRoot '.kiro/skills/team-memory/SKILL.md'))) {
    if ((Test-Path $dest) -and (Get-Item $dest).LinkType) { continue }
    $same = (Test-Path $dest) -and ((Get-FileHash $canonical).Hash -eq (Get-FileHash $dest).Hash)
    if (-not $same) {
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
      Copy-Item $canonical $dest -Force
      Log "$Tag refreshed skill copy $($dest.Substring($RepoRoot.Length + 1))"
    }
  }
}

$GuardPath = Join-Path $NotesRoot 'scripts/memory_guard.py'
$script:PythonExe = $null
$script:PythonPre = @()
function Find-Python {
  foreach ($c in @('python3', 'python', 'py')) {
    $exe = Get-Command $c -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $exe) { continue }
    & $exe.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $script:PythonExe = $exe.Source; $script:PythonPre = @(); return $true }
  }
  $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($uv) { $script:PythonExe = $uv.Source; $script:PythonPre = @('run', '-q', '--script'); return $true }
  return $false
}
function Require-Guard {
  # FAIL CLOSED (06-F4): no guard or no interpreter means no commit.
  if (-not (Test-Path $GuardPath)) { Die "memory_guard.py is missing ($GuardPath): the policy cannot be enforced, so nothing is committed" 6 }
  if (-not (Find-Python)) { Die 'no Python 3.9+ found (python3, python, py or uv): the policy cannot be enforced, so nothing is committed' 6 }
}
# Runs the guard; its stdout goes straight to the console (never into a return value) and the
# exit code lands in $script:GuardExit. No param() block, for the same reason as Invoke-GitNative.
function Invoke-Guard {
  $all = @($script:PythonPre) + @($GuardPath, '--notes-root', $NotesRoot) + @($args)
  & $script:PythonExe @all | ForEach-Object { if (-not $script:GuardSilent) { [Console]::Out.WriteLine("$_") } }
  $script:GuardExit = $LASTEXITCODE
}

function SecretGuard {
  # Runs against the temporary index: exactly the tree that will be committed.
  $names = Invoke-GitNative diff --cached --name-only | Where-Object { $_ -match '(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$|id_rsa|credentials\.json$' }
  if ($names) {
    [Console]::Error.WriteLine("$Tag refusing to commit files that look like secrets:"); $names | ForEach-Object { [Console]::Error.WriteLine("  $_") }
    exit 3
  }
  $added = Invoke-GitNative diff --cached '-U0' | Where-Object { $_ -match '^\+' -and $_ -match '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' }
  if ($added) {
    [Console]::Error.WriteLine("$Tag refusing to commit: the change contains what looks like an API key / private key:"); $added | ForEach-Object { [Console]::Error.WriteLine("  $_") }
    exit 3
  }
}

function Outside-Tier([string[]]$paths) {
  if ($RelNotes -eq '.') { return @() }
  return @($paths | Where-Object { $_ -and -not $_.StartsWith("$RelNotes/") })
}

# ---------------------------------------------------------------- modes
switch ($Mode) {
  'pre' {
    PullRebase
    EnsureRegistered
    RefreshSkillCopies
    $recent = Invoke-GitNative log '--since=7 days ago' --name-only '--pretty=format:' -- $RelNotes |
      Where-Object { $_ -match '(^|/)(context|decisions|projects|log)/.*\.md$' -and $_ -notmatch 'CHANGELOG\.md' } | Select-Object -Unique -First 5
    $recentStr = 'nothing in 7 days'
    if ($recent) { $recentStr = $recent -join ' ' }
    $sha = Invoke-GitNative rev-parse --short HEAD | Select-Object -First 1
    [Console]::Out.WriteLine("$Tag memory synced: $Branch@$sha, pulled $($script:Pulled) commit(s), Basic Memory project $($script:Registered). Recently changed: $recentStr")
    $dirs = @('context', 'decisions', 'projects') | ForEach-Object { Join-Path $NotesRoot $_ } | Where-Object { Test-Path $_ }
    $stale = 0
    if ($dirs) { $stale = @(Get-ChildItem -Path $dirs -Filter *.md -Recurse -ErrorAction SilentlyContinue | Select-String -Pattern '^review_needed:' -List).Count }
    if ($stale -gt 0) {
      [Console]::Out.WriteLine("$Tag $stale note(s) carry review_needed after a planning change: treat them as possibly stale and prefer the note they point at.")
    }
  }

  'post' {
    Require-Guard
    # Build the commit in a TEMPORARY index: HEAD plus this tier's working-tree changes, nothing
    # else. The user's own index is never staged into, reset or committed (06-F1, 06-F11).
    $TmpIndex = Join-Path $GitDir ("sync-memory.index." + $PID)
    $env:GIT_INDEX_FILE = $TmpIndex
    Invoke-GitNative rev-parse --verify -q HEAD | Out-Null
    if ($script:GitExit -eq 0) { Invoke-GitNative read-tree HEAD | Out-Null } else { Invoke-GitNative read-tree --empty | Out-Null }
    if ($script:GitExit -ne 0) { Die 'could not prepare the sync index' }
    Invoke-GitNative add -A -- $RelNotes | Out-Null
    if ($script:GitExit -ne 0) { Die 'git add failed' }
    $committed = $false
    Invoke-GitNative diff --cached --quiet | Out-Null
    if ($script:GitExit -eq 0) { Log "$Tag nothing to commit." }
    else {
      # Attribution is written from the git identity, never from what the agent claims.
      $script:GuardSilent = $true; Invoke-Guard stamp --staged; $script:GuardSilent = $false
      if ($script:GuardExit -ne 0) { Die 'guard stamp failed' 6 }
      Invoke-GitNative add -A -- $RelNotes | Out-Null
      # The gate. Same code CI runs, so this cannot pass here and fail there.
      Invoke-Guard check --staged --quiet
      $rc = $script:GuardExit
      if ($rc -ne 0) {
        switch ($rc) {
          3 { [Console]::Error.WriteLine("$Tag blocked: a secret would have been committed. Nothing was written.") }
          4 { [Console]::Error.WriteLine("$Tag blocked: this change is above your level. Write it as a proposal instead (log/proposals/).") }
          6 { [Console]::Error.WriteLine("$Tag blocked: the policy could not be loaded, so nothing is committed.") }
          default { [Console]::Error.WriteLine("$Tag blocked: the note did not pass validation. Fix the findings above and retry.") }
        }
        exit $rc
      }
      SecretGuard
      $staged = @(Invoke-GitNative diff --cached --name-only | Where-Object { $_ })
      if ((Outside-Tier $staged).Count -gt 0) { Die "internal: the sync index holds paths outside $RelNotes; nothing committed" }
      $n = $staged.Count
      $files = ($staged | Select-Object -First 3) -join ', '
      if ($n -gt 3) { $files += ", +$($n - 3) more" }
      $agent = 'unknown'
      if ($env:MEMORY_AGENT) { $agent = $env:MEMORY_AGENT } elseif ($env:CLAUDE_CODE_ENTRYPOINT) { $agent = 'claude-code' } elseif ($env:KIRO_AGENT) { $agent = 'kiro' }
      # same default as memory_guard.Ctx: an agent runtime's marker means agent (trailer must match the gate)
      $markers = @($env:CLAUDE_CODE_SESSION_ID, $env:CLAUDECODE, $env:CLAUDE_CODE_ENTRYPOINT, $env:KIRO_AGENT, $env:CURSOR_AGENT, $env:MEMORY_AGENT) | Where-Object { $_ }
      $actor = 'human'
      if ($env:MEMORY_ACTOR_KIND) { $actor = $env:MEMORY_ACTOR_KIND } elseif ($markers) { $actor = 'agent' }
      $hostName = $env:COMPUTERNAME
      if (-not $hostName) { $hostName = [System.Net.Dns]::GetHostName() }
      Invoke-GitNative commit --quiet --no-verify -m "memory: $n file(s) - $files" -m "Sync-Actor: $actor" -m "Sync-Agent: $agent" -m "Sync-Host: $hostName" | Out-Null
      if ($script:GitExit -ne 0) { Die 'git commit failed (is user.name / user.email configured?)' }
      $committed = $true
      Log "$Tag committed $n file(s)."
    }
    Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
    Remove-Item $TmpIndex -Force -ErrorAction SilentlyContinue
    $TmpIndex = $null
    # Bring the user's real index in line with the new commit for this tier only.
    if ($committed) { Invoke-GitNative reset -q -- $RelNotes | Out-Null }
    if ($env:MEMORY_SYNC_NO_PUSH -eq '1') { Log "$Tag push skipped (MEMORY_SYNC_NO_PUSH=1)"; exit 0 }
    if (-not $HasRemote) { Warn "no remote '$Remote' - commit kept locally"; exit 0 }
    if ($HasUpstream) {
      $ahead = Invoke-GitNative rev-list --count '@{u}..HEAD' | Select-Object -First 1
      if ($ahead -eq '0') { Log "$Tag nothing to push."; exit 0 }
      # Push only memory work (06-F6).
      $unpushed = @(Invoke-GitNative log '--format=' --name-only '@{u}..HEAD' | Where-Object { $_ } | Sort-Object -Unique)
      $outside = Outside-Tier $unpushed
      if ($outside.Count -gt 0) {
        [Console]::Error.WriteLine("$Tag not pushing: unpushed commits change files outside ${RelNotes}:")
        $outside | Select-Object -First 5 | ForEach-Object { [Console]::Error.WriteLine("  - $_") }
        [Console]::Error.WriteLine("$Tag push those yourself (the memory commit is kept locally and will go with them).")
        exit 0
      }
      PullRebase
      if ($env:MEMORY_SYNC_DIRECT_PUSH -eq '0') { Log "$Tag committed locally; sync-memory.py opens the pull request."; exit 0 }
      $slash = $Upstream.IndexOf('/')
      $upRemote = $Upstream.Substring(0, $slash); $upBranch = $Upstream.Substring($slash + 1)
      $out = Invoke-GitNative push --quiet $upRemote "HEAD:$upBranch"
      if ($script:GitExit -ne 0) {
        if (($out -join "`n") -match '(?i)protected branch|GH006|GH013|repository rule') {
          $out | ForEach-Object { [Console]::Error.WriteLine($_) }
          [Console]::Error.WriteLine("$Tag $upBranch is protected: not pushing directly. The commit is kept locally.")
          exit 7
        }
        PullRebase
        $out2 = Invoke-GitNative push --quiet $upRemote "HEAD:$upBranch"
        if ($script:GitExit -ne 0) { ($out + $out2) | ForEach-Object { [Console]::Error.WriteLine($_) }; Die 'git push rejected. Not forcing. Fix and run sync post again.' }
      }
      Log "$Tag pushed $Branch -> $Upstream."
    } else {
      if (-not $committed) { Log "$Tag nothing to push."; exit 0 }
      $all = @(Invoke-GitNative log '--format=' --name-only HEAD | Where-Object { $_ } | Sort-Object -Unique)
      if ((Outside-Tier $all).Count -gt 0) { Warn "branch '$Branch' has no upstream and holds non-memory commits; not pushing"; exit 0 }
      $out = Invoke-GitNative push --quiet -u $Remote $Branch
      if ($script:GitExit -ne 0) { $out | ForEach-Object { [Console]::Error.WriteLine($_) }; Die 'initial push failed' }
      Log "$Tag pushed $Branch -> $Remote."
    }
  }

  'status' {
    [Console]::Out.WriteLine("$Tag repo=$RepoRoot tier=$ProjectKind notes=$RelNotes branch=$Branch remote=$HasRemote upstream=$HasUpstream")
    if ($HasUpstream) {
      Invoke-GitNative fetch --quiet $Remote | Out-Null
      $lr = Invoke-GitNative rev-list --left-right --count '@{u}...HEAD' | Select-Object -First 1
      if ($lr) { $p = $lr -split '\s+'; [Console]::Out.WriteLine("ahead/behind upstream: behind=$($p[0]) ahead=$($p[1])") }
    }
    [Console]::Out.WriteLine('uncommitted memory changes:')
    Invoke-GitNative status --porcelain -- $RelNotes | ForEach-Object { [Console]::Out.WriteLine("  $_") }
  }
}
exit 0

} finally {
  if ($TmpIndex) { Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue; Remove-Item $TmpIndex -Force -ErrorAction SilentlyContinue }
  if ($LockDir) { Remove-Item $LockDir -Recurse -Force -ErrorAction SilentlyContinue }
}
