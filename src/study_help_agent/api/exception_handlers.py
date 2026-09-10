"""应用业务异常到 HTTP 响应的统一映射。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from study_help_agent.core.exceptions import (
    AppError,
    ExplainedFileNotFoundError,
    InvalidProjectPathError,
    NoPythonSourceFilesError,
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    LearningNoteNotFoundError,
    SourceFileTooLargeError,
    SourceScanLimitError,
)


def register_exception_handlers(
    app: FastAPI,
) -> None:
    """注册应用级业务异常处理器。"""

    @app.exception_handler(
        ProjectNotFoundError
    )
    async def handle_project_not_found(
        request: Request,
        error: ProjectNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            status_code=404,
            error=error,
        )

    @app.exception_handler(
        ExplainedFileNotFoundError
    )
    async def handle_file_not_found(
        request: Request,
        error: ExplainedFileNotFoundError,
    ) -> JSONResponse:
        return _error_response(
            status_code=404,
            error=error,
        )

    @app.exception_handler(LearningNoteNotFoundError)
    async def handle_learning_note_not_found(
        request: Request,
        error: LearningNoteNotFoundError,
    ) -> JSONResponse:
        return _error_response(status_code=404, error=error)

    @app.exception_handler(
        ProjectAccessDeniedError
    )
    async def handle_access_denied(
        request: Request,
        error: ProjectAccessDeniedError,
    ) -> JSONResponse:
        return _error_response(
            status_code=403,
            error=error,
        )

    @app.exception_handler(
        SourceScanLimitError
    )
    async def handle_scan_limit(
        request: Request,
        error: SourceScanLimitError,
    ) -> JSONResponse:
        return _error_response(
            status_code=413,
            error=error,
        )

    @app.exception_handler(
        SourceFileTooLargeError
    )
    async def handle_file_too_large(
        request: Request,
        error: SourceFileTooLargeError,
    ) -> JSONResponse:
        return _error_response(
            status_code=413,
            error=error,
        )

    @app.exception_handler(
        InvalidProjectPathError
    )
    async def handle_invalid_project_path(
        request: Request,
        error: InvalidProjectPathError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            error=error,
        )

    @app.exception_handler(
        NoPythonSourceFilesError
    )
    async def handle_empty_project(
        request: Request,
        error: NoPythonSourceFilesError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            error=error,
        )

    @app.exception_handler(AppError)
    async def handle_app_error(
        request: Request,
        error: AppError,
    ) -> JSONResponse:
        return _error_response(
            status_code=400,
            error=error,
        )


def _error_response(
    *,
    status_code: int,
    error: AppError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": error.code,
            "message": str(error),
        },
    )
