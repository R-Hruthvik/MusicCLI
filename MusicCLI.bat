@echo off
title MusicCLI
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python -u musiccli.py
pause
