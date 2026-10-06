@echo off
REM Run once: puts a "Sports Notifier" shortcut on your desktop that starts the dashboard.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Sports Notifier.lnk\");" ^
  "$s.TargetPath='%~dp0start_dashboard.bat';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.WindowStyle=7;" ^
  "$s.Description='Open the Sports Notifier dashboard';" ^
  "$s.Save(); Write-Host ('Shortcut created on ' + $d)"
pause
