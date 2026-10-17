$ErrorActionPreference = 'Stop'
$desktopRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $desktopRoot
$nodeCandidate = Get-Command node -ErrorAction SilentlyContinue
$nodeDirectory = if ($nodeCandidate) { Split-Path -Parent $nodeCandidate.Source } else { $null }
if (-not $nodeDirectory -or -not (Test-Path -LiteralPath (Join-Path $nodeDirectory 'npm.cmd'))) {
    $portable = Get-ChildItem -LiteralPath (Join-Path $repositoryRoot '.setup') -Directory -Filter 'node-v24.*-win-x64' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($portable) { $nodeDirectory = $portable.FullName }
}
if (-not $nodeDirectory) { throw '请先安装 Node.js 24（含 npm），配置见 desktop/README.md。' }
$env:PATH = $nodeDirectory + ';' + (Join-Path $env:USERPROFILE '.cargo\bin') + ';' + $env:PATH
$nodeVersion = & (Join-Path $nodeDirectory 'node.exe') --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v24\.') { throw '新版开发环境需要 Node.js 24。' }
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw '请先安装 Rust MSVC 工具链，配置见 desktop/README.md。' }
Push-Location -LiteralPath $desktopRoot
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
    & npm.cmd run desktop
    exit $LASTEXITCODE
} finally { Pop-Location }
