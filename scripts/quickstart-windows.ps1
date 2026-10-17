# Dedicated Windows host-Python + owned Docker DB. Never reuses an existing listener.
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $taskRoot
$taskDbPort = if ($env:FALKOR_PORT) { [int]$env:FALKOR_PORT } else { 6379 }
$taskApiPort = if ($env:PEDIGREE_PORT) { [int]$env:PEDIGREE_PORT } else { 8000 }
foreach ($taskPort in @($taskDbPort, $taskApiPort)) {
    $taskProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $taskPort)
    try { $taskProbe.Start() } finally { $taskProbe.Stop() }
}
uv sync --frozen --extra dev
if ($LASTEXITCODE -ne 0) { throw 'Locked installation failed' }
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskData = if ($env:DATA_DIR) { [System.IO.Path]::GetFullPath($env:DATA_DIR) } else { Join-Path $taskRoot 'data/windows' }
New-Item -ItemType Directory -Force -Path (Join-Path $taskData 'db') | Out-Null
$taskLock = [System.IO.File]::Open((Join-Path $taskData '.runtime.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$taskContainer = 'pedigree-dev-' + [guid]::NewGuid().ToString('N')
$taskCreated = $false
try {
    docker run -d --name $taskContainer -p "127.0.0.1:${taskDbPort}:6379" --mount "type=bind,source=$taskData/db,target=/var/lib/falkordb/data" -e BROWSER=0 -e 'REDIS_ARGS=--appendonly yes --save 900 1' -e 'FALKORDB_ARGS=TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824' falkordb/falkordb:v4.22.1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Owned DB startup failed' }
    $taskCreated = $true
    $env:FALKOR_HOST = '127.0.0.1'
    $env:FALKOR_PORT = "$taskDbPort"
    $env:PEDIGREE_SEED_DEMO = '1'
    if (-not $env:PEDIGREE_CREDENTIALS_DIR) { $env:PEDIGREE_CREDENTIALS_DIR = Join-Path $taskData 'credentials' }
    & $taskPython scripts/runtime.py wait-db
    if ($LASTEXITCODE -ne 0) { throw 'Database readiness failed' }
    & $taskPython scripts/seed_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Demo seed failed; recover the private credentials or choose a new dedicated tenant' }
    & $taskPython -m uvicorn pedigree.api.app:create_app --factory --host 127.0.0.1 --port $taskApiPort --no-proxy-headers
} finally {
    if ($taskCreated) {
        docker stop --time 10 $taskContainer | Out-Null
        docker rm $taskContainer | Out-Null
    }
    $taskLock.Dispose()
}
