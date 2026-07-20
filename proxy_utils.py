"""代理相关工具函数。"""
from __future__ import annotations

import re
import uuid
import urllib.parse


_SESSID_RE = re.compile(r"(^|;)sessid\.[^;]*", re.IGNORECASE)


def mask_proxy_url(proxy: str | None) -> str:
    """日志中隐藏代理密码。

    支持格式：
      - http://user:pass@host:port
      - https://user:pass@host:port
      - socks5://user:pass@host:port
      - socks5h://user:pass@host:port
      - host:port（无认证信息则原样返回）

    解析失败或无密码时原样返回。
    """
    if not proxy:
        return proxy or ""
    try:
        parsed = urllib.parse.urlparse(str(proxy))
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
    except Exception:
        pass
    return str(proxy)


def parse_proxy_pool(text: str) -> list[str]:
    """把多行代理字符串拆成列表。空行 / # 开头注释跳过。"""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _rebuild_proxy_url(
    parsed: urllib.parse.ParseResult,
    username: str,
    password: str | None,
) -> str:
    """重建带 userinfo 的代理 URL；user 中的 `;` `.` `_` 保持不编码（DataImpulse 参数格式）。"""
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    if password is not None:
        netloc = f"{username}:{password}@{host}"
    elif username:
        netloc = f"{username}@{host}"
    else:
        netloc = host
    return parsed._replace(netloc=netloc).geturl()


def proxy_usage_key(proxy: str | None) -> str:
    """用量统计用的稳定 key：去掉 DataImpulse sessid，避免每次 sticky 都算新代理。"""
    if not proxy:
        return ""
    raw = str(proxy).strip()
    try:
        parsed = urllib.parse.urlparse(raw)
        user = urllib.parse.unquote(parsed.username or "")
        if not user or not _SESSID_RE.search(user):
            return raw
        # 去掉 sessid.xxx，清理多余分号
        cleaned = _SESSID_RE.sub("", user)
        cleaned = re.sub(r";{2,}", ";", cleaned).strip(";")
        password = (
            urllib.parse.unquote(parsed.password)
            if parsed.password is not None
            else None
        )
        return _rebuild_proxy_url(parsed, cleaned, password)
    except Exception:
        return raw


def ensure_sticky_proxy(proxy: str | None, session_id: str | None = None) -> str:
    """为住宅代理网关注入 sticky session，保证单次注册全程同出口 IP。

    - DataImpulse (`*.dataimpulse.com`): 用户名追加 `;sessid.<id>`（约 30 分钟绑同一 IP）
    - 已有 `sessid.` 参数：原样返回（尊重用户配置）
    - 其它代理：原样返回

    session_id 不传则每次随机生成。
    """
    if not proxy:
        return proxy or ""
    raw = str(proxy).strip()
    try:
        parsed = urllib.parse.urlparse(raw)
        host = (parsed.hostname or "").lower()
        # 目前仅 DataImpulse 有明确 sessid 语法；其它家保持原 URL
        if "dataimpulse.com" not in host:
            return raw

        user = urllib.parse.unquote(parsed.username or "")
        if not user:
            return raw
        if _SESSID_RE.search(user):
            return raw

        sid = (session_id or "").strip() or uuid.uuid4().hex[:12]
        # 已有 cr/sessttl 等参数时用分号拼接
        new_user = f"{user};sessid.{sid}"
        password = urllib.parse.unquote(parsed.password) if parsed.password is not None else None
        return _rebuild_proxy_url(parsed, new_user, password)
    except Exception:
        return raw
