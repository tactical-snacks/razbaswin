@echo off
rem Sets a random static color on the Basilisk V3 (live state only; saved profiles are untouched).
rem Meant to run at Windows login. Retries for ~30 s in case the mouse isn't ready yet.

cd /d "%~dp0.."
for /l %%i in (1,1,10) do (
    python -m razbaswin effect static random && exit /b 0
    timeout /t 3 /nobreak >nul
)
exit /b 1
