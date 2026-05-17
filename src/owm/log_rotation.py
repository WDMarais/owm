import os
from dataclasses import dataclass


@dataclass
class RotationCheck:
    needed: bool
    reason: str | None = None


@dataclass
class RotationResult:
    discarded: bool
    summarised: bool


def check_rotation_needed(
    line_count: int,
    log_age_days: int,
    threshold_lines: int,
    threshold_days: int,
) -> RotationCheck:
    if line_count > threshold_lines:
        return RotationCheck(needed=True, reason="line_count")
    if log_age_days > threshold_days:
        return RotationCheck(needed=True, reason="age")
    return RotationCheck(needed=False)


def rotate_log(log_path: str, mode: str) -> RotationResult:
    if mode == "local":
        try:
            os.remove(log_path)
        except OSError:
            pass
        return RotationResult(discarded=True, summarised=False)
    raise NotImplementedError(f"rotate_log mode={mode!r} is not implemented")
