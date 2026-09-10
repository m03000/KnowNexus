# 仅清除代码解析记录、源码快照和项目向量索引；不删除原项目文件。
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "scripts\reset_project_data.py") --scope projects @args
exit $LASTEXITCODE
