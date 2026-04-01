"""告警与通知发送。"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from config_loader import AppConfig, load_config

QQ_SMTP_HOST = "smtp.qq.com"
QQ_SMTP_SSL_PORT = 465


def _parse_recipients(to_field: str) -> list[str]:
    parts: list[str] = []
    for chunk in to_field.replace(";", ",").split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


def send_email(subject: str, content: str) -> None:
    """
    使用 smtplib 经 QQ 邮箱（SMTP SSL 465）发送纯文本邮件。
    发件人、授权码、收件人从 ``config_loader.load_config()`` 读取。
    """
    cfg = load_config()
    to_list = _parse_recipients(cfg.qq_mail_to)
    if not to_list:
        raise ValueError("收件人列表为空")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.qq_mail_account
    msg["To"] = ", ".join(to_list)
    msg.set_content(content, charset="utf-8")

    with smtplib.SMTP_SSL(QQ_SMTP_HOST, QQ_SMTP_SSL_PORT, timeout=60) as smtp:
        smtp.login(cfg.qq_mail_account, cfg.qq_mail_auth_code)
        smtp.send_message(msg)


def notify_if_needed(result: dict[str, Any], config: AppConfig) -> None:
    """若策略结果要求通知，则在此发送（控制台、Webhook、邮件等）。"""
    if not result.get("should_notify"):
        return
    message = result.get("message", "")
    print(message)
