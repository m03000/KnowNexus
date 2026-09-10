# 仅清除笔记、个人文档、内置 Wiki 与个人知识索引；不删除 Obsidian Vault。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "scripts\reset_project_data.py") --scope notes @args
exit $LASTEXITCODE
