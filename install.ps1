#Requires -Version 5.0
<#
.SYNOPSIS
    wbclean 一键安装（Windows）

.DESCRIPTION
    把 wbclean 装到本地目录，并生成一个 wbclean.cmd 包装器，
    之后在任意命令行里直接敲 wbclean 就能用。

    只用标准库，不需要 pip install，也不写注册表。

.PARAMETER Prefix
    安装目录，默认 %LOCALAPPDATA%\wbclean

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Prefix D:\tools\wbclean
#>
[CmdletBinding()]
param(
    [string]$Prefix = (Join-Path $env:LOCALAPPDATA 'wbclean')
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $ScriptDir 'bin\wbclean'

Write-Host ''
Write-Host '  ===================================================='
Write-Host '    wbclean 安装程序'
Write-Host '  ===================================================='
Write-Host ''

# ---- 前置检查
if (-not (Test-Path $Source)) {
    Write-Host "  [错误] 找不到主脚本：$Source" -ForegroundColor Red
    Write-Host ''
    exit 1
}

function Test-PythonCmd {
    param([string[]]$Command)
    try {
        $out = & $Command[0] @($Command[1..($Command.Length - 1)]) `
               -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $false }
        return ([int]$out -ge 307)
    } catch {
        return $false
    }
}

# ---- 找 Python 3.7+
$pyInvoke = $null
$pyDisplay = $null

if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-PythonCmd @('py', '-3')) { $pyInvoke = @('py', '-3'); $pyDisplay = 'py -3' }
}
if (-not $pyInvoke -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-PythonCmd @('python')) { $pyInvoke = @('python'); $pyDisplay = 'python' }
}
if (-not $pyInvoke) {
    # WorkBuddy 自带的解释器，作为最后兜底
    $base = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions'
    if (Test-Path $base) {
        $exe = Get-ChildItem $base -Directory |
               Sort-Object Name -Descending |
               ForEach-Object { Join-Path $_.FullName 'python.exe' } |
               Where-Object { Test-Path $_ } |
               Select-Object -First 1
        if ($exe -and (Test-PythonCmd @($exe))) {
            $pyInvoke = @($exe)
            $pyDisplay = $exe
        }
    }
}

if (-not $pyInvoke) {
    Write-Host '  [错误] 没找到 Python 3.7 或更高版本。' -ForegroundColor Red
    Write-Host ''
    Write-Host '  到 https://www.python.org/downloads/windows/ 装一个，'
    Write-Host '  安装时记得勾上 "Add python.exe to PATH"，然后重新运行本脚本。'
    Write-Host ''
    exit 1
}

$verText = (& $pyInvoke[0] @($pyInvoke[1..($pyInvoke.Length - 1)]) --version 2>&1) -join ''
Write-Host "  Python    $verText  ($pyDisplay)"

# ---- 安装
if (-not (Test-Path $Prefix)) {
    New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
}

$TargetPy = Join-Path $Prefix 'wbclean.py'
if (Test-Path $TargetPy) {
    $backup = "$TargetPy.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $TargetPy $backup
    Write-Host "  已备份旧版本 → $backup"
}

Copy-Item $Source $TargetPy -Force
Write-Host "  安装完成  → $TargetPy"

# ---- 生成 cmd 包装器
$TargetCmd = Join-Path $Prefix 'wbclean.cmd'
$callLine = if ($pyInvoke.Length -gt 1) {
    ($pyInvoke[0..($pyInvoke.Length - 1)] | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
} else {
    if ($pyInvoke[0] -match '\s') { "`"$($pyInvoke[0])`"" } else { $pyInvoke[0] }
}

$cmdBody = @"
@echo off
chcp 65001 >nul 2>&1
$callLine "$TargetPy" %*
"@
# 用 LF 写不出问题，cmd 认 CRLF 更稳
Set-Content -Path $TargetCmd -Value $cmdBody -Encoding ASCII
Write-Host "  命令包装  → $TargetCmd"

# ---- PATH 检查（只提示，不擅自改系统设置）
$pathDirs = $env:PATH -split ';' | Where-Object { $_ }
$inPath = $pathDirs | Where-Object { $_.TrimEnd('\') -ieq $Prefix.TrimEnd('\') }

Write-Host ''
if ($inPath) {
    Write-Host "  PATH      已包含 $Prefix" -ForegroundColor Green
} else {
    Write-Host "  [注意] $Prefix 不在 PATH 里，装完还要跑一次：" -ForegroundColor Yellow
    Write-Host ''
    Write-Host "      setx PATH `"`$env:PATH;$Prefix`""
    Write-Host ''
    Write-Host '  然后关掉当前窗口重新打开，让新 PATH 生效。'
}

Write-Host ''
Write-Host '  验证：'
Write-Host "    $TargetCmd --version"
Write-Host "    $TargetCmd scan"
Write-Host ''
