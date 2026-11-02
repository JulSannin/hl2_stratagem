@echo off
setlocal
 title HD2 Stratagem LAN Firewall Rule
 echo.
 echo This optional rule allows other devices on your PRIVATE home network
 echo to connect to this PC on TCP port 8765.
 echo It is not needed when opening the page on this same PC.
 echo.
 net session >nul 2>&1
 if errorlevel 1 (
     echo ERROR: Right-click this file and choose "Run as administrator".
     pause
     exit /b 1
 )
 netsh advfirewall firewall add rule name="HD2 Stratagem LAN TCP 8765" dir=in action=allow protocol=TCP localport=8765 profile=private
 if errorlevel 1 (
     echo ERROR: Could not add the Windows Firewall rule.
 ) else (
     echo Firewall rule added for the Private network profile.
 )
 pause
