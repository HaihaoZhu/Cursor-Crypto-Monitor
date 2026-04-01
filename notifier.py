"""告警与通知发送。"""

from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from typing import Any

from config_loader import AppConfig, load_config

# 网易 163 邮箱 SMTP（SSL）
NETEASE_163_SMTP_HOST = "smtp.163.com"
NETEASE_163_SMTP_SSL_PORT = 465

# 简单校验，避免把整段说明文字当邮箱发出
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _strip_one_address(raw: str) -> str:
    s = raw.strip().strip('"').strip("'").strip()
    return s


def _parse_recipients(to_field: str) -> list[str]:
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
            f"{label} 格式异常（须为单个邮箱，如 name@163.com；多个用英文逗号分隔）: {bad!r}"
        )


def send_email(
    subject: str,
    text_body: str,
    *,
    html_body: str | None = None,
) -> None:
    """
    使用 smtplib 经 163 邮箱（SMTP SSL 465）发送邮件。
    若提供 ``html_body``，则为 multipart/alternative（纯文本 + HTML），客户端优先显示表格等样式。
    """
    cfg = load_config()
    sender = _strip_one_address(cfg.mail_163_account)
    password = cfg.mail_163_auth_code.strip()
    to_list = _parse_recipients(cfg.mail_163_to)
    if not to_list:
        raise ValueError(
            "收件人列表为空，请检查 MAIL_163_TO（或 config.json mail_163.to）"
        )

    _validate_addresses("收件人 To", to_list)
    _validate_addresses("发件人 From", [sender])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    msg.set_content(text_body, charset="utf-8")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP_SSL(
            NETEASE_163_SMTP_HOST,
            NETEASE_163_SMTP_SSL_PORT,
            timeout=60,
        ) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    except smtplib.SMTPDataError as e:
        raise RuntimeError(
            "163 SMTP 拒收（常见为收件人无效或授权码错误）。请检查：\n"
            "1) GitHub Secret「MAIL_163_TO」是否为真实存在的邮箱，无多余空格/引号/中文逗号；\n"
            "2)「MAIL_163_AUTH_CODE」须为 163 邮箱设置里的「客户端授权密码」，不是登录密码；\n"
            "3) 可先令 MAIL_163_TO 与发件 MAIL_163_ACCOUNT 相同做自发自收测试。\n"
            f"原始错误: {e!r}"
        ) from e


def notify_if_needed(result: dict[str, Any], config: AppConfig) -> None:
    """若策略结果要求通知，则在此发送（控制台、Webhook、邮件等）。"""
    if not result.get("should_notify"):
        return
    message = result.get("message", "")
    print(message)
