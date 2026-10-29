
import shutil
from pathlib import Path
from typing import Optional, Set
import structlog

logger = structlog.get_logger()


EXCLUDE_PATTERNS: Set[str] = {
    ".git",
    ".gitignore",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".env.local",
    "*.log",
    ".pytest_cache",
    ".mypy_cache",
    ".coverage",
    "dist",
    "build",
    "*.egg-info"
}


def should_exclude(path: Path) -> bool:
    name = path.name

    if name in EXCLUDE_PATTERNS:
        return True

    for pattern in EXCLUDE_PATTERNS:
        if "*" in pattern:
            if pattern.startswith("*"):
                suffix = pattern[1:]
                if name.endswith(suffix):
                    return True
            elif pattern.endswith("*"):
                prefix = pattern[:-1]
                if name.startswith(prefix):
                    return True

    return False


def copy_templates(template_path: str, destination_path: str) -> tuple[bool, Optional[str]]:
    try:
        template_dir = Path(template_path).expanduser().resolve()
        dest_dir = Path(destination_path).expanduser().resolve()

        if not template_dir.exists():
            error_msg = f"Template directory not found: {template_dir}"
            logger.warning("template_directory_missing", path=str(template_dir))
            return False, error_msg

        if not template_dir.is_dir():
            error_msg = f"Template path is not a directory: {template_dir}"
            logger.error("template_path_not_directory", path=str(template_dir))
            return False, error_msg

        dest_dir.mkdir(parents=True, exist_ok=True)

        copied_count = 0
        skipped_count = 0
        kept_existing: list[str] = []

        for item in template_dir.rglob("*"):
            if any(should_exclude(part) for part in item.relative_to(template_dir).parents) or should_exclude(item):
                skipped_count += 1
                continue

            rel_path = item.relative_to(template_dir)
            dest_item = dest_dir / rel_path

            if item.is_symlink():
                skipped_count += 1
                continue

            try:
                if item.is_dir():
                    dest_item.mkdir(parents=True, exist_ok=True)
                    logger.debug("template_dir_created", path=str(rel_path))
                elif item.is_file():
                    if dest_item.exists() or dest_item.is_symlink():
                        kept_existing.append(str(rel_path))
                        skipped_count += 1
                        continue
                    dest_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_item, follow_symlinks=False)
                    copied_count += 1
                    logger.debug("template_file_copied", path=str(rel_path))
            except (OSError, shutil.Error) as e:
                logger.warning(
                    "template_item_copy_failed",
                    path=str(rel_path),
                    error=str(e)
                )
                skipped_count += 1

        if kept_existing:
            logger.info("template_existing_skipped", dest_dir=str(dest_dir), paths=kept_existing)
        logger.info(
            "templates_copied",
            template_dir=str(template_dir),
            dest_dir=str(dest_dir),
            copied=copied_count,
            skipped=skipped_count
        )

        return True, None

    except (OSError, shutil.Error) as e:
        error_msg = f"Template copy failed: {str(e)}"
        logger.error(
            "template_copy_error",
            template_path=template_path,
            destination_path=destination_path,
            error=str(e)
        )
        return False, error_msg


def validate_template_path(template_path: Optional[str]) -> tuple[bool, Optional[str]]:
    if not template_path:
        return False, "No template path specified"

    try:
        path = Path(template_path).expanduser().resolve()

        if not path.exists():
            return False, f"Template path does not exist: {path}"

        if not path.is_dir():
            return False, f"Template path is not a directory: {path}"

        if not path.stat().st_mode & 0o444:
            return False, f"Template path is not readable: {path}"

        return True, None

    except Exception as e:
        return False, f"Template path validation error: {str(e)}"
