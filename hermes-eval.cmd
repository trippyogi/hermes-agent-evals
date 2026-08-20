@echo off
set PYTHONPATH=%~dp0;%PYTHONPATH%
if defined HERMES_EVAL_PYTHON (
  "%HERMES_EVAL_PYTHON%" -m hermes_eval %*
) else if exist "c:\dev\hermes-agent\.venv\Scripts\python.exe" (
  "c:\dev\hermes-agent\.venv\Scripts\python.exe" -m hermes_eval %*
) else (
  python -m hermes_eval %*
)
