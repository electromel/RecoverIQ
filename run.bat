@echo off
rem Lance RecoverIQ sur http://localhost:8765 (fermer la fenêtre pour arrêter).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Environnement virtuel absent. Voir README.md, section Installation.
    pause
    exit /b 1
)

start "" http://localhost:8765
".venv\Scripts\python.exe" -m recoveriq
