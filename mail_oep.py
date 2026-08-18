"""OutlookEmailPlus 平台接码 —— 转发壳。

实现已迁至 mail_providers/oep.py（继承统一的 MailProvider 基类）。
本文件仅保留原有的公开名字，让旧 import 路径继续可用。

新代码请直接用：

    from mail_providers import create_mail_provider
    mail = create_mail_provider("oep", settings)
"""
from __future__ import annotations

from mail_providers.oep import (  # noqa: F401
    DEFAULT_PROVIDER,
    OEPError,
    OutlookEmailPlusProvider,
    POLL_INTERVAL,
)

__all__ = ["OutlookEmailPlusProvider", "OEPError"]


if __name__ == "__main__":
    import logging
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if len(sys.argv) < 3:
        print("usage: python mail_oep.py <api_url> <api_key>")
        sys.exit(2)
    p = OutlookEmailPlusProvider(sys.argv[1], sys.argv[2])
    try:
        em = p.create_mailbox()
        print(f"claimed: {em}  (account_id={p._account_id})")
        print("等待 60s 看 OpenAI 来信（不会真有，仅验证连通）...")
        otp = p.wait_for_otp(em, timeout=60)
        print(f"OTP: {otp}")
    except Exception as ex:
        print(f"ERR: {ex}")
    finally:
        p.on_release("debug test")
