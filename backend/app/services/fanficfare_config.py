"""FanFicFare configuration helpers shared by downloads and site collectors."""

import configparser
import logging
import os
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException, status

from ..config import APP_DIR

logger = logging.getLogger(__name__)

_DEFAULT_USER_PERSONAL_INI_CANDIDATES = (
    (APP_DIR.parent.parent / "config" / "fanficfare" / "personal.ini").resolve(),
    Path("/app/config/personal.ini"),
)


def get_optional_user_ini_path() -> Optional[Path]:
    env_path = os.getenv("FFF_USER_CONFIG_PATH")
    if env_path is not None:
        stripped = env_path.strip()
        if not stripped:
            logger.info("FFF_USER_CONFIG_PATH is set to an empty value; skipping optional FanFicFare config.")
            return None
        resolved = Path(stripped).expanduser()
        if not resolved.is_file():
            logger.warning("FFF_USER_CONFIG_PATH points to %s, but that file was not found.", resolved)
            return None
        logger.info("Using FanFicFare user config from FFF_USER_CONFIG_PATH: %s", resolved)
        return resolved

    for candidate in _DEFAULT_USER_PERSONAL_INI_CANDIDATES:
        if candidate.is_file():
            logger.info("Using FanFicFare user config override: %s", candidate)
            return candidate

    logger.info(
        "No optional FanFicFare user config found. Checked: %s",
        ", ".join(str(candidate) for candidate in _DEFAULT_USER_PERSONAL_INI_CANDIDATES),
    )
    return None


def get_fff_config_paths() -> List[Path]:
    ini_path = APP_DIR / "personal.ini"
    if not ini_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: personal.ini not found.",
        )

    config_paths = [ini_path]
    optional_user_ini = get_optional_user_ini_path()
    if optional_user_ini and optional_user_ini.is_file():
        try:
            if optional_user_ini.resolve() != ini_path.resolve():
                config_paths.append(optional_user_ini)
        except FileNotFoundError:
            # Another process may have removed it between is_file and resolve.
            pass
    logger.info("FanFicFare config chain: %s", " -> ".join(str(path) for path in config_paths))
    return config_paths


def get_fff_site_config(site_domain: str) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read([str(path) for path in get_fff_config_paths()])

    config: dict[str, str] = {}
    for section in ("defaults", site_domain):
        if parser.has_section(section):
            config.update({key: value.strip() for key, value in parser.items(section)})
    return config


def is_enabled_config_value(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on", "withimages"}
