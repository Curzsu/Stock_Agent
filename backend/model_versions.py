"""Encrypt immutable provider settings and retain references to revoked versions."""

import base64
import hmac
import json
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException


def save_version(conn, key: str, profile: str, settings: tuple[str, str, str, str]):
    if not key:
        raise HTTPException(503, "请先设置 FINEX_MODEL_CONFIG_KEY")
    try:
        cipher = Fernet(key)
    except ValueError as exc:
        raise HTTPException(503, "FINEX_MODEL_CONFIG_KEY 格式无效") from exc
    payload = json.dumps((profile, *settings), ensure_ascii=False).encode()
    fingerprint = hmac.digest(base64.urlsafe_b64decode(key), b"FINEX model version\0" + payload, "sha256").hex()
    existing = conn.execute(
        "SELECT id, revoked_at FROM model_config_versions WHERE fingerprint = %s FOR SHARE", (fingerprint,),
    ).fetchone()
    if existing:
        if existing["revoked_at"] is not None:
            raise HTTPException(409, "当前模型配置版本已撤销，请更新本机模型配置后重新提交")
        return existing["id"]
    version_id = uuid4()
    conn.execute(
        "INSERT INTO model_config_versions (id, profile, fingerprint, ciphertext) VALUES (%s, %s, %s, %s)",
        (version_id, profile, fingerprint, cipher.encrypt(payload)),
    )
    return version_id


def read_version(conn, key: str, version_id) -> tuple[str, str, str, str]:
    row = conn.execute(
        "SELECT ciphertext FROM model_config_versions WHERE id = %s AND revoked_at IS NULL FOR SHARE", (version_id,),
    ).fetchone()
    if row and key:
        try:
            _, secret, url, model, summary_mode = json.loads(Fernet(key).decrypt(row["ciphertext"]))
            return secret, url, model, summary_mode
        except (InvalidToken, ValueError, TypeError):
            pass
    raise HTTPException(409, "原模型配置版本已撤销或不可读取，请重新提交研究")
