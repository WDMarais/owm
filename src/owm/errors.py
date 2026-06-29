from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    """Ordered severity scale shared by errors and findings.

    blocking > attention > warn > info. Use `.rank` for threshold comparisons
    (`severity.rank >= Severity.ATTENTION.rank`); equality/serialisation stay
    plain strings ("blocking", ...) so the wire contract is agent-parseable.
    """
    BLOCKING  = "blocking"
    ATTENTION = "attention"
    WARN      = "warn"
    INFO      = "info"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.BLOCKING:  3,
    Severity.ATTENTION: 2,
    Severity.WARN:      1,
    Severity.INFO:      0,
}


class ErrorCode(StrEnum):
    NOT_FOUND           = "NOT_FOUND"
    ALREADY_EXISTS      = "ALREADY_EXISTS"
    INSTANCE_RUNNING    = "INSTANCE_RUNNING"
    DIRTY_WORKTREE      = "DIRTY_WORKTREE"
    BRANCH_NOT_FOUND    = "BRANCH_NOT_FOUND"
    BRANCH_ALREADY_EXISTS = "BRANCH_ALREADY_EXISTS"
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
    PORT_RANGE_EXHAUSTED      = "PORT_RANGE_EXHAUSTED"
    PORT_CONTESTED      = "PORT_CONTESTED"
    ARCHIVE_CONFLICT    = "ARCHIVE_CONFLICT"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    NO_ODOO_REPO        = "NO_ODOO_REPO"
    FETCH_TIMEOUT       = "FETCH_TIMEOUT"
    # Config failures, named by owning domain rather than file format (which is
    # incidental): OWM_CONFIG_* = owm's own config (instance.toml / workspace.toml);
    # ODOO_CONFIG_* = the Odoo server config owm generates (instance.conf).
    OWM_CONFIG_INVALID   = "OWM_CONFIG_INVALID"
    ODOO_CONFIG_UNMARKED = "ODOO_CONFIG_UNMARKED"
    ODOO_CONFIG_NO_ADDONS = "ODOO_CONFIG_NO_ADDONS"
    DB_HAS_CONNECTIONS   = "DB_HAS_CONNECTIONS"

    def __new__(cls, value, default_severity=Severity.BLOCKING):
        # Codes default to BLOCKING (raised as OwmError). A code emitted as a
        # non-fatal Finding carries its own severity at construction; a member
        # may also override this finding-context default via ("VALUE", Severity.X).
        # The code is the *what*; severity is the *how-bad* — kept separate so a
        # future ErrorCode/FindingCode split stays a mechanical partition.
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.default_severity = default_severity
        return obj


NOT_FOUND           = ErrorCode.NOT_FOUND
ALREADY_EXISTS      = ErrorCode.ALREADY_EXISTS
INSTANCE_RUNNING    = ErrorCode.INSTANCE_RUNNING
DIRTY_WORKTREE      = ErrorCode.DIRTY_WORKTREE
BRANCH_NOT_FOUND    = ErrorCode.BRANCH_NOT_FOUND
BRANCH_ALREADY_EXISTS = ErrorCode.BRANCH_ALREADY_EXISTS
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
PORT_RANGE_EXHAUSTED        = ErrorCode.PORT_RANGE_EXHAUSTED
PORT_CONTESTED        = ErrorCode.PORT_CONTESTED
ARCHIVE_CONFLICT      = ErrorCode.ARCHIVE_CONFLICT
CONFIRMATION_REQUIRED = ErrorCode.CONFIRMATION_REQUIRED
NO_ODOO_REPO          = ErrorCode.NO_ODOO_REPO
FETCH_TIMEOUT         = ErrorCode.FETCH_TIMEOUT
OWM_CONFIG_INVALID    = ErrorCode.OWM_CONFIG_INVALID
ODOO_CONFIG_UNMARKED  = ErrorCode.ODOO_CONFIG_UNMARKED
ODOO_CONFIG_NO_ADDONS = ErrorCode.ODOO_CONFIG_NO_ADDONS
DB_HAS_CONNECTIONS    = ErrorCode.DB_HAS_CONNECTIONS


class OwmError(Exception):
    def __init__(self, message: str, code: ErrorCode | str, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra

    def __str__(self) -> str:
        return f"[{self.code}] {self.args[0]}"


class ConfigError(OwmError):
    """A workspace.toml / instance.toml that cannot be parsed into config.

    Always carries OWM_CONFIG_INVALID. Callers (dashboard, api, CLI) catch this
    specifically to distinguish a malformed config from operational errors
    rather than swallowing every exception."""

    def __init__(self, message: str, **extra):
        super().__init__(message, OWM_CONFIG_INVALID, **extra)


def format_error(message: str, code: ErrorCode | str, **extra) -> dict:
    return {"error": message, "code": code, **extra}


@dataclass
class Finding:
    """A non-fatal result/warning/note from a lib operation.

    The return-value twin of OwmError: same vocabulary (code, message, extra),
    different carrier. Hard failures `raise OwmError`; soft outcomes ride home
    in the return value as Finding(s). The raise-vs-return choice is made at the
    callsite by which carrier is constructed — never by inspecting the code — so
    the two stay untangled.

    severity defaults to the code's default_severity and may be overridden, so a
    code whose fatal form raises BLOCKING can also surface as an INFO note.
    """
    code: ErrorCode | str
    message: str
    severity: Severity | None = None
    subject: str | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.severity is None:
            self.severity = getattr(self.code, "default_severity", Severity.BLOCKING)

    def to_dict(self) -> dict:
        """Agent-parseable shape: {severity, code, message, [subject], **extra}.

        Mirrors format_error's {error, code, **extra}; Severity/ErrorCode are
        StrEnums so they serialise as plain strings.
        """
        d = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.subject is not None:
            d["subject"] = self.subject
        d.update(self.extra)
        return d
