@echo off
setlocal
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator permission for LAN firewall access...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$name='Morris QA Analyzer Web 8766';" ^
  "$rule=Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue;" ^
  "if ($rule) {" ^
  "  $rule | Set-NetFirewallRule -Enabled True -Direction Inbound -Action Allow -Profile Domain,Private;" ^
  "  $rule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort 8766" ^
  "} else {" ^
  "  New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8766 -Profile Domain,Private | Out-Null" ^
  "}"

if errorlevel 1 (
  echo Firewall setup failed.
) else (
  echo LAN access enabled on Domain and Private networks, TCP port 8766.
)
pause
