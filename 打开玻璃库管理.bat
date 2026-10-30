@echo off
cd /d "%~dp0"
if exist "%~dp0release\GlassCatalog\GlassCatalog.exe" (
    start "" "%~dp0release\GlassCatalog\GlassCatalog.exe"
    exit /b 0
)
python -X utf8 glass_catalog_gui.py
if errorlevel 1 pause
