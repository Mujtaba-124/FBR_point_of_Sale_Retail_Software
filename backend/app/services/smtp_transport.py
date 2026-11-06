"""SMTP transport with TLS enforcement and SSRF protection.

Security properties:

- TLS is mandatory. ``starttls`` mode refuses to continue (and never
  authenticates) if the server does not offer STARTTLS; ``ssl`` mode wraps the
  socket before the first byte. Certificates and hostnames are always verified
  (``ssl.create_default_context``), minimum TLS 1.2.
- SSRF: the hostname is resolved once, every resolved address must be a public
  (global unicast) address, and the connection goes to that vetted address
  while SNI and certificate verification use the configured hostname. Because
  the socket is pinned to the checked address there is no second DNS lookup,
  so DNS rebinding between check and connect is not possible.
- Only standard submission ports are allowed (see ``ALLOWED_PORTS``).
- No SMTP conversation is logged (``debuglevel`` stays 0) and server replies are
  never passed to clients; failures map to fixed, safe error codes.

``SmtpTransport`` is the seam tests replace with a fake; automated tests never
open real SMTP connections.
"""

import ipaddress
import logging
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

logger = logging.getLogger(__name__)

# 587 = submission (STARTTLS), 465 = submissions (implicit TLS),
# 25 / 2525 = relay ports some providers offer with STARTTLS.
ALLOWED_PORTS = frozenset({25, 465, 587, 2525})
# Fixed EHLO name: avoids leaking the container's internal hostname.
EHLO_NAME = "localhost"

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    mode: str  # "starttls" | "ssl"
    username: str | None
    password: str | None
    timeout: float
    allow_private_hosts: bool = False


class SmtpFailure(Exception):
    """A safe, client-presentable SMTP failure.

    ``transient`` is True when retrying later may succeed (network problems,
    timeouts, SMTP 4xx replies). Permanent failures (5xx rejections, TLS or
    authentication/configuration problems) must not be retried blindly.
    """

    def __init__(self, code: str, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient


_MODE_HINT = (
    "Check that the encryption mode matches the port (STARTTLS uses 587, SSL/TLS uses 465)."
)

FAILURE_MESSAGES: dict[str, str] = {
    "smtp_host_not_allowed": (
        "This SMTP host is not allowed. Use a public mail server such as smtp.gmail.com."
    ),
    "smtp_port_not_allowed": "This port is not allowed. Use 587 (STARTTLS) or 465 (SSL/TLS).",
    "smtp_host_not_found": "The SMTP host could not be found. Check the host name.",
    "smtp_timeout": "The SMTP server did not respond in time. " + _MODE_HINT,
    "smtp_connection_refused": "The SMTP server refused the connection. Check the host and port.",
    "smtp_connection_failed": "Could not connect to the SMTP server. Check the host and port.",
    "smtp_starttls_unsupported": (
        "The server does not offer STARTTLS, so the connection was not secured and no "
        "credentials were sent. " + _MODE_HINT
    ),
    "smtp_tls_certificate_invalid": (
        "The SMTP server's TLS certificate could not be verified for this host name."
    ),
    "smtp_tls_failed": "A secure TLS connection could not be established. " + _MODE_HINT,
    "smtp_auth_failed": (
        "The SMTP server rejected the username or password. For Gmail, use a 16-character "
        "App Password, not your normal Google password."
    ),
    "smtp_auth_unsupported": "The SMTP server does not accept authentication on this connection.",
    "smtp_sender_refused": "The SMTP server refused the sender email address.",
    "smtp_recipient_refused": "The SMTP server refused the recipient email address.",
    "smtp_message_rejected": "The SMTP server rejected the message.",
    "smtp_disconnected": "The SMTP server closed the connection unexpectedly.",
    "smtp_error": "The SMTP server returned an error.",
}


# Failures caused by the network or a temporarily unavailable server.
TRANSIENT_CODES = frozenset(
    {
        "smtp_host_not_found",
        "smtp_timeout",
        "smtp_connection_refused",
        "smtp_connection_failed",
        "smtp_disconnected",
        "smtp_error",
    }
)


def failure(code: str, transient: bool | None = None) -> SmtpFailure:
    if transient is None:
        transient = code in TRANSIENT_CODES
    return SmtpFailure(code, FAILURE_MESSAGES[code], transient)


def _is_4xx(code: object) -> bool:
    return isinstance(code, int) and 400 <= code < 500


# --- Host and address policy -------------------------------------------------


def normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def host_syntax_problem(host: str) -> str | None:
    """Static checks done at save time. Returns a message, or None when acceptable."""
    if not host:
        return "Enter the SMTP host."
    if len(host) > 253:
        return "The SMTP host is too long."
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        return None if _is_public(ip) else FAILURE_MESSAGES["smtp_host_not_allowed"]
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return "The SMTP host is not a valid host name."
    labels = ascii_host.split(".")
    if len(labels) < 2 or not all(_LABEL_RE.match(label) for label in labels):
        return "The SMTP host is not a valid host name (for example smtp.gmail.com)."
    if labels[-1].isdigit():
        return "The SMTP host is not a valid host name."
    if ascii_host == "localhost" or ascii_host.endswith(_BLOCKED_SUFFIXES):
        return FAILURE_MESSAGES["smtp_host_not_allowed"]
    return None


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return _is_public(mapped)
        if ip.teredo is not None:
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def resolve_vetted_address(host: str, port: int, allow_private: bool = False) -> str:
    """Resolve ``host`` and return one address that passes the SSRF policy.

    Every resolved address must be public: if a name resolves to both public
    and internal addresses it is rejected outright rather than filtered.
    """
    try:
        infos = socket.getaddrinfo(host.strip("[]"), port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise failure("smtp_host_not_found") from None
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        address = str(sockaddr[0]).split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise failure("smtp_host_not_found")
    if not allow_private:
        for address in addresses:
            if not _is_public(ipaddress.ip_address(address)):
                logger.warning("smtp host rejected: resolves to a non-public address")
                raise failure("smtp_host_not_allowed")
    # Prefer IPv4: container networks often lack IPv6 egress.
    addresses.sort(key=lambda a: ":" in a)
    return addresses[0]


# --- smtplib clients pinned to the vetted address ----------------------------


class _PinnedSMTP(smtplib.SMTP):
    def __init__(self, hostname: str, address: str, timeout: float) -> None:
        super().__init__(local_hostname=EHLO_NAME, timeout=timeout)
        self._host = hostname  # used for STARTTLS SNI + certificate checks
        self._pinned_address = address

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return socket.create_connection((self._pinned_address, port), timeout)


class _PinnedSMTPSSL(smtplib.SMTP_SSL):
    def __init__(
        self, hostname: str, address: str, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(local_hostname=EHLO_NAME, timeout=timeout, context=context)
        self._host = hostname
        self._pinned_address = address

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        raw = socket.create_connection((self._pinned_address, port), timeout)
        try:
            return self.context.wrap_socket(raw, server_hostname=self._host)
        except BaseException:
            raw.close()
            raise


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # create_default_context already sets these; asserted so they can't regress.
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    return context


def _map_exception(exc: BaseException) -> SmtpFailure:
    if isinstance(exc, SmtpFailure):
        return exc
    # SMTP 4xx replies are temporary by definition (RFC 5321); 5xx are permanent.
    smtp_code = getattr(exc, "smtp_code", None)
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return failure("smtp_auth_failed", _is_4xx(smtp_code))
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return failure("smtp_auth_unsupported")
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return failure("smtp_sender_refused", _is_4xx(smtp_code))
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [reply[0] for reply in exc.recipients.values()]
        return failure("smtp_recipient_refused", bool(codes) and all(map(_is_4xx, codes)))
    if isinstance(exc, smtplib.SMTPDataError):
        return failure("smtp_message_rejected", _is_4xx(smtp_code))
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return failure("smtp_disconnected")
    if isinstance(exc, smtplib.SMTPConnectError):
        return failure("smtp_connection_failed")
    if isinstance(exc, smtplib.SMTPException):
        return failure("smtp_error")
    if isinstance(exc, ssl.SSLCertVerificationError):
        return failure("smtp_tls_certificate_invalid")
    if isinstance(exc, ssl.SSLError):
        return failure("smtp_tls_failed")
    if isinstance(exc, TimeoutError | socket.timeout):
        return failure("smtp_timeout")
    if isinstance(exc, ConnectionRefusedError):
        return failure("smtp_connection_refused")
    if isinstance(exc, socket.gaierror):
        return failure("smtp_host_not_found")
    return failure("smtp_connection_failed")


class SmtpTransport(Protocol):
    def check_connection(self, config: SmtpConfig) -> None:
        """Connect, secure, authenticate and quit. Sends no message."""

    def send(self, config: SmtpConfig, message: EmailMessage) -> None:
        """Deliver ``message`` to the server. Raises ``SmtpFailure``."""


class SmtplibTransport:
    """Production transport built on smtplib."""

    def _open(self, config: SmtpConfig) -> smtplib.SMTP:
        if config.port not in ALLOWED_PORTS:
            raise failure("smtp_port_not_allowed")
        problem = host_syntax_problem(config.host)
        if problem and not config.allow_private_hosts:
            raise failure("smtp_host_not_allowed")
        address = resolve_vetted_address(config.host, config.port, config.allow_private_hosts)
        context = tls_context()
        client: smtplib.SMTP
        if config.mode == "ssl":
            client = _PinnedSMTPSSL(config.host, address, config.timeout, context)
        else:
            client = _PinnedSMTP(config.host, address, config.timeout)
        try:
            client.connect(config.host, config.port)
            client.ehlo()
            if config.mode != "ssl":
                if not client.has_extn("starttls"):
                    raise failure("smtp_starttls_unsupported")
                client.starttls(context=context)
                client.ehlo()
            if config.username:
                client.login(config.username, config.password or "")
        except BaseException:
            _close(client)
            raise
        return client

    def check_connection(self, config: SmtpConfig) -> None:
        try:
            client = self._open(config)
            _quit(client)
        except Exception as exc:
            raise _map_exception(exc) from None

    def send(self, config: SmtpConfig, message: EmailMessage) -> None:
        try:
            client = self._open(config)
            try:
                refused = client.send_message(message)
            finally:
                _quit(client)
        except Exception as exc:
            raise _map_exception(exc) from None
        if refused:
            raise failure("smtp_recipient_refused")


def _quit(client: smtplib.SMTP) -> None:
    try:
        client.quit()
    except (smtplib.SMTPException, OSError):
        _close(client)


def _close(client: smtplib.SMTP) -> None:
    try:
        client.close()
    except OSError:
        pass


SINK_FAULTS_KEY = "e2e:smtp:faults"
CRASH_EXIT_CODE = 70


class SinkTransport:
    """Development/QA only: writes messages to files instead of sending them.

    Selected with ``EMAIL_TRANSPORT=sink``; the settings validator refuses it in
    production. Lets the Celery worker/Beat pipeline be exercised end to end
    without any real SMTP traffic.

    In ``E2E_TEST_MODE`` each send first pops one instruction from the Redis
    list ``SINK_FAULTS_KEY``: an SMTP failure code (raised as that failure),
    ``crash_before_accept`` (the worker process exits before the message is
    written) or ``crash_after_accept`` (exits right after it is written, i.e.
    accepted but not yet recorded).
    """

    def __init__(self, directory: str, fault_injection: bool = False) -> None:
        self.directory = directory
        self.fault_injection = fault_injection

    def check_connection(self, config: SmtpConfig) -> None:
        return None

    def _next_fault(self) -> str | None:
        if not self.fault_injection:
            return None
        from app.core.redis import get_redis

        raw = get_redis().lpop(SINK_FAULTS_KEY)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    def send(self, config: SmtpConfig, message: EmailMessage) -> None:
        import os
        import uuid

        fault = self._next_fault()
        if fault == "crash_before_accept":
            os._exit(CRASH_EXIT_CODE)
        if fault and fault != "crash_after_accept":
            raise failure(fault)
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, f"{uuid.uuid4().hex}.eml")
        with open(path, "wb") as fh:
            fh.write(bytes(message))
            fh.flush()
            os.fsync(fh.fileno())
        if fault == "crash_after_accept":
            os._exit(CRASH_EXIT_CODE)


_default_transport = SmtplibTransport()


def get_smtp_transport() -> SmtpTransport:
    """The transport for this process (FastAPI dependency; tests override it)."""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.email_transport == "sink":
        return SinkTransport(settings.email_sink_dir, settings.e2e_test_mode)
    return _default_transport
