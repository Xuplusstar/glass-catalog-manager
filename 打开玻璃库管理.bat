@echo off
cd /d "%~dp0"
if exist "%~dp0release\GlassCatalog-1.2.0-Windows-x64\GlassCatalog.exe" (
    start "" "%~dp0release\GlassCatalog-1.2.0-Windows-x64\GlassCatalog.exe"
    exit /b 0
)
python -X utf8 glass_catalog_gui.py
if errorlevel 1 pause
