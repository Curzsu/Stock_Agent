"""PostgreSQL accounts and opaque browser sessions."""

import argparse
import hashlib
import hmac
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from getpass import getpass
from ipaddress import ip_address
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Security
from fastapi.security import APIKeyCookie
from pwdlib import PasswordHash
from pydantic import BaseModel, Field, SecretStr

from backend.api_models import ApiError


COOKIE_NAME = "finex_session"
SESSION_SECONDS = 8 * 60 * 60
USERNAME_PATTERN = r"^[a-zA-Z0-9._-]{1,64}$"
TOKEN_PATTERN = r"[A-Za-z0-9_-]{43}"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
passwords = PasswordHash.recommended()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
session_cookie = APIKeyCookie(name=COOKIE_NAME, auto_error=False)
router = APIRouter(prefix="/api/session", tags=["session"])
SESSION_ERRORS = {status: {"model": ApiError} for status in (401, 403, 503)}


class LoginRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: SecretStr = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    user_id: UUID
    username: str
    csrf_token: str


@dataclass(frozen=True)
class ActiveSession:
    user_id: UUID
    username: str
    token: str

    def public(self) -> SessionResponse:
        csrf_token = hmac.digest(self.token.encode("ascii"), b"finex csrf v1", "sha256").hex()
        return SessionResponse(user_id=self.user_id, username=self.username, csrf_token=csrf_token)


def connect(database_url: str):
    return psycopg.connect(database_url, connect_timeout=5)


def migrate(database_url: str) -> None:
    with connect(database_url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(462324275819550121)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for migration in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            if migration.name not in applied:
                conn.execute(migration.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (migration.name,))


def create_user(database_url: str, username: str, password: str) -> None:
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise ValueError("用户名须为 1–64 位英文字母、数字、点、下划线或连字符")
    if not 12 <= len(password) <= 256:
        raise ValueError("密码须为 12–256 个字符")
    with connect(database_url) as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (%s, %s, %s)",
            (uuid4(), username.lower(), passwords.hash(password)),
        )


@contextmanager
def account_db():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(503, "会话数据库未配置")
    try:
        with connect(database_url) as conn:
            yield conn
    except psycopg.Error as exc:
        raise HTTPException(503, "会话数据库暂不可用") from exc


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def secure_cookie(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    try:
        loopback = request.client and ip_address(request.client.host).is_loopback
    except ValueError:
        loopback = False
    if request.url.scheme == "http" and loopback and request.url.hostname in {"localhost", "127.0.0.1", "::1"}:
        return False
    raise HTTPException(403, "会话需要 HTTPS 或本机会话入口")


def require_same_origin(request: Request) -> None:
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "请求来源无效")


def require_session(request: Request, token: str | None = Security(session_cookie)) -> ActiveSession:
    secure_cookie(request)
    if token is None or re.fullmatch(TOKEN_PATTERN, token) is None:
        raise HTTPException(401, "请登录")
    with account_db() as conn:
        row = conn.execute(
            """SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = %s AND sessions.expires_at > now() AND users.is_active""",
            (token_hash(token),),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "请登录")
    return ActiveSession(row[0], row[1], token)


def require_session_write(
    request: Request,
    session: ActiveSession = Depends(require_session),
    csrf_token: str = Header(alias="X-CSRF-Token", default=""),
) -> ActiveSession:
    require_same_origin(request)
    if not hmac.compare_digest(csrf_token.encode(), session.public().csrf_token.encode()):
        raise HTTPException(403, "CSRF 令牌无效")
    return session


@router.post("", response_model=SessionResponse, responses={**SESSION_ERRORS, 422: {"model": ApiError}})
def login(credentials: LoginRequest, request: Request, response: Response) -> SessionResponse:
    secure = secure_cookie(request)
    require_same_origin(request)
    with account_db() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s AND is_active",
            (credentials.username.lower(),),
        ).fetchone()
        valid = passwords.verify(credentials.password.get_secret_value(), user[2] if user else dummy_hash)
        if user is None or not valid:
            raise HTTPException(401, "用户名或密码不正确")
        old_token = request.cookies.get(COOKIE_NAME)
        if old_token and re.fullmatch(TOKEN_PATTERN, old_token):
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(old_token),))
        conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s * interval '1 second')",
            (token_hash(token), user[0], SESSION_SECONDS),
        )
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, secure=secure, samesite="lax")
    return ActiveSession(user[0], user[1], token).public()


@router.get("", response_model=SessionResponse, responses=SESSION_ERRORS)
def current_session(session: ActiveSession = Depends(require_session)) -> SessionResponse:
    return session.public()


@router.delete("", status_code=204, responses=SESSION_ERRORS)
def logout(request: Request, session: ActiveSession = Depends(require_session_write)) -> Response:
    with account_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(session.token),))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=secure_cookie(request), samesite="lax")
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage local FINEX accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    commands.add_parser("create-user").add_argument("username")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.exit(1, "请先设置 DATABASE_URL\n")
    try:
        if args.command == "migrate":
            migrate(database_url)
            print("数据库迁移完成")
        else:
            password = getpass("密码: ")
            if password != getpass("确认密码: "):
                raise ValueError("两次密码输入不一致")
            create_user(database_url, args.username, password)
            print(f"已创建账号 {args.username.lower()}")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except psycopg.errors.UniqueViolation:
        parser.exit(1, "用户名已存在\n")
    except psycopg.Error:
        parser.exit(1, "数据库操作失败，请检查连接和迁移状态\n")


if __name__ == "__main__":
    main()
