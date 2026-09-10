"""KnowNexus 的统一 FastAPI 应用入口。"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "study_help_agent.app.main:app",
        host="127.0.0.1",
        port=8001,
        log_level="info",
        reload=True
    )


# .venv\Scripts\python.exe -m uvicorn study_help_agent.app.main:app --reload --host 127.0.0.1 --port 8001
# .venv\Scripts\python.exe -m uvicorn study_help_agent.app.main:app --host 127.0.0.1 --port 8001
# cd frontend
# npm run desktop:run
# npm run dev
# 精准清空：.\clear_memory_data.ps1 / .\clear_notes_data.ps1 / .\clear_project_data.ps1
