"""配置加载：环境变量优先，缺失时从项目根目录的 config.json 读取。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


# 环境变量名（与 OKX / QQ 邮箱、GitHub Actions Secrets 一致）
ENV_OKX_API_KEY = "OKX_API_KEY"
ENV_OKX_API_SECRET = "OKX_API_SECRET"
# 部分教程使用此名；与 OKX_API_SECRET 二选一即可
ENV_OKX_SECRET_KEY_ALT = "OKX_SECRET_KEY"
ENV_OKX_PASSPHRASE = "OKX_PASSPHRASE"
ENV_QQ_MAIL_ACCOUNT = "QQ_MAIL_ACCOUNT"
ENV_QQ_MAIL_AUTH_CODE = "QQ_MAIL_AUTH_CODE"
ENV_QQ_MAIL_TO = "QQ_MAIL_TO"

# 兼容：GitHub Actions 只认环境变量；本地未设置时可由 load_config 回退到 config.json。
# 使用 or "" 表示「未注入」；勿在仓库中填写真实密钥。合并仍以 load_config() 内 os.getenv 为准（每次调用重新读取）。
OKX_API_KEY = os.getenv(ENV_OKX_API_KEY) or ""
OKX_API_SECRET = os.getenv(ENV_OKX_API_SECRET) or ""
OKX_PASSPHRASE = os.getenv(ENV_OKX_PASSPHRASE) or ""
QQ_MAIL_ACCOUNT = os.getenv(ENV_QQ_MAIL_ACCOUNT) or ""
QQ_MAIL_AUTH_CODE = os.getenv(ENV_QQ_MAIL_AUTH_CODE) or ""
QQ_MAIL_TO = os.getenv(ENV_QQ_MAIL_TO) or ""


@dataclass(frozen=True)
class AppConfig:
    okx_api_key: str
    okx_api_secret: str
    okx_passphrase: str
    qq_mail_account: str
    qq_mail_auth_code: str
    qq_mail_to: str


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s if s else None


def _from_json_nested(root: dict, *path: str) -> str | None:
    d: object = root
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    if d is None:
        return None
    return _strip_or_none(str(d))


def _load_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _resolve(
    env_name: str,
    file_root: dict,
    *json_path: str,
) -> str | None:
    v = _strip_or_none(os.getenv(env_name))
    if v is not None:
        return v
    return _from_json_nested(file_root, *json_path)


def load_config(config_path: Path | None = None) -> AppConfig:
    """
    合并配置：每个字段先读环境变量，否则读 config.json。

    config_path 默认：与本模块同目录下的 config.json。
    任一必填项仍为空时抛出 ValueError。
    """
    path = config_path or (Path(__file__).resolve().parent / "config.json")
    file_root = _load_json_file(path)

    okx_key = _resolve(ENV_OKX_API_KEY, file_root, "okx", "api_key")
    okx_secret = _resolve(ENV_OKX_API_SECRET, file_root, "okx", "api_secret")
    if not okx_secret:
        okx_secret = _strip_or_none(os.getenv(ENV_OKX_SECRET_KEY_ALT))
    okx_pass = _resolve(ENV_OKX_PASSPHRASE, file_root, "okx", "passphrase")
    qq_account = _resolve(ENV_QQ_MAIL_ACCOUNT, file_root, "qq_mail", "account")
    qq_auth = _resolve(ENV_QQ_MAIL_AUTH_CODE, file_root, "qq_mail", "auth_code")
    qq_to = _resolve(ENV_QQ_MAIL_TO, file_root, "qq_mail", "to")

    missing: list[str] = []
    if not okx_key:
        missing.append(f"{ENV_OKX_API_KEY} 或 okx.api_key")
    if not okx_secret:
        missing.append(
            f"{ENV_OKX_API_SECRET}（或 {ENV_OKX_SECRET_KEY_ALT}）或 okx.api_secret"
        )
    if not okx_pass:
        missing.append(f"{ENV_OKX_PASSPHRASE} 或 okx.passphrase")
    if not qq_account:
        missing.append(f"{ENV_QQ_MAIL_ACCOUNT} 或 qq_mail.account")
    if not qq_auth:
        missing.append(f"{ENV_QQ_MAIL_AUTH_CODE} 或 qq_mail.auth_code")
    if not qq_to:
        missing.append(f"{ENV_QQ_MAIL_TO} 或 qq_mail.to")

    if missing:
        msg = (
            "以下配置未设置（请设置对应环境变量，或在 config.json 中填写）：\n  - "
            + "\n  - ".join(missing)
        )
        if os.getenv("GITHUB_ACTIONS") == "true":
            msg += (
                "\n\n若在 GitHub Actions 中运行：请到仓库 "
                "Settings → Secrets and variables → Actions → New repository secret，"
                "名称须与上述环境变量名完全一致（含 QQ_MAIL_*）。"
            )
        raise ValueError(msg)

    return AppConfig(
        okx_api_key=okx_key,
        okx_api_secret=okx_secret,
        okx_passphrase=okx_pass,
        qq_mail_account=qq_account,
        qq_mail_auth_code=qq_auth,
        qq_mail_to=qq_to,
    )


if __name__ == "__main__":
    import sys

    default_json = Path(__file__).resolve().parent / "config.json"
    try:
        cfg = load_config()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print("配置加载成功。")
    print(f"规则：环境变量优先；未设置时从 {default_json} 读取。")
    print("当前各必填项均已解析（不在此打印具体密钥）：")
    print(f"  OKX API Key: 已设置（{len(cfg.okx_api_key)} 字符）")
    print(f"  OKX API Secret: 已设置（{len(cfg.okx_api_secret)} 字符）")
    print(f"  OKX Passphrase: 已设置（{len(cfg.okx_passphrase)} 字符）")
    print(f"  QQ 邮箱账号: {cfg.qq_mail_account}")
    print(f"  QQ 邮箱授权码: 已设置（{len(cfg.qq_mail_auth_code)} 字符）")
    print(f"  收件人: {cfg.qq_mail_to}")
