param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$desktopRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $desktopRoot 'src-tauri\target\release\agent-system.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw '没有找到已有的 release 程序。本入口不会自动编译，请在需要时明确安排编译。'
}
$program = Get-Item -LiteralPath $executable
if ($CheckOnly) {
    [PSCustomObject]@{
        Executable = $program.FullName
        Version = $program.VersionInfo.ProductVersion
        BuiltAt = $program.LastWriteTime
        BuildsApplication = $false
    }
    return
}
Start-Process -FilePath $program.FullName -WorkingDirectory $program.DirectoryName -WindowStyle Normal
