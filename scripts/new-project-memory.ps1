<#
.SYNOPSIS
  new-project-memory.ps1 - give a project repo its own memory tier (see templates\project-memory\README.md).
  Windows equivalent of new-project-memory.sh.

.EXAMPLE
  scripts\new-project-memory.ps1 C:\path\to\my-app
  scripts\new-project-memory.ps1 C:\src\repo my-project-name

  Idempotent: never overwrites an existing file. Existing client configs get a
  <file>.team-memory.suggested sibling and a printed merge hint instead.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Target,
  [Parameter(Position = 1)][string]$Name
)
$ErrorActionPreference = 'Continue'

$CairnRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')).Path.TrimEnd('\')
$Tpl    = Join-Path $CairnRoot 'templates\project-memory'
if (-not (Test-Path $Target -PathType Container)) { Write-Error "ERROR: $Target is not a directory"; exit 1 }
$Target = (Resolve-Path $Target).Path.TrimEnd('\')
$top = (& git -C $Target rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0) { Write-Error "ERROR: $Target is not a git repository (git init first)"; exit 1 }
if ((Resolve-Path $top).Path.TrimEnd('\') -ine $Target) { Write-Error 'ERROR: run against the repo root, not a subfolder'; exit 1 }

$base = Split-Path -Leaf $Target
if (-not $Name) { $Name = ($base.ToLower() -replace '[^a-z0-9]+', '-').Trim('-') }
$Title = ($base -replace '[_-]+', ' ')
$Date  = Get-Date -Format 'yyyy-MM-dd'
if ($Name -eq 'cairn') { Write-Error "ERROR: project name 'cairn' is reserved"; exit 1 }

$created = New-Object System.Collections.Generic.List[string]
$skipped = New-Object System.Collections.Generic.List[string]
$suggested = New-Object System.Collections.Generic.List[string]
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Rel([string]$p) { $p.Substring($Target.Length + 1) }
function Render([string]$src, [string]$dest) {
  if (Test-Path $dest) { $skipped.Add((Rel $dest)); return }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  $txt = [System.IO.File]::ReadAllText($src)
  $txt = $txt.Replace('__PROJECT_NAME__', $Name).Replace('__PROJECT_TITLE__', $Title).Replace('__DATE__', $Date)
  [System.IO.File]::WriteAllText($dest, $txt, $utf8)   # LF preserved, no BOM
  $created.Add((Rel $dest))
}
function RenderOrSuggest([string]$src, [string]$dest) {
  if (Test-Path $dest) { Render $src "$dest.team-memory.suggested"; $suggested.Add((Rel $dest)) } else { Render $src $dest }
}

# 1. memory/ notes + manifest
Get-ChildItem -Path (Join-Path $Tpl 'memory') -Recurse -File -Force | ForEach-Object {
  $rel = $_.FullName.Substring((Join-Path $Tpl 'memory').Length + 1)
  Render $_.FullName (Join-Path $Target (Join-Path 'memory' ($rel -replace '\.tmpl$', '')))
}
# 2. sync scripts + canonical skill
# memory_guard.py and mem.py were not copied before 2026-09-23 (policy was NOT enforced in the project tier).
foreach ($s in 'sync-memory.sh', 'sync-memory.ps1', 'sync-memory.py', 'memory_guard.py', 'mem.py') { Render (Join-Path $CairnRoot "scripts\$s") (Join-Path $Target "memory\scripts\$s") }
Render (Join-Path $CairnRoot 'governance\roles.json') (Join-Path $Target 'memory\governance\roles.json')
Render (Join-Path $CairnRoot '.agents\skills\team-memory\SKILL.md') (Join-Path $Target 'memory\.agents\skills\team-memory\SKILL.md')
# 2b. slash commands, pointed at memory/scripts
Get-ChildItem -Path (Join-Path $CairnRoot '.claude\commands') -Filter *.md -File | ForEach-Object {
  $dest = Join-Path $Target (Join-Path '.claude\commands' $_.Name)
  if (Test-Path $dest) { $skipped.Add((Rel $dest)); return }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
  $txt = [System.IO.File]::ReadAllText($_.FullName).Replace('scripts/mem.py', 'memory/scripts/mem.py')
  [System.IO.File]::WriteAllText($dest, $txt, $utf8); $created.Add((Rel $dest))
}
# 3. client configs
$cc = Join-Path $Tpl 'client-config'
Render          (Join-Path $cc 'cursor-memory.mdc.tmpl')            (Join-Path $Target '.cursor\rules\memory.mdc')
Render          (Join-Path $cc 'kiro-steering-memory.md.tmpl')      (Join-Path $Target '.kiro\steering\memory.md')
Render          (Join-Path $cc 'kiro-hook-session-start.json.tmpl') (Join-Path $Target '.kiro\hooks\memory-session-start.json')
Render          (Join-Path $cc 'kiro-hook-post-task.json.tmpl')     (Join-Path $Target '.kiro\hooks\memory-post-task.json')
RenderOrSuggest (Join-Path $cc 'kiro-mcp.json.tmpl')                (Join-Path $Target '.kiro\settings\mcp.json')
RenderOrSuggest (Join-Path $cc 'mcp.json.tmpl')                     (Join-Path $Target '.mcp.json')
RenderOrSuggest (Join-Path $cc 'cursor-mcp.json.tmpl')              (Join-Path $Target '.cursor\mcp.json')
RenderOrSuggest (Join-Path $cc 'claude-settings.json.tmpl')         (Join-Path $Target '.claude\settings.json')
# 4. CLAUDE.md
$claude = Join-Path $Target 'CLAUDE.md'
$snippet = [System.IO.File]::ReadAllText((Join-Path $cc 'CLAUDE-snippet.md.tmpl')).Replace('__PROJECT_NAME__', $Name).Replace('__PROJECT_TITLE__', $Title)
if (Test-Path $claude) {
  if (-not (Select-String -Path $claude -Pattern '@memory/AGENT-RULES.md' -Quiet)) {
    [System.IO.File]::AppendAllText($claude, $snippet, $utf8); $created.Add('CLAUDE.md (appended)')
  } else { $skipped.Add('CLAUDE.md (import already present)') }
} else { [System.IO.File]::WriteAllText($claude, "# $Title`n$snippet", $utf8); $created.Add('CLAUDE.md') }
# 5. skill copies
foreach ($d in '.claude', '.kiro') { Render (Join-Path $Target 'memory\.agents\skills\team-memory\SKILL.md') (Join-Path $Target "$d\skills\team-memory\SKILL.md") }
# 6. register with Basic Memory
$reg = 'skipped (basic-memory not on PATH)'
$bm = Get-Command basic-memory -ErrorAction SilentlyContinue
if ($bm) {
  $list = (& $bm.Source project list --json 2>$null) -join "`n"
  if ($list -match "`"name`"\s*:\s*`"$([regex]::Escape($Name))`"") { $reg = 'already registered' }
  else {
    & $bm.Source project add $Name (Join-Path $Target 'memory') 2>$null | Out-Null
    $reg = if ($LASTEXITCODE -eq 0) { "registered -> $Target\memory" } else { "FAILED - run: basic-memory project add $Name `"$Target\memory`"" }
  }
}

# ---------------------------------------------------------------- report
Write-Output "`nproject memory for `"$Name`" ($Target)"
Write-Output "  created ($($created.Count)):"; $created | ForEach-Object { "    + $_" }
if ($skipped.Count)   { Write-Output "  left untouched ($($skipped.Count)):"; $skipped | ForEach-Object { "    = $_" } }
if ($suggested.Count) {
  Write-Output '  MERGE BY HAND - these already existed, see the .team-memory.suggested file next to each:'; $suggested | ForEach-Object { "    ! $_" }
  Write-Output '    (add the "basic-memory" server / hooks block; then delete the .suggested file)'
}
Write-Output "  Basic Memory: $reg"
Write-Output "`nnext:`n  cd `"$Target`"; git add -A memory .claude .cursor .kiro .mcp.json CLAUDE.md; git commit -m `"memory: add project memory tier ($Name)`""
Write-Output '  then fill memory\context\overview.md and run: uv run -q --script memory/scripts/sync-memory.py pre'
