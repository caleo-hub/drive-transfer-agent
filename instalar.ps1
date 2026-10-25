$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
foreach ($tool in @('uv', 'node', 'npm')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Instale $tool antes de continuar. Consulte o README."
    }
}
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar o backend.' }
Push-Location -LiteralPath (Join-Path $PSScriptRoot 'web')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível instalar a interface.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível compilar a interface.' }
} finally { Pop-Location }
Write-Host 'Instalação concluída. Abra iniciar.bat.'
