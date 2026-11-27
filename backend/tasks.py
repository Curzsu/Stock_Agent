"""PostgreSQL task admission, checkpoints and private report metadata."""

import os
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.model_versions import read_version, save_version


INTERRUPTED_MESSAGE = "服务重启中断了研究，已保留完成的部分。请重新发起研究。"
SAVE_FAILED_MESSAGE = "研究结果保存失败，已保留上次保存的片段。请重新发起研究。"
ACTIVE_STATUSES = ("pending", "running")
ADMISSION_LOCK = 673001
RUNNER_LOCK = 673002
TASK_SELECT = """
    SELECT t.id, t.owner_id, t.status, t.snapshot, t.config_version_id,
           r.markdown_path, r.pdf_path, r.pdf_status
    FROM analysis_tasks AS t LEFT JOIN report_documents AS r ON r.task_id = t.id
"""


class TaskDatabaseError(HTTPException):
    def __init__(self, cause: psycopg.Error):
        self.retryable = isinstance(cause, (psycopg.OperationalError, psycopg.InterfaceError)) or cause.sqlstate in {
            "40001", "40P01", "55P03", "57014",
        }
        message = "任务数据库暂不可用，请稍后重试" if self.retryable else "任务数据库操作失败"
        super().__init__(503 if self.retryable else 500, message)


class RunnerReplaced(HTTPException):
    def __init__(self):
        super().__init__(503, "此 FINEX 进程已失去任务执行权，请重新启动服务")


def stopped_snapshot(snapshot, error):
    snapshot.update(error=error, current_task=None, end_time=datetime.now().isoformat())
    for agent, state in snapshot["progress"].items():
        if state == "running":
            snapshot["progress"][agent] = "waiting"
    for detail in snapshot["agent_details"].values():
        if detail["status"] == "running":
            detail["status"] = "waiting"
    return snapshot


class TaskStore:
    def __init__(self, database_url, report_root, config_key, *, user_limit=1, global_limit=3):
        self.database_url = database_url
        self.report_root = Path(report_root).expanduser().resolve()
        frontend = (Path(__file__).resolve().parents[1] / "frontend").resolve()
        static_roots = (frontend, (frontend / "assets").resolve(), (frontend / "dist").resolve())
        if any(self.report_root.is_relative_to(root) or root.is_relative_to(self.report_root) for root in static_roots):
            raise ValueError("私有报告目录必须与前端静态文件目录分开")
        self.config_key = config_key
        self.user_limit = user_limit
        self.global_limit = global_limit
        self._run_id = uuid4()
        if min(user_limit, global_limit) < 1:
            raise ValueError("任务并发上限必须为正整数")

    @classmethod
    def from_environment(cls):
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise HTTPException(503, "任务数据库未配置")
        default_root = Path(__file__).resolve().parents[1] / "agents" / "reports" / "workbench"
        return cls(database_url, os.getenv("FINEX_REPORT_DIR") or default_root, os.getenv("FINEX_MODEL_CONFIG_KEY", ""),
                   user_limit=int(os.getenv("FINEX_MAX_USER_TASKS", "1")),
                   global_limit=int(os.getenv("FINEX_MAX_ACTIVE_TASKS", "3")))

    @contextmanager
    def transaction(self, *, startup=False):
        try:
            with closing(psycopg.connect(self.database_url, connect_timeout=5, row_factory=dict_row)) as conn, conn.transaction():
                if not startup:
                    row = conn.execute("SELECT run_id FROM task_runner WHERE singleton FOR SHARE").fetchone()
                    if row is None or row["run_id"] != self._run_id:
                        raise RunnerReplaced()
                yield conn
        except psycopg.Error as exc:
            raise TaskDatabaseError(exc) from exc

    def claim_runner(self):
        """Hold a separate connection while the single local executor is running."""
        conn = psycopg.connect(self.database_url, connect_timeout=5, autocommit=True)
        try:
            claimed, = conn.execute("SELECT pg_try_advisory_lock(%s, hashtext(current_schema()))", (RUNNER_LOCK,)).fetchone()
            if not claimed:
                raise RuntimeError("任务数据库已有 FINEX 执行进程，请停止旧进程后再启动")
        except BaseException:
            conn.close()
            raise
        return conn

    def task_directory(self, task_id: str) -> Path:
        if UUID(task_id).hex != task_id:
            raise ValueError("无效的任务文件目录")
        expected = self.report_root / task_id
        if expected.resolve() != expected:
            raise ValueError("任务文件目录不能是链接")
        return expected

    def private_path(self, relative_path: str) -> Path:
        path = (self.report_root / relative_path).resolve()
        if path == self.report_root or not path.is_relative_to(self.report_root):
            raise ValueError("报告位置超出私有目录")
        return path

    def relative_path(self, task_id: str, path: str) -> str:
        resolved = Path(path).resolve()
        task_dir = self.task_directory(task_id)
        if not resolved.is_relative_to(task_dir) or resolved == task_dir:
            raise ValueError("报告位置不属于当前任务")
        return resolved.relative_to(self.report_root).as_posix()

    def artifact_path(self, task_id: str, relative_path: str) -> Path:
        path = self.private_path(relative_path)
        self.relative_path(task_id, str(path))
        return path

    def _admission_lock(self, conn):
        conn.execute("SELECT pg_advisory_xact_lock(%s, hashtext(current_schema()))", (ADMISSION_LOCK,))

    def _check_capacity(self, conn, owner_id):
        capacity = conn.execute(
            """SELECT count(*) AS total, count(*) FILTER (WHERE owner_id = %s) AS owned
               FROM analysis_tasks WHERE status IN ('pending', 'running') AND deleted_at IS NULL""",
            (owner_id,),
        ).fetchone()
        if capacity["owned"] >= self.user_limit:
            raise HTTPException(429, "你的研究任务已达并发上限，请等待完成后重试", headers={"Retry-After": "2"})
        if capacity["total"] >= self.global_limit:
            raise HTTPException(429, "研究服务繁忙，请稍后重试", headers={"Retry-After": "2"})

    def create(self, task_id, owner_id, key, query, snapshot, profile, settings):
        with self.transaction() as conn:
            self._admission_lock(conn)
            if key is not None:
                prior = conn.execute(
                    "SELECT id, query, deleted_at FROM analysis_tasks WHERE owner_id = %s AND idempotency_key = %s",
                    (owner_id, key),
                ).fetchone()
                if prior is not None:
                    if prior["query"] != query or prior["deleted_at"] is not None:
                        raise HTTPException(409, "该提交标识已使用，请发起新的研究")
                    return prior["id"], False
            self._check_capacity(conn, owner_id)
            version_id = save_version(conn, self.config_key, profile, settings)
            conn.execute(
                """INSERT INTO analysis_tasks (id, owner_id, idempotency_key, query, status, snapshot, config_version_id)
                   VALUES (%s, %s, %s, %s, 'pending', %s, %s)""",
                (task_id, owner_id, key, query, Jsonb(snapshot), version_id),
            )
        return task_id, True

    def _restore(self, row):
        result = dict(row["snapshot"])
        result.update(analysis_id=row["id"], owner_id=row["owner_id"], status=row["status"])
        if result.get("result") is not None and row["markdown_path"]:
            result["result"].update(
                report_path=str(self.artifact_path(row["id"], row["markdown_path"])),
                pdf_path=str(self.artifact_path(row["id"], row["pdf_path"])),
                pdf_available=row["pdf_status"] == "ready", pdf_status=row["pdf_status"],
            )
        return result

    def _owned_row(self, conn, owner_id, task_id, *, for_update=False):
        statement = TASK_SELECT + " WHERE t.owner_id = %s AND t.id = %s AND t.deleted_at IS NULL"
        if for_update:
            statement += " FOR UPDATE OF t"
        row = conn.execute(statement, (owner_id, task_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Analysis not found")
        return row

    def get(self, owner_id, task_id):
        with self.transaction() as conn:
            return self._restore(self._owned_row(conn, owner_id, task_id))

    def history(self, owner_id):
        with self.transaction() as conn:
            rows = conn.execute("""
                SELECT id AS analysis_id, status, snapshot->>'api_profile' AS api_profile,
                       COALESCE(NULLIF(snapshot#>>'{result,company_name}', ''),
                                NULLIF(snapshot->>'company_name', ''), query) AS company_name,
                       COALESCE(snapshot#>>'{result,stock_code}', '') AS stock_code,
                       COALESCE(NULLIF(snapshot#>>'{result,analysis_date}', ''), snapshot->>'start_time', '') AS analysis_date
                FROM analysis_tasks WHERE owner_id = %s AND deleted_at IS NULL
                ORDER BY created_at DESC, id DESC LIMIT 10
            """, (owner_id,)).fetchall()
            return list(reversed(rows))

    def retry(self, owner_id, task_id, prepare):
        with self.transaction() as conn:
            self._admission_lock(conn)
            row = self._owned_row(conn, owner_id, task_id, for_update=True)
            session, snapshot = prepare(self._restore(row))
            self._check_capacity(conn, owner_id)
            settings = read_version(conn, self.config_key, row["config_version_id"])
            conn.execute("UPDATE analysis_tasks SET status = 'running', snapshot = %s WHERE id = %s", (Jsonb(snapshot), task_id))
            return session, settings

    def checkpoint(self, task_id, owner_id, status, snapshot, report=None):
        with self.transaction() as conn:
            updated = conn.execute(
                """UPDATE analysis_tasks SET status = %s, snapshot = %s
                   WHERE id = %s AND owner_id = %s AND status IN ('pending', 'running') AND deleted_at IS NULL""",
                (status, Jsonb(snapshot), task_id, owner_id),
            )
            if updated.rowcount != 1:
                return False
            if report is not None:
                conn.execute(
                    """INSERT INTO report_documents
                       (task_id, owner_id, document_id, stock_code, report_date, markdown_path, pdf_path, pdf_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (task_id) DO UPDATE SET
                           stock_code = EXCLUDED.stock_code, report_date = EXCLUDED.report_date,
                           markdown_path = EXCLUDED.markdown_path, pdf_path = EXCLUDED.pdf_path,
                           pdf_status = EXCLUDED.pdf_status,
                           content_version = report_documents.content_version
                               + (report_documents.markdown_path <> EXCLUDED.markdown_path)::integer""",
                    (task_id, owner_id, uuid4(), *report),
                )
        return True

    def update_pdf(self, task_id, markdown_path, status):
        with self.transaction() as conn:
            conn.execute(
                "UPDATE report_documents SET pdf_status = %s WHERE task_id = %s AND markdown_path = %s",
                (status, task_id, markdown_path),
            )

    def fail_checkpoint(self, task_id, owner_id):
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT snapshot FROM analysis_tasks WHERE id = %s AND owner_id = %s
                   AND status IN ('pending', 'running') AND deleted_at IS NULL FOR UPDATE""",
                (task_id, owner_id),
            ).fetchone()
            if row is not None:
                snapshot = stopped_snapshot(row["snapshot"], SAVE_FAILED_MESSAGE)
                conn.execute("UPDATE analysis_tasks SET status = 'error', snapshot = %s WHERE id = %s",
                             (Jsonb(snapshot), task_id))

    def recover(self):
        with self.transaction(startup=True) as conn:
            conn.execute("""INSERT INTO task_runner (singleton, run_id) VALUES (TRUE, %s)
                            ON CONFLICT (singleton) DO UPDATE SET run_id = EXCLUDED.run_id""", (self._run_id,))
            self._admission_lock(conn)
            abandoned = conn.execute(
                "SELECT id, snapshot FROM analysis_tasks WHERE status IN ('pending', 'running') FOR UPDATE",
            ).fetchall()
            for row in abandoned:
                snapshot = stopped_snapshot(row["snapshot"], INTERRUPTED_MESSAGE)
                conn.execute("UPDATE analysis_tasks SET status = 'interrupted', snapshot = %s WHERE id = %s",
                             (Jsonb(snapshot), row["id"]))
            pending = conn.execute("SELECT task_id, pdf_path FROM report_documents WHERE pdf_status = 'pending'").fetchall()
            for report in pending:
                path = self.artifact_path(report["task_id"], report["pdf_path"])
                status = "ready" if path.is_file() and path.stat().st_size else "failed"
                conn.execute("UPDATE report_documents SET pdf_status = %s WHERE task_id = %s", (status, report["task_id"]))
            return conn.execute("SELECT owner_id, id FROM analysis_tasks WHERE cleanup_pending").fetchall()

    def delete(self, owner_id, task_id, ensure_files_idle, cleanup):
        with self.transaction() as conn:
            row = conn.execute("""SELECT status, deleted_at, cleanup_pending FROM analysis_tasks
                                  WHERE id = %s AND owner_id = %s FOR UPDATE""", (task_id, owner_id)).fetchone()
            if row is None or (row["deleted_at"] is not None and not row["cleanup_pending"]):
                raise HTTPException(404, "Analysis not found")
            if row["status"] in ACTIVE_STATUSES:
                raise HTTPException(409, "分析任务正在进行中，无法删除")
            if row["deleted_at"] is None:
                ensure_files_idle(self.task_directory(task_id))
                conn.execute("DELETE FROM report_documents WHERE task_id = %s", (task_id,))
                conn.execute("""UPDATE analysis_tasks SET deleted_at = now(), cleanup_pending = TRUE,
                                query = '', snapshot = '{}'::jsonb WHERE id = %s""", (task_id,))
        self.finish_cleanup(owner_id, task_id, cleanup)

    def finish_cleanup(self, owner_id, task_id, cleanup):
        with self.transaction() as conn:
            row = conn.execute("""SELECT id FROM analysis_tasks WHERE id = %s AND owner_id = %s
                                  AND cleanup_pending FOR UPDATE""", (task_id, owner_id)).fetchone()
            if row is not None:
                cleanup(self.task_directory(task_id))
                conn.execute("UPDATE analysis_tasks SET cleanup_pending = FALSE WHERE id = %s", (task_id,))
