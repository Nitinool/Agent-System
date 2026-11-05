param([switch]$Develop, [switch]$Build, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $appRoot 'bin\task-notes.exe'
if ($Develop -or $Build) {
    $env:PATH = (Join-Path $env:ProgramFiles 'nodejs') + ';' + (Join-Path $env:USERPROFILE '.cargo\bin') + ';' + $env:PATH
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw '请先安装 Node.js 24。' }
    if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) { throw '请先安装 Rust MSVC 工具链和 C++ Build Tools。' }
    Push-Location -LiteralPath $appRoot
    try {
        # Keep this application's build output separate from Agent System.
        $env:CARGO_TARGET_DIR = Join-Path $appRoot 'src-tauri\target'
        if (-not (Test-Path -LiteralPath (Join-Path $appRoot 'node_modules'))) {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw '安装依赖失败。' }
        }
        if ($Develop) { & npm.cmd run desktop }
        else {
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
            & cargo.exe build --manifest-path src-tauri/Cargo.toml --features custom-protocol --locked
        }
        if ($LASTEXITCODE -ne 0) { throw '事项便签构建或开发进程失败。' }
        if ($Build -and -not $Develop) {
            # A later tauri dev build must not replace the standalone executable.
            $outputDirectory = Join-Path $appRoot 'bin'
            New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $env:CARGO_TARGET_DIR 'debug\task-notes.exe') -Destination $executable -Force
        }
    } finally { Pop-Location }
    return
}
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw '未找到事项便签可执行文件。请先运行 todo-desktop\tools\start.ps1 -Build，或双击“开发事项便签.cmd”。'
}
$binary = Get-Item -LiteralPath $executable
if ($CheckOnly) { $binary | Select-Object FullName, LastWriteTime, Length; return }
Start-Process -FilePath $executable -WorkingDirectory $appRoot
