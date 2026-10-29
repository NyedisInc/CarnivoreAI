
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Iterable, List, Optional

import structlog

from src.core import resource_push
from src.core.companies import lineage
from src.core.db import table_exists, transaction
from src.core.resource_push import topics as resource_topics
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

MAX_NAME_LENGTH = 80


class CompanyNameInvalid(ValueError):
    pass


class CompanyNameConflict(Exception):
    pass


class CompanyNotFound(Exception):
    pass


class ProjectNotFound(Exception):
    pass


def clean_name(raw: Any) -> str:
    name = raw.strip() if isinstance(raw, str) else ""
    if not name or len(name) > MAX_NAME_LENGTH:
        raise CompanyNameInvalid(f"a company name is 1 to {MAX_NAME_LENGTH} characters")
    return name


def _notify() -> None:
    resource_push.notify(resource_topics.COMPANIES)
    resource_push.notify(resource_topics.PROJECTS)


def _company_columns(conn: sqlite3.Connection) -> set:
    return {r[1] for r in conn.execute("PRAGMA table_info(companies)")}


def list_companies(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    if not table_exists(conn, "companies"):
        return []
    present = _company_columns(conn)
    optional = ", ".join(f"{'c.' + col if col in present else 'NULL'} AS {col}" for col in ("hue", "parent_id", "hq_project_id"))
    rows = conn.execute(
        f"SELECT c.id, c.name, {optional}, COUNT(p.id) AS project_count FROM companies c "
        "LEFT JOIN projects p ON p.company_id = c.id GROUP BY c.id ORDER BY c.name COLLATE NOCASE, c.id"
    ).fetchall()
    return [{"id": r["id"], "name": r["name"], "project_count": r["project_count"], "hue": r["hue"],
             "parent_id": r["parent_id"], "hq_project_id": r["hq_project_id"]} for r in rows]


def get_company(conn: sqlite3.Connection, company_id: int) -> Dict[str, Any]:
    for company in list_companies(conn):
        if company["id"] == company_id:
            return company
    raise CompanyNotFound(str(company_id))


def create_company(conn: sqlite3.Connection, name: str, parent_id: Optional[int] = None) -> Dict[str, Any]:
    clean = clean_name(name)
    stamp = utc_now()
    try:
        with transaction(conn):
            if parent_id is not None:
                _check_parent(conn, None, parent_id)
                cur = conn.execute(
                    "INSERT INTO companies (name, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (clean, parent_id, stamp, stamp),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO companies (name, created_at, updated_at) VALUES (?, ?, ?)", (clean, stamp, stamp)
                )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise CompanyNameConflict(clean)
    logger.info("company_created", company_id=new_id, parent_id=parent_id)
    _notify()
    return get_company(conn, new_id)


def _check_parent(conn: sqlite3.Connection, company_id: Optional[int], parent_id: int) -> None:
    parents = lineage.parent_map(conn)
    if parent_id not in parents:
        raise CompanyNotFound(str(parent_id))
    lineage.validate_parent(parents, company_id, parent_id)


def set_parent(conn: sqlite3.Connection, company_id: int, parent_id: Optional[int]) -> Dict[str, Any]:
    with transaction(conn):
        if conn.execute("SELECT 1 FROM companies WHERE id = ?", (company_id,)).fetchone() is None:
            raise CompanyNotFound(str(company_id))
        if parent_id is not None:
            _check_parent(conn, company_id, parent_id)
        conn.execute("UPDATE companies SET parent_id = ?, updated_at = ? WHERE id = ?", (parent_id, utc_now(), company_id))
    logger.info("company_parent_set", company_id=company_id, parent_id=parent_id)
    _notify()
    return get_company(conn, company_id)


def rename_company(conn: sqlite3.Connection, company_id: int, name: str) -> Dict[str, Any]:
    clean = clean_name(name)
    try:
        with transaction(conn):
            cur = conn.execute(
                "UPDATE companies SET name = ?, updated_at = ? WHERE id = ?", (clean, utc_now(), company_id)
            )
            if cur.rowcount == 0:
                raise CompanyNotFound(str(company_id))
    except sqlite3.IntegrityError:
        raise CompanyNameConflict(clean)
    logger.info("company_renamed", company_id=company_id)
    _notify()
    return get_company(conn, company_id)


def set_company_hue(conn: sqlite3.Connection, company_id: int, hue: Optional[int]) -> Dict[str, Any]:
    if hue is not None and (type(hue) is not int or not 0 <= hue <= 359):
        raise ValueError("hue must be a whole number from 0 to 359")
    with transaction(conn):
        cur = conn.execute("UPDATE companies SET hue = ?, updated_at = ? WHERE id = ?", (hue, utc_now(), company_id))
        if cur.rowcount == 0:
            raise CompanyNotFound(str(company_id))
    logger.info("company_hue_set", company_id=company_id, hue=hue)
    _notify()
    return get_company(conn, company_id)


def delete_company(conn: sqlite3.Connection, company_id: int) -> Dict[str, int]:
    with transaction(conn):
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise CompanyNotFound(str(company_id))
        orphaned = conn.execute(
            "UPDATE projects SET company_id = NULL WHERE company_id = ?", (company_id,)
        ).rowcount
        moved = 0
        if "parent_id" in row.keys():
            moved = conn.execute(
                "UPDATE companies SET parent_id = ?, updated_at = ? WHERE parent_id = ?",
                (row["parent_id"], utc_now(), company_id),
            ).rowcount
        conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    logger.info("company_deleted", company_id=company_id, orphaned=orphaned, children_moved=moved)
    _notify()
    return {"orphaned": orphaned, "children_moved": moved}


def assign_project(conn: sqlite3.Connection, project_id: int, company_id: Optional[int]) -> None:
    with transaction(conn):
        if company_id is not None and conn.execute(
            "SELECT 1 FROM companies WHERE id = ?", (company_id,)
        ).fetchone() is None:
            raise CompanyNotFound(str(company_id))
        cur = conn.execute(
            "UPDATE projects SET company_id = ?, updated_at = ? WHERE id = ?", (company_id, utc_now(), project_id)
        )
        if cur.rowcount == 0:
            raise ProjectNotFound(str(project_id))
    logger.info("project_company_set", project_id=project_id, company_id=company_id)
    _notify()


def set_hq_project(conn: sqlite3.Connection, company_id: int, project_id: Optional[int]) -> Dict[str, Any]:
    with transaction(conn):
        if project_id is not None and conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ProjectNotFound(str(project_id))
        cur = conn.execute("UPDATE companies SET hq_project_id = ?, updated_at = ? WHERE id = ?", (project_id, utc_now(), company_id))
        if cur.rowcount == 0:
            raise CompanyNotFound(str(company_id))
    logger.info("company_hq_set", company_id=company_id, project_id=project_id)
    _notify()
    return get_company(conn, company_id)


def attach_company_names(conn: sqlite3.Connection, rows: Iterable[Dict[str, Any]]) -> None:
    names: Dict[int, str] = {}
    if table_exists(conn, "companies"):
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM companies")}
    for row in rows:
        company_id = row.get("company_id")
        row["company_id"] = company_id
        row["company_name"] = names.get(company_id) if company_id is not None else None
