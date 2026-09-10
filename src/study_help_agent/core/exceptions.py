"""应用异常定义。"""


class AppError(Exception):
    """应用内可预期异常的基类."""

    code = "app_error"


class ConfigurationError(AppError):
    """应用配置不合法或缺失."""

    code = "configuration_error"


class InvalidProjectPathError(AppError):
    """用户提供的项目路径不合法。"""

    code = "invalid_project_path"


class ProjectAccessDeniedError(AppError):
    """项目路径不在允许访问范围内。"""

    code = "project_access_denied"


class SourceScanLimitError(AppError):
    """扫描到的源码文件数量超过限制。"""

    code = "source_scan_limit_exceeded"


class SourceFileTooLargeError(AppError):
    """源码文件超过允许读取的大小。"""

    code = "source_file_too_large"


class NoPythonSourceFilesError(AppError):
    """项目中没有可分析的 Python 源文件。"""

    code = "no_python_source_files"


class ProjectNotFoundError(AppError):
    """指定的代码解释项目不存在。"""

    code = "project_not_found"


class ExplainedFileNotFoundError(AppError):
    """项目中不存在指定的已解释源码文件。"""

    code = "explained_file_not_found"


class LearningNoteNotFoundError(AppError):
    """前端请求的已发布学习笔记不存在。"""

    code = "learning_note_not_found"






















