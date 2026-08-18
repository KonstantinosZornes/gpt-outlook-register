"""HeroSMS 延迟取消队列：购买后 120s 内不可取消，入队等到点再 cancel。"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MIN_ACTIVATION_S = 120.0


@dataclass
class _Item:
    order_id: str
    api_key: str
    base_url: str
    provider: str
    reason: str
    enqueued_at: float
    proxies: Optional[dict] = None


def is_early_cancel_denied(http_status: int, body: str) -> bool:
    if http_status == 409:
        return True
    b = (body or "").upper()
    return "EARLY_CANCEL_DENIED" in b or "MINIMUM ACTIVATION" in b


def is_cancel_success(http_status: int, body: str) -> bool:
    """HeroSMS: 204 empty; SmsBower: 200 ACCESS_CANCEL."""
    if http_status == 204:
        return True
    if http_status != 200:
        return False
    upper = (body or "").upper()
    return "ACCESS_CANCEL" in upper or upper in ("OK", "1", "ACCESS_READY")


def cancel_order(
    *,
    api_key: str,
    base_url: str,
    order_id: str,
    proxies: Optional[dict] = None,
    timeout: float = 30.0,
) -> tuple[int, str]:
    """cancelActivation first, then setStatus=8."""
    def _get(params: dict) -> tuple[int, str]:
        resp = requests.get(
            base_url, params=params, timeout=timeout, proxies=proxies,
        )
        return resp.status_code, (resp.text or "")

    code, body = _get({
        "api_key": api_key, "action": "cancelActivation", "id": order_id,
    })
    if is_cancel_success(code, body) or is_early_cancel_denied(code, body):
        return code, body
    return _get({
        "api_key": api_key, "action": "setStatus", "id": order_id, "status": "8",
    })


class SmsCancelQueue:
    """FIFO：入队后等到 min_wait（默认 120s）再取消。"""

    def __init__(self, min_wait_s: float = MIN_ACTIVATION_S):
        self._min_wait_s = float(min_wait_s)
        self._q: list[_Item] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stopping = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._loop, name="sms-cancel-queue", daemon=True,
            )
            self._thread.start()
        logger.info("[sms_cancel_q] started min_wait=%.0fs", self._min_wait_s)

    def stop(self) -> None:
        self._stopping = True
        t = self._thread
        self._thread = None
        if t is not None:
            t.join(timeout=5)
        logger.info("[sms_cancel_q] stopped pending=%s", len(self._q))

    def enqueue(
        self,
        *,
        order_id: str,
        api_key: str,
        base_url: str,
        provider: str = "sms",
        reason: str = "",
        proxies: Optional[dict] = None,
    ) -> None:
        oid = (order_id or "").strip()
        key_api = (api_key or "").strip()
        base = (base_url or "").strip()
        if not oid or not key_api or not base:
            return
        now = time.time()
        with self._lock:
            if any(i.order_id == oid for i in self._q):
                return
            self._q.append(_Item(
                order_id=oid,
                api_key=key_api,
                base_url=base,
                provider=(provider or "sms").strip() or "sms",
                reason=(reason or "")[:200],
                enqueued_at=now,
                proxies=proxies,
            ))
        logger.info(
            "[sms_cancel_q] enqueued id=%s provider=%s reason=%s pending=%s",
            oid, provider, (reason or "")[:80], len(self._q),
        )
        if self._thread is None or not self._thread.is_alive():
            self.start()

    def pending_count(self) -> int:
        return len(self._q)

    def _loop(self) -> None:
        while not self._stopping:
            with self._lock:
                item = self._q.pop(0) if self._q else None
            if item is None:
                for _ in range(50):
                    if self._stopping or self._q:
                        break
                    time.sleep(0.1)
                continue

            remain = (item.enqueued_at + self._min_wait_s) - time.time()
            if remain > 0:
                logger.info(
                    "[sms_cancel_q] sleep %.1fs id=%s", remain, item.order_id,
                )
                deadline = time.time() + remain
                while time.time() < deadline and not self._stopping:
                    time.sleep(min(1.0, max(0.05, deadline - time.time())))
                if self._stopping:
                    with self._lock:
                        self._q.insert(0, item)
                    break

            try:
                code, body = cancel_order(
                    api_key=item.api_key,
                    base_url=item.base_url,
                    order_id=item.order_id,
                    proxies=item.proxies,
                )
            except Exception as e:
                logger.warning(
                    "[sms_cancel_q] cancel error id=%s: %s; requeue",
                    item.order_id, e,
                )
                with self._lock:
                    self._q.append(item)
                continue

            if is_cancel_success(code, body):
                logger.info(
                    "[sms_cancel_q] cancelled id=%s HTTP=%s body=%s",
                    item.order_id, code, (body or "")[:80],
                )
            elif is_early_cancel_denied(code, body):
                logger.warning(
                    "[sms_cancel_q] still early id=%s HTTP=%s; requeue",
                    item.order_id, code,
                )
                item.enqueued_at = time.time()
                with self._lock:
                    self._q.append(item)
            else:
                logger.warning(
                    "[sms_cancel_q] cancel failed id=%s HTTP=%s body=%s (drop)",
                    item.order_id, code, (body or "")[:160],
                )


_QUEUE: Optional[SmsCancelQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_sms_cancel_queue() -> SmsCancelQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = SmsCancelQueue()
        return _QUEUE
