# 仅清除会话、长期记忆、记忆图谱、记忆向量与监听游标。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "scripts\reset_project_data.py") --scope memory @args
exit $LASTEXITCODE
