from dataclasses import dataclass


@dataclass
class InstallResult:
    installed: list
    skipped: bool
    odoo_bin_called: bool
    odoo_bin_args: str | None = None


@dataclass
class UpgradeResult:
    stopped_before: bool
    modules: list | str
    restarted: bool
    odoo_bin_called: bool
    odoo_bin_args: str | None = None
    reinstall: bool = False


def install_modules(
    instance: str,
    configured_modules: list[str],
    installed_modules: list[str],
) -> InstallResult:
    missing = [m for m in configured_modules if m not in installed_modules]
    if not missing:
        return InstallResult(installed=[], skipped=True, odoo_bin_called=False)
    return InstallResult(
        installed=missing,
        skipped=False,
        odoo_bin_called=True,
        odoo_bin_args=f"-i {','.join(missing)}",
    )


def upgrade_modules(
    instance: str,
    modules: list[str] | None,
    *,
    reinstall: bool = False,
) -> UpgradeResult:
    if modules is None:
        return UpgradeResult(
            stopped_before=True,
            modules="all",
            restarted=True,
            odoo_bin_called=True,
            odoo_bin_args="-u all",
            reinstall=reinstall,
        )
    return UpgradeResult(
        stopped_before=True,
        modules=modules,
        restarted=True,
        odoo_bin_called=True,
        reinstall=reinstall,
    )


def check_modules_present(instance: str, configured_modules: list[str]) -> list[str]:
    return []
