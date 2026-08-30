# Watches the 4 hub apps (stock/borrow/pension/portal) and restarts any that
# stopped responding. Registered as a scheduled task running every 5 minutes,
# because the login-time VBS launcher only starts things once and nothing
# else brings a crashed process back mid-session.

$apps = @(
    @{ Name = 'stock';   Port = 5000; Dir = 'C:\Users\tyinc\Desktop\ai 개발관련\주가현황';   Args = 'server.py' },
    @{ Name = 'borrow';  Port = 8501; Dir = 'C:\Users\tyinc\Desktop\ai 개발관련\차입금관리'; Args = '-m streamlit run app.py' },
    @{ Name = 'pension'; Port = 8000; Dir = 'C:\Users\tyinc\Desktop\퇴직연금_보고시스템';     Args = 'run_dashboard.py' },
    @{ Name = 'portal';  Port = 9000; Dir = 'C:\Users\tyinc\Desktop\ai 개발관련\통합포털';   Args = 'app.py' }
)

$logPath = Join-Path $PSScriptRoot '_watchdog.log'

foreach ($app in $apps) {
    $listening = $null
    try {
        $listening = Get-NetTCPConnection -LocalPort $app.Port -State Listen -ErrorAction SilentlyContinue
    } catch {}

    if (-not $listening) {
        $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Add-Content -Path $logPath -Value "$timestamp - $($app.Name) (port $($app.Port)) not responding - restarting"
        Start-Process -FilePath 'python' -ArgumentList $app.Args -WorkingDirectory $app.Dir -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $app.Dir '_watchdog_stdout.log') `
            -RedirectStandardError (Join-Path $app.Dir '_watchdog_stderr.log')
    }
}

