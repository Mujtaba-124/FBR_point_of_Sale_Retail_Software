<#
.SYNOPSIS
    End-to-end verification of the subscription expiry reminder system on an
    isolated, disposable QA stack.

.DESCRIPTION
    Creates a fresh disposable PostgreSQL database (cheena_database_e2e) on the
    existing Postgres server, migrates it with Alembic, and starts a dedicated
    Celery worker and Celery Beat that use Redis logical database 12 and the
    file-sink email transport. The driver (backend/qa/reminder_e2e.py) then
    simulates the full reminder period with the application's simulated clock:
    15 days before expiry through 5 days after (21 reminder dates, 42 recipient
    events), duplicate scheduler runs, renewal cancellation, transient and
    permanent SMTP failures, retries, worker crashes and Asia/Karachi day
    boundaries.

    Safety:
      - No real email is sent (EMAIL_TRANSPORT=sink; messages are written to
        backend/.qa-e2e/sink-<run> and deleted afterwards).
      - Windows and Docker clocks are not changed.
      - cheena_database, its accounts, subscription, renewal history, audit log,
        SMTP settings and all Docker volumes are never touched. The backend
        refuses E2E mode for any database not named *_e2e.
      - Only disposable QA resources are cleaned up: the e2e containers, the
        cheena_database_e2e database, Redis DB 12 and the sink folder.

    The Markdown/JSON report is kept in backend/.qa-e2e/reports.
    Exit code: 0 = all checks passed, nonzero = at least one failure.

.PARAMETER KeepResources
    Leave the e2e database, containers and sink in place for inspection.

.PARAMETER IntervalSeconds
    Beat interval for evaluation and dispatch during the run (1-10, default 2).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\qa\Invoke-ReminderE2E.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepResources,
    [ValidateRange(1, 10)][int]$IntervalSeconds = 2
)

$ErrorActionPreference = 'Continue'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root

$RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$Db = 'cheena_database_e2e'
$RedisDb = 12
$Worker = 'cheena_e2e_worker'
$Beat = 'cheena_e2e_beat'
$Driver = 'cheena_e2e_driver'
$SinkInContainer = "/app/.qa-e2e/sink-$RunId"
$SinkOnHost = Join-Path $Root "backend\.qa-e2e\sink-$RunId"
$ReportOnHost = Join-Path $Root "backend\.qa-e2e\reports\reminder-e2e-$RunId.md"

if (-not $Db.EndsWith('_e2e') -or $Db -eq 'cheena_database') {
    throw 'Refusing to run: the e2e database name must end in _e2e.'
}

function Write-Step([string]$Text) { Write-Host "`n=== $Text" -ForegroundColor Cyan }

function Assert-Exit([string]$What) {
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function New-EncryptionKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}

# Shell prefix inside the containers: point DATABASE_URL at the e2e database.
# (No double quotes: Windows PowerShell 5.1 mangles them in native arguments.)
$Pre = 'export DATABASE_URL=${DATABASE_URL%/*}/' + $Db + ';'
$Key = New-EncryptionKey
$EnvArgs = @(
    '-e', 'ENVIRONMENT=development',
    '-e', 'E2E_TEST_MODE=true',
    '-e', 'EMAIL_TRANSPORT=sink',
    '-e', "EMAIL_SINK_DIR=$SinkInContainer",
    '-e', "REDIS_URL=redis://redis:6379/$RedisDb",
    '-e', "EMAIL_SETTINGS_ENCRYPTION_KEY=$Key",
    '-e', 'EMAIL_SETTINGS_PREVIOUS_KEYS=',
    '-e', "REMINDER_EVALUATE_INTERVAL_SECONDS=$IntervalSeconds",
    '-e', "OUTBOX_DISPATCH_INTERVAL_SECONDS=$IntervalSeconds"
)

function Remove-E2EContainers {
    foreach ($name in @($Driver, $Beat, $Worker)) {
        $id = docker ps -aq --filter "name=^/$name$"
        if ($id) { docker rm -f $name | Out-Null }
    }
}

function Invoke-Cleanup([string]$PgUser) {
    Write-Step 'Cleaning up disposable QA resources'
    Remove-E2EContainers
    if ($PgUser) {
        docker exec cheena_postgres dropdb --if-exists --force -U $PgUser $Db
        Write-Host "Dropped database $Db"
    }
    docker exec cheena_redis redis-cli -n $RedisDb flushdb | Out-Null
    Write-Host "Flushed Redis DB $RedisDb"
    if (Test-Path $SinkOnHost) {
        Remove-Item -Recurse -Force -Confirm:$false $SinkOnHost
        Write-Host 'Removed the email sink folder'
    }
}

$exitCode = 1
$pgUser = $null
try {
    Write-Step 'Preflight'
    foreach ($c in @('cheena_postgres', 'cheena_redis')) {
        $state = docker inspect -f '{{.State.Running}}' $c
        if ($state -ne 'true') { throw "Container $c is not running. Start it with: docker compose up -d postgres redis" }
    }
    $pgUser = (docker exec cheena_postgres printenv POSTGRES_USER).Trim()
    Assert-Exit 'Reading POSTGRES_USER'
    Remove-E2EContainers

    Write-Step "Creating disposable database $Db"
    docker exec cheena_postgres dropdb --if-exists --force -U $pgUser $Db
    Assert-Exit 'dropdb'
    docker exec cheena_postgres createdb -U $pgUser $Db
    Assert-Exit 'createdb'
    docker exec cheena_redis redis-cli -n $RedisDb flushdb | Out-Null
    Assert-Exit 'Flushing Redis DB'

    Write-Step 'Applying Alembic migrations to the e2e database'
    docker compose run --rm --no-deps @EnvArgs backend sh -c "$Pre alembic upgrade head"
    Assert-Exit 'alembic upgrade head'

    Write-Step 'Starting isolated Celery worker and Beat'
    docker compose run -d --rm --no-deps --name $Worker @EnvArgs celery_worker sh -c "$Pre exec celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=2 -n e2e@%h" | Out-Null
    Assert-Exit 'Starting the e2e worker'
    docker compose run -d --rm --no-deps --name $Beat @EnvArgs celery_worker sh -c "$Pre exec celery -A app.celery_app.celery_app beat --loglevel=info --schedule /tmp/e2e-beat-schedule" | Out-Null
    Assert-Exit 'Starting the e2e Beat'

    Write-Step 'Running the verification driver'
    docker compose run --rm --no-deps --name $Driver @EnvArgs backend sh -c "$Pre exec python -m qa.reminder_e2e --run-id $RunId"
    $exitCode = $LASTEXITCODE

    # Evidence that the real Celery processes did the work.
    $beatLog = docker logs $Beat 2>&1 | ForEach-Object { "$_" }
    $workerLog = docker logs $Worker 2>&1 | ForEach-Object { "$_" }
    $evaluateSent = @($beatLog | Select-String 'Sending due task reminders-evaluate').Count
    $dispatchSent = @($beatLog | Select-String 'Sending due task email-outbox-dispatch').Count
    $evaluateDone = @($workerLog | Select-String 'reminders.evaluate\[.*succeeded').Count
    $dispatchDone = @($workerLog | Select-String 'email_outbox.dispatch\[.*succeeded').Count
    $crashes = @($workerLog | Select-String 'exited prematurely|WorkerLostError').Count
    $evidence = @(
        '',
        '## Celery evidence (container logs)',
        '',
        "- Beat sent reminders.evaluate: $evaluateSent; email_outbox.dispatch: $dispatchSent",
        "- Worker completed reminders.evaluate: $evaluateDone; email_outbox.dispatch: $dispatchDone",
        "- Worker child processes lost (injected crashes): $crashes"
    )
    if (Test-Path $ReportOnHost) {
        Add-Content -Path $ReportOnHost -Value $evidence -Encoding UTF8
    }
    $evidence | ForEach-Object { Write-Host $_ }
    if ($evaluateSent -lt 1 -or $dispatchSent -lt 1) {
        Write-Host 'FAIL: Celery Beat did not send the scheduled tasks.' -ForegroundColor Red
        $exitCode = 1
    }
    if ($crashes -lt 2) {
        Write-Host 'FAIL: the injected worker crashes were not observed in the worker log.' -ForegroundColor Red
        $exitCode = 1
    }
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($KeepResources) {
        Write-Host "`nKeeping QA resources ($Db, Redis DB $RedisDb, $Worker, $Beat, sink)." -ForegroundColor Yellow
    }
    else {
        Invoke-Cleanup $pgUser
    }
}

Write-Host ''
if (Test-Path $ReportOnHost) { Write-Host "Report: $ReportOnHost" }
if ($exitCode -eq 0) {
    Write-Host 'REMINDER E2E VERIFICATION: PASS' -ForegroundColor Green
}
else {
    Write-Host "REMINDER E2E VERIFICATION: FAIL (exit code $exitCode)" -ForegroundColor Red
}
exit $exitCode
