<#
.SYNOPSIS
  new-project-memory.ps1 - give a code repository its own memory tier (templates\project-memory\README.md).

.EXAMPLE
  scripts\new-project-memory.ps1 C:\path\to\my-app
  scripts\new-project-memory.ps1 C:\src\repo my-project-name --update

  A thin wrapper: the scaffold itself is scripts\new_project_memory.py, one implementation for every
  platform (the shell and PowerShell copies drifted apart, recheck 08-F3..F10). Python 3 is needed
  anyway: the memory guard is Python. No param() block on purpose, so --update reaches Python as is.
#>
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'new_project_memory.py'
foreach ($c in @('py', 'python', 'python3')) {
  $cmd = Get-Command $c -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { continue }
  $pre = @()
  if ($c -eq 'py') { $pre = @('-3') }
  # The Windows Store alias for python is on PATH and runs nothing: check that it really is Python 3.
  & $cmd.Source @pre -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' 2>$null
  if ($LASTEXITCODE -ne 0) { continue }
  & $cmd.Source @pre $script @args
  exit $LASTEXITCODE
}
[Console]::Error.WriteLine('ERROR: Python 3 is required (install it from python.org, then rerun)')
exit 1
