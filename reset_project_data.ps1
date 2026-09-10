# 旧的一键全量清理入口已停用，避免测试时误删其他业务域。
Write-Host "一键清除全部数据已停用。请按测试范围运行以下脚本之一："
Write-Host "  .\clear_memory_data.ps1   # 记忆数据"
Write-Host "  .\clear_notes_data.ps1    # 笔记数据"
Write-Host "  .\clear_project_data.ps1  # 项目数据"
exit 1
