
from __future__ import annotations

import asyncio
import ipaddress
import smtplib
import socket
import ssl
from email.message import EmailMessage
from typing import Any, Callable, Optional

import structlog

from src.core.notifications.kind_specs import MAX_EMAIL_RECIPIENTS
from src.core.notifications.http import (
    GuardNetworkError,
    Resolver,
    _system_resolver,
    address_verdict,
    normalize_host,
    GuardBlocked,
)

log = structlog.get_logger(__name__)

MAX_RECIPIENTS = MAX_EMAIL_RECIPIENTS
DEFAULT_PORTS = {"starttls": 587, "tls": 465, "plain": 25}
SECURITY_MODES = tuple(DEFAULT_PORTS)
_LOCAL_HELO = "localhost"


class MailError(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MailBlocked(MailError):
    pass


class MailTimeout(MailError):
    pass


class MailNetworkError(MailError):
    pass


class MailAuthError(MailError):
    pass


class MailRejected(MailError):
    pass


class MailTempFailure(MailError):
    pass


class _PinnedSMTP(smtplib.SMTP):

    def __init__(self, host: str, port: int, *, pinned_ip: str, **kw: Any) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, port, **kw)

    def _get_socket(self, host, port, timeout):
        return socket.create_connection((self._pinned_ip, port), timeout, self.source_address)


class _PinnedSMTPSSL(smtplib.SMTP_SSL):

    def __init__(self, host: str, port: int, *, pinned_ip: str, **kw: Any) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, port, **kw)

    def _get_socket(self, host, port, timeout):
        raw = socket.create_connection((self._pinned_ip, port), timeout, self.source_address)
        return self.context.wrap_socket(raw, server_hostname=self._host)


def _default_factory(
    security: str, host: str, port: int, pinned_ip: str, timeout: float, context: ssl.SSLContext
) -> smtplib.SMTP:
    if security == "tls":
        return _PinnedSMTPSSL(host, port, pinned_ip=pinned_ip, timeout=timeout,
                              local_hostname=_LOCAL_HELO, context=context)
    return _PinnedSMTP(host, port, pinned_ip=pinned_ip, timeout=timeout, local_hostname=_LOCAL_HELO)


def _is_loopback(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _clean(value: str) -> bool:
    return bool(value) and not any(c in value for c in "\r\n\0")


def _check_inputs(security: str, sender: str, recipients: list[str], subject: str) -> None:
    if security not in SECURITY_MODES:
        raise MailBlocked("security")
    if not recipients or len(recipients) > MAX_RECIPIENTS:
        raise MailBlocked("recipients")
    if not _clean(sender) or not all(_clean(r) for r in recipients):
        raise MailBlocked("address_format")
    if "\r" in subject or "\n" in subject or "\0" in subject:
        raise MailBlocked("subject")


async def _vet_host(host: str, port: int, security: str, resolver: Optional[Resolver], timeout: float) -> str:
    try:
        name = normalize_host(host)
    except GuardBlocked as exc:
        raise MailBlocked("host") from exc
    try:
        literal: Optional[Any] = ipaddress.ip_address(name)
    except ValueError:
        literal = None
    if literal is not None:
        addrs = [str(literal)]
    else:
        try:
            async with asyncio.timeout(timeout):
                addrs = await (resolver or _system_resolver)(name, port)
        except TimeoutError as exc:
            raise MailTimeout("timeout") from exc
        except GuardNetworkError as exc:
            raise MailNetworkError("dns") from exc
    if not addrs:
        raise MailNetworkError("dns")
    parsed = []
    for a in addrs:
        try:
            parsed.append(ipaddress.ip_address(a))
        except ValueError as exc:
            raise MailBlocked("address") from exc
    for ip in parsed:
        if not (_is_loopback(ip) or address_verdict(ip, allow_private=False)):
            raise MailBlocked("address")
    if security == "plain" and not all(_is_loopback(ip) for ip in parsed):
        raise MailBlocked("plain_not_loopback")
    return str(parsed[0])


def _classify_response(code: int) -> MailError:
    if 400 <= code < 500:
        return MailTempFailure("temp_failure")
    return MailRejected("rejected")


def _deliver(
    factory: Callable[..., smtplib.SMTP], security: str, host: str, port: int, pinned_ip: str,
    timeout: float, context: ssl.SSLContext, username: Optional[str], password: Optional[str],
    msg: EmailMessage, sender: str, recipients: list[str],
) -> None:
    client = factory(security, host, port, pinned_ip, timeout, context)
    try:
        client.ehlo()
        if security == "starttls":
            client.starttls(context=context)
            client.ehlo()
        if username:
            client.login(username, password or "")
        client.send_message(msg, from_addr=sender, to_addrs=recipients)
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            client.close()


async def send_mail(
    *, host: str, port: Optional[int] = None, security: str = "starttls",
    username: Optional[str] = None, password: Optional[str] = None,
    sender: str, recipients: list[str], subject: str, body: str, dest_id: str,
    timeout: float = 15.0, resolver: Optional[Resolver] = None,
    smtp_factory: Optional[Callable[..., smtplib.SMTP]] = None,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> None:
    port = port or DEFAULT_PORTS.get(security, 587)
    try:
        _check_inputs(security, sender, recipients, subject)
        pinned_ip = await _vet_host(host, port, security, resolver, timeout)
    except MailBlocked as exc:
        log.warning("smtp.blocked", dest_id=dest_id, host=host, port=port, security=security, reason=exc.reason)
        raise
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, ", ".join(recipients), subject
    msg.set_content(body)
    context = ssl_context or ssl.create_default_context()
    try:
        await asyncio.to_thread(
            _deliver, smtp_factory or _default_factory, security, normalize_host(host), port,
            pinned_ip, timeout, context, username, password, msg, sender, list(recipients),
        )
    except smtplib.SMTPAuthenticationError as exc:
        err: MailError = MailAuthError("auth")
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [c for c, _ in exc.recipients.values()]
        err = _classify_response(min(codes) if codes and all(400 <= c < 500 for c in codes) else 550)
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    except smtplib.SMTPResponseException as exc:
        err = _classify_response(exc.smtp_code)
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    except (smtplib.SMTPException, ssl.SSLError) as exc:
        err = MailNetworkError(type(exc).__name__.lower())
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    except TimeoutError as exc:
        err = MailTimeout("timeout")
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    except OSError as exc:
        err = MailNetworkError(type(exc).__name__.lower())
        _fail(err, dest_id, host, port, security, len(recipients))
        raise err from exc
    log.info("smtp.sent", dest_id=dest_id, host=host, port=port, security=security,
             recipient_count=len(recipients))


def _fail(err: MailError, dest_id: str, host: str, port: int, security: str, count: int) -> None:
    log.warning("smtp.failed", dest_id=dest_id, host=host, port=port, security=security,
                recipient_count=count, reason=err.reason, kind=type(err).__name__)
