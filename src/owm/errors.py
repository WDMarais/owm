from enum import StrEnum


class ErrorCode(StrEnum):
    NOT_FOUND           = "NOT_FOUND"
    ALREADY_EXISTS      = "ALREADY_EXISTS"
    INSTANCE_RUNNING    = "INSTANCE_RUNNING"
    DIRTY_WORKTREE      = "DIRTY_WORKTREE"
    BRANCH_NOT_FOUND    = "BRANCH_NOT_FOUND"
    NOT_OWNED           = "NOT_OWNED"
    SHARED_REPO         = "SHARED_REPO"
    DIVERGED            = "DIVERGED"
    NO_COMPARE_TARGET   = "NO_COMPARE_TARGET"
    START_TIMEOUT       = "START_TIMEOUT"
    STOP_TIMEOUT        = "STOP_TIMEOUT"
    DB_UNAVAILABLE      = "DB_UNAVAILABLE"
    UPGRADE_FAILED      = "UPGRADE_FAILED"
    XMLRPC_UNAVAILABLE  = "XMLRPC_UNAVAILABLE"
    NO_WORKERS          = "NO_WORKERS"
    PORT_EXHAUSTED      = "PORT_EXHAUSTED"
    PORT_CONTESTED      = "PORT_CONTESTED"
    ARCHIVE_CONFLICT    = "ARCHIVE_CONFLICT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


NOT_FOUND           = ErrorCode.NOT_FOUND
ALREADY_EXISTS      = ErrorCode.ALREADY_EXISTS
INSTANCE_RUNNING    = ErrorCode.INSTANCE_RUNNING
DIRTY_WORKTREE      = ErrorCode.DIRTY_WORKTREE
BRANCH_NOT_FOUND    = ErrorCode.BRANCH_NOT_FOUND
NOT_OWNED           = ErrorCode.NOT_OWNED
SHARED_REPO         = ErrorCode.SHARED_REPO
DIVERGED            = ErrorCode.DIVERGED
NO_COMPARE_TARGET   = ErrorCode.NO_COMPARE_TARGET
START_TIMEOUT       = ErrorCode.START_TIMEOUT
STOP_TIMEOUT        = ErrorCode.STOP_TIMEOUT
DB_UNAVAILABLE      = ErrorCode.DB_UNAVAILABLE
UPGRADE_FAILED      = ErrorCode.UPGRADE_FAILED
XMLRPC_UNAVAILABLE  = ErrorCode.XMLRPC_UNAVAILABLE
NO_WORKERS          = ErrorCode.NO_WORKERS
PORT_EXHAUSTED        = ErrorCode.PORT_EXHAUSTED
PORT_CONTESTED        = ErrorCode.PORT_CONTESTED
ARCHIVE_CONFLICT      = ErrorCode.ARCHIVE_CONFLICT
CONFIRMATION_REQUIRED = ErrorCode.CONFIRMATION_REQUIRED


class OwmError(Exception):
    def __init__(self, message: str, code: ErrorCode | str, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra

    def __str__(self) -> str:
        return f"[{self.code}] {self.args[0]}"


def format_error(message: str, code: ErrorCode | str, **extra) -> dict:
    return {"error": message, "code": code, **extra}
