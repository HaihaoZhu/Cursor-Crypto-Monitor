"""告警与通知发送。"""

from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from typing import Any

from config_loader import AppConfig, load_config

QQ_SMTP_HOST = "smtp.qq.com"
QQ_SMTP_SSL_PORT = 465

# 简单校验，避免把整段说明文字当邮箱发给 QQ
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _strip_one_address(raw: str) -> str:
    s = raw.strip().strip('"').strip("'").strip()
    return s


def _parse_recipients(to_field: str) -> list[str]:
    # 中文标点常见于从网页复制 Secret
    normalized = (
        to_field.replace("，", ",")
        .replace("；", ";")
        .replace("\n", ",")
        .replace("\r", "")
    )
    parts: list[str] = []
    for chunk in normalized.split(";"):
        for sub in chunk.split(","):
            s = _strip_one_address(sub)
            if s:
                parts.append(s)
    return parts


def _validate_addresses(label: str, addrs: list[str]) -> None:
    bad = [a for a in addrs if not _EMAIL_RE.match(a)]
    if bad:
        raise ValueError(
            f"{label} 格式异常（须为单个邮箱，如 a@qq.com；多个用英文逗号分隔）: {bad!r}"
        )


def send_email(subject: str, content: str) -> None:
    """
    使用 smtplib 经 QQ 邮箱（SMTP SSL 465）发送纯文本邮件。
    发件人、授权码、收件人从 ``config_loader.load_config()`` 读取。
    """
    cfg = load_config()
    sender = _strip_one_address(cfg.qq_mail_account)
    password = cfg.qq_mail_auth_code.strip()
    to_list = _parse_recipients(cfg.qq_mail_to)
    if not to_list:
        raise ValueError("收件人列表为空，请检查 QQ_MAIL_TO（或 config.json qq_mail.to）")

    _validate_addresses("收件人 To", to_list)
    _validate_addresses("发件人 From", [sender])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    msg.set_content(content, charset="utf-8")

    try:
        with smtplib.SMTP_SSL(QQ_SMTP_HOST, QQ_SMTP_SSL_PORT, timeout=60) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    except smtplib.SMTPDataError as e:
        raise RuntimeError(
            "QQ SMTP 拒收（常见为收件人无效）。请检查：\n"
            "1) GitHub Secret「QQ_MAIL_TO」是否为真实存在的邮箱，无多余空格/引号/中文逗号；\n"
            "2) 可先设为与发件 QQ_MAIL_ACCOUNT 相同做自发自收测试；\n"
            "3) 若发外域邮箱，确认该地址无误且未被 QQ 限制。\n"
            f"原始错误: {e!r}"
        ) from e


def notify_if_needed(result: dict[str, Any], config: AppConfig) -> None:
    """若策略结果要求通知，则在此发送（控制台、Webhook、邮件等）。"""
    if not result.get("should_notify"):
        return
    message = result.get("message", "")
    print(message)
