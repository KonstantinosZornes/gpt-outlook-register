"""OutlookEmailPlus 平台接码 Provider（对接 outlookEmailPlus 的 /api/external/*）。

把远端 OutlookEmailPlus 服务当成"邮箱池 + 取码"黑盒：
  1. claim-random  → 从平台池 claim 一个 outlook 邮箱
  2. verification-code → 轮询取 OTP
  3. claim-complete(result=success / provider_blocked) → 回传结果
  4. claim-release → 中途放弃，把号还回 available

能力：pooled=False（不走本地号池，远端平台自己管池）
      ephemeral=False（地址来自平台池，是固定 outlook 号）
      platform=True（远端平台，WebUI 按平台型渲染）
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Optional

from .base import ConfigField, MailProvider, MailProviderError, register

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "outlook"
POLL_INTERVAL = 4


class OEPError(Exception):
    """平台返回 success=false 且非"暂无邮件"类错误时抛出。"""

    def __init__(self, code: str, message: str = "", status: int = 0):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(f"OEP {code}: {message}")


def _parse_iso_utc(s: str) -> float:
    """ISO8601 (如 '2026-07-04T07:37:18Z') → UTC timestamp。失败返回 0。"""
    if not s:
        return 0.0
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _api(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
    timeout: int = 30,
) -> dict:
    """调平台 /api/external/* 接口，返回解析后的 JSON dict。"""
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None and v != ""}
        )
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("X-API-Key", api_key)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            return json.loads(raw) if raw else {}
        except Exception:
            raise OEPError("HTTP_ERROR", f"{e.code} {e.reason}", status=e.code)
    return json.loads(raw) if raw else {}


@register
class OutlookEmailPlusProvider(MailProvider):
    """对接 outlookEmailPlus 平台的 MailProvider。"""

    kind = "oep"
    display_name = "OutlookEmailPlus 平台"
    pooled = False
    ephemeral = False
    platform = True
    supports_specified_email = True

    line_segments = 0
    import_hint = ""
    import_placeholder = ""

    config_fields = [
        ConfigField(
            "oep_api_url", "平台地址",
            placeholder="https://oep.example.com",
            help="OutlookEmailPlus 的 HTTPS 地址，末尾不带斜杠",
        ),
        ConfigField(
            "oep_api_key", "API Key", type="password",
            help="平台签发的 X-API-Key",
        ),
        ConfigField(
            "oep_project_key", "项目 Key", required=False,
            placeholder="可选",
            help="平台 project_key，用于长期邮箱回池复用；可留空",
        ),
        ConfigField(
            "oep_caller_id", "调用方 ID", required=False,
            placeholder="gpt-outlook-register",
            help="平台 caller_id，默认 gpt-outlook-register",
        ),
    ]

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        caller_id: str = "gpt-outlook-register",
        project_key: str = "",
        provider: str = DEFAULT_PROVIDER,
    ):
        if not api_url:
            raise ValueError("api_url 不能为空")
        if not api_key:
            raise ValueError("api_key 不能为空")
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.caller_id = caller_id or "gpt-outlook-register"
        self.project_key = project_key or ""
        self.provider = provider or DEFAULT_PROVIDER
        self._task_id = f"reg-{uuid.uuid4().hex[:12]}"
        self._account_id: Optional[int] = None
        self._claim_token: str = ""
        self.email: str = ""
        self.password: str = ""
        self.last_persona = None
        self.catch_all_domain = ""
        self._dead = False
        self._claim_done = False
        self._fixed_email: str = ""

    @classmethod
    def from_config(cls, settings: dict, account: Optional[dict] = None):
        api_url = (settings.get("oep_api_url") or "").strip()
        api_key = (settings.get("oep_api_key") or "").strip()
        if not api_url or not api_key:
            raise RuntimeError(
                "OutlookEmailPlus 未配置完整（缺 api_url / api_key），"
                "请去「邮箱配置」Tab 填写"
            )
        return cls(
            api_url=api_url,
            api_key=api_key,
            caller_id=(settings.get("oep_caller_id") or "").strip() or "gpt-outlook-register",
            project_key=(settings.get("oep_project_key") or "").strip(),
        )

    def set_specified_email(self, email: str) -> tuple[bool, str]:
        em = (email or "").strip()
        if not em:
            return False, "邮箱为空"
        ok, msg = self.check_accessible(em)
        if not ok:
            return False, msg
        self.set_fixed_email(em)
        return True, "ok"

    def set_fixed_email(self, email: str) -> None:
        em = (email or "").strip()
        if not em:
            return
        self._fixed_email = em
        self.email = em
        self.catch_all_domain = em.split("@", 1)[-1] if "@" in em else ""
        logger.info(f"[oep] 使用指定邮箱: {em} (跳过 claim-random)")

    def check_accessible(self, email: str) -> tuple[bool, str]:
        em = (email or "").strip()
        if not em:
            return False, "邮箱为空"
        try:
            d = _api(
                self.api_url, self.api_key, "GET",
                "/api/external/account-status",
                params={"email": em}, timeout=20,
            )
        except Exception as e:
            return False, f"account-status 调用失败: {e}"
        if not d.get("success"):
            code = d.get("code", "UNKNOWN")
            msg = d.get("message", "")
            return False, f"{code}: {msg}" if msg else code
        data = d.get("data") or {}
        exists = bool(data.get("exists"))
        can_read = bool(data.get("can_read"))
        if not exists:
            return False, "平台不存在该邮箱"
        if not can_read:
            return False, "邮箱存在但当前 API key 无读取权限"
        return True, "ok"

    def _claim(self) -> str:
        params = {
            "caller_id": self.caller_id,
            "task_id": self._task_id,
            "provider": self.provider,
        }
        if self.project_key:
            params["project_key"] = self.project_key
        d = _api(
            self.api_url, self.api_key, "POST",
            "/api/external/pool/claim-random", body=params,
        )
        if not d.get("success"):
            code = d.get("code", "UNKNOWN")
            if code == "no_available_account":
                raise RuntimeError("OutlookEmailPlus 池中没有可用邮箱")
            raise OEPError(code, d.get("message", ""))
        data = d["data"]
        self._account_id = int(data["account_id"])
        self._claim_token = data["claim_token"]
        self.email = data["email"]
        self.catch_all_domain = data.get("email_domain") or self.email.split("@", 1)[-1]
        return self.email

    def _claim_complete(self, result: str, detail: str = "") -> bool:
        if self._claim_done or not self._account_id:
            return False
        self._claim_done = True
        d = _api(
            self.api_url, self.api_key, "POST",
            "/api/external/pool/claim-complete",
            body={
                "account_id": self._account_id,
                "claim_token": self._claim_token,
                "caller_id": self.caller_id,
                "task_id": self._task_id,
                "result": result,
                "detail": detail,
            },
        )
        ok = bool(d.get("success"))
        status = (d.get("data") or {}).get("pool_status", "")
        logger.info(f"[oep] claim-complete result={result} ok={ok} pool_status={status}")
        return ok

    def _claim_release(self, reason: str = "") -> bool:
        if self._claim_done or not self._account_id:
            return False
        self._claim_done = True
        d = _api(
            self.api_url, self.api_key, "POST",
            "/api/external/pool/claim-release",
            body={
                "account_id": self._account_id,
                "claim_token": self._claim_token,
                "caller_id": self.caller_id,
                "task_id": self._task_id,
                "reason": reason,
            },
        )
        ok = bool(d.get("success"))
        logger.info(f"[oep] claim-release ok={ok} reason={reason!r}")
        return ok

    def _fetch_code(self, since_ts: float) -> Optional[str]:
        since_minutes = max(1, int((time.time() - since_ts) / 60) + 1)
        d = _api(
            self.api_url, self.api_key, "GET",
            "/api/external/verification-code",
            params={
                "email": self.email,
                "since_minutes": since_minutes,
                "from_contains": "openai.com",
                "code_source": "content",
                "code_length": "6-6",
            },
        )
        if d.get("success"):
            data = d.get("data") or {}
            code = data.get("verification_code") or ""
            if not code:
                return None
            received_str = data.get("received_at") or ""
            received_ts = _parse_iso_utc(received_str)
            if received_ts and received_ts < since_ts:
                logger.warning(
                    f"[oep] 丢弃旧邮件 email={self.email} code={code} "
                    f"received_at={received_str} (< since_ts={int(since_ts)}), "
                    f"平台 since_minutes={since_minutes} fallback 返回了过期邮件"
                )
                return None
            frm = (data.get("from") or "")[:60]
            logger.info(
                f"[oep] OTP 命中 email={self.email} code={code} from={frm} "
                f"received_at={received_str}"
            )
            return str(code)
        code = d.get("code", "")
        if code in ("MAIL_NOT_FOUND", "VERIFICATION_CODE_NOT_FOUND"):
            return None
        if code in (
            "ACCOUNT_NOT_FOUND", "ACCOUNT_ACCESS_FORBIDDEN",
            "UPSTREAM_READ_FAILED", "EMAIL_SCOPE_FORBIDDEN",
        ):
            raise OEPError(code, d.get("message", ""))
        raise OEPError(code or "UNKNOWN", d.get("message", ""))

    def create_mailbox(self) -> str:
        if self._fixed_email:
            logger.info(f"[oep] 使用指定邮箱: {self._fixed_email} (无 account_id，跳过 claim)")
            self.email = self._fixed_email
            return self._fixed_email
        email = self._claim()
        logger.info(f"[oep] claim 成功: {email} (account_id={self._account_id})")
        return email

    def wait_for_otp(
        self,
        email_addr: str,
        timeout: int = 120,
        issued_after: Optional[float] = None,
    ) -> str:
        if email_addr and email_addr.lower() != self.email.lower():
            logger.warning(
                f"[oep] wait_for_otp 传入 email={email_addr!r} 与 claim 绑定 "
                f"self.email={self.email!r} 不一致，强制用 self.email 防串号"
            )
        timeout = max(int(timeout), 60)
        since_ts = (issued_after - 5) if issued_after else (time.time() - 5)
        deadline = time.time() + timeout
        logger.info(
            f"[oep] 取 OTP -> {self.email} (timeout={timeout}s "
            f"since_minutes={max(1, int((time.time() - since_ts) / 60) + 1)})"
        )
        while time.time() < deadline:
            try:
                code = self._fetch_code(since_ts)
                if code:
                    return code
            except OEPError as e:
                self.mark_dead(f"平台取码不可用 ({e.code}): {e.message}")
                raise TimeoutError(
                    f"oep mailbox unavailable for {self.email}: {e}"
                ) from e
            time.sleep(POLL_INTERVAL)
        raise TimeoutError(f"oep OTP timeout {timeout}s for {self.email}")

    @property
    def exhausted(self) -> bool:
        return self._dead

    def mark_dead(self, reason: str = "") -> None:
        logger.warning(f"[oep] mark dead: {self.email} reason={reason}")
        self._dead = True
        try:
            self._claim_complete("provider_blocked", reason[:200])
        except Exception as e:
            logger.warning(f"[oep] mark_dead 回传失败: {e}")

    def on_success(self, detail: str = "注册成功") -> None:
        try:
            self._claim_complete("success", detail)
        except Exception as e:
            logger.warning(f"[oep] on_success 失败: {e}")

    def on_release(self, reason: str = "放弃") -> None:
        try:
            self._claim_release(reason)
        except Exception as e:
            logger.warning(f"[oep] on_release 失败: {e}")

    def self_test(self) -> dict:
        try:
            health = _api(
                self.api_url, self.api_key, "GET",
                "/api/external/health", timeout=15,
            )
            stats = _api(
                self.api_url, self.api_key, "GET",
                "/api/external/pool/stats", timeout=15,
            )
            version = (health.get("data") or {}).get("version", "?")
            avail = (stats.get("data") or {}).get("pool_counts", {}).get("available", "?")
            return {
                "ok": True,
                "message": f"连接成功 (v{version})，池中可用邮箱: {avail}",
            }
        except MailProviderError:
            raise
        except Exception as e:
            return {"ok": False, "message": str(e)}
