"""SMTP transport: SSRF policy, address pinning, TLS enforcement, error mapping.

DNS is monkeypatched and the only server used is an in-process fake SMTP
server on 127.0.0.1 (reachable only because those tests opt in to
``allow_private_hosts``). No real mail server is contacted.
"""

import smtplib
import socket
import socketserver
import ssl
import threading
from collections.abc import Iterator

import pytest

from app.services import smtp_transport as st
from app.services.smtp_transport import SmtpConfig, SmtpFailure, SmtplibTransport


def _addrinfo(*addresses: str):
    def fake(host, port, *args, **kwargs):
        out = []
        for a in addresses:
            family = socket.AF_INET6 if ":" in a else socket.AF_INET
            sockaddr = (a, port, 0, 0) if family == socket.AF_INET6 else (a, port)
            out.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    return fake


# --- Static host policy ------------------------------------------------------


@pytest.mark.parametrize("host", ["smtp.gmail.com", "smtp.office365.com", "8.8.8.8", "mail.co.uk"])
def test_public_hosts_pass_syntax(host: str) -> None:
    assert st.host_syntax_problem(host) is None


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "foo.localhost",
        "127.0.0.1",
        "10.1.2.3",
        "100.64.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "2002:0a00:0001::1",  # 6to4 wrapping 10.0.0.1
        "224.0.0.1",
        "printer.local",
        "db.internal",
        "singlelabel",
        "a..b.com",
        "x" * 254,
    ],
)
def test_unsafe_hosts_fail_syntax(host: str) -> None:
    assert st.host_syntax_problem(host) is not None


# --- Resolution policy -------------------------------------------------------


def test_public_resolution_is_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo("2607:f8b0::1", "142.250.1.1"))
    assert st.resolve_vetted_address("smtp.example.com", 587) == "142.250.1.1"


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.7",),
        ("172.18.0.3",),  # Docker network
        ("169.254.169.254",),  # cloud metadata
        ("::1",),
        ("::ffff:192.168.0.1",),
        ("142.250.1.1", "10.0.0.7"),  # mixed: one internal answer rejects all
    ],
)
def test_internal_resolution_is_rejected(
    monkeypatch: pytest.MonkeyPatch, addresses: tuple[str, ...]
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo(*addresses))
    with pytest.raises(SmtpFailure) as err:
        st.resolve_vetted_address("rebind.example.com", 587)
    assert err.value.code == "smtp_host_not_allowed"


def test_private_resolution_allowed_only_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo("10.0.0.7"))
    assert st.resolve_vetted_address("relay.example.com", 587, allow_private=True) == "10.0.0.7"


def test_unknown_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(SmtpFailure) as err:
        st.resolve_vetted_address("missing.example.com", 587)
    assert err.value.code == "smtp_host_not_found"


def _config(**overrides: object) -> SmtpConfig:
    values: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "mode": "starttls",
        "username": "user@example.com",
        "password": "pw",
        "timeout": 2.0,
        "allow_private_hosts": False,
    }
    values.update(overrides)
    return SmtpConfig(**values)  # type: ignore[arg-type]


def test_connection_goes_to_vetted_address_without_second_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS rebinding: resolve once, connect to that address, never re-resolve."""
    lookups: list[str] = []
    connects: list[tuple[str, int]] = []

    def getaddrinfo(host, port, *args, **kwargs):
        lookups.append(host)
        return _addrinfo("142.250.1.1")(host, port)

    def create_connection(address, timeout=None, *args, **kwargs):
        connects.append(address)
        raise ConnectionRefusedError()

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_config())
    assert err.value.code == "smtp_connection_refused"
    assert lookups == ["smtp.example.com"]
    assert connects == [("142.250.1.1", 587)]


def test_blocked_port_never_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(*args, **kwargs):
        raise AssertionError("must not resolve")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_config(port=6379))
    assert err.value.code == "smtp_port_not_allowed"


def test_blocked_host_never_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(*args, **kwargs):
        raise AssertionError("must not resolve")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_config(host="169.254.169.254"))
    assert err.value.code == "smtp_host_not_allowed"


# --- TLS ---------------------------------------------------------------------


def test_tls_context_verifies_certificates_and_hostnames() -> None:
    context = st.tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_pinned_clients_verify_against_hostname() -> None:
    plain = st._PinnedSMTP("smtp.gmail.com", "142.250.1.1", 1.0)
    secure = st._PinnedSMTPSSL("smtp.gmail.com", "142.250.1.1", 1.0, st.tls_context())
    # smtplib passes _host as server_hostname for SNI + certificate checks.
    assert plain._host == "smtp.gmail.com" and secure._host == "smtp.gmail.com"
    assert plain.debuglevel == 0 and secure.debuglevel == 0
    assert plain.local_hostname == st.EHLO_NAME


# --- Fake SMTP server ---------------------------------------------------------


class FakeSmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.commands: list[str] = []
        super().__init__(("127.0.0.1", 0), FakeSmtpHandler)


class FakeSmtpHandler(socketserver.StreamRequestHandler):
    server: FakeSmtpServer

    def reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())

    def handle(self) -> None:
        behaviour = self.server.behaviour
        if behaviour == "silent":
            self.rfile.readline()  # never greets; client must time out
            return
        self.reply("220 fake.test ESMTP")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").strip()
            self.server.commands.append(line.split(" ", 1)[0].upper())
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                if behaviour == "starttls_garbage":
                    self.reply("250-fake.test")
                    self.reply("250-STARTTLS")
                    self.reply("250 AUTH PLAIN LOGIN")
                else:
                    self.reply("250-fake.test")
                    self.reply("250 AUTH PLAIN LOGIN")
            elif verb == "STARTTLS":
                self.reply("220 go ahead")
                self.wfile.write(b"this is not a TLS handshake\r\n")
                return
            elif verb == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("502 not implemented")


@pytest.fixture
def fake_server(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    server = FakeSmtpServer(request.param)
    port = server.server_address[1]
    monkeypatch.setattr(st, "ALLOWED_PORTS", frozenset({port}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, port
    server.shutdown()
    server.server_close()


def _local(port: int, **overrides: object) -> SmtpConfig:
    values: dict[str, object] = {"timeout": 1.0, **overrides}
    return _config(host="127.0.0.1", port=port, allow_private_hosts=True, **values)


@pytest.mark.parametrize("fake_server", ["no_starttls"], indirect=True)
def test_missing_starttls_stops_before_credentials(fake_server) -> None:
    server, port = fake_server
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_local(port))
    assert err.value.code == "smtp_starttls_unsupported"
    assert "AUTH" not in server.commands  # no plaintext login


@pytest.mark.parametrize("fake_server", ["starttls_garbage"], indirect=True)
def test_failed_tls_handshake_stops_before_credentials(fake_server) -> None:
    server, port = fake_server
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_local(port))
    assert err.value.code in ("smtp_tls_failed", "smtp_disconnected", "smtp_connection_failed")
    assert "STARTTLS" in server.commands and "AUTH" not in server.commands


@pytest.mark.parametrize("fake_server", ["no_starttls"], indirect=True)
def test_ssl_mode_against_plain_server_fails(fake_server) -> None:
    server, port = fake_server
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_local(port, mode="ssl"))
    assert err.value.code in ("smtp_tls_failed", "smtp_disconnected", "smtp_connection_failed")
    assert "AUTH" not in server.commands


@pytest.mark.parametrize("fake_server", ["silent"], indirect=True)
def test_unresponsive_server_times_out(fake_server) -> None:
    _, port = fake_server
    with pytest.raises(SmtpFailure) as err:
        SmtplibTransport().check_connection(_local(port, timeout=0.3))
    assert err.value.code in ("smtp_timeout", "smtp_disconnected")


# --- Error mapping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"), "smtp_auth_failed"),
        (smtplib.SMTPNotSupportedError(), "smtp_auth_unsupported"),
        (smtplib.SMTPSenderRefused(553, b"no", "a@b.c"), "smtp_sender_refused"),
        (smtplib.SMTPRecipientsRefused({"a@b.c": (550, b"no")}), "smtp_recipient_refused"),
        (smtplib.SMTPDataError(554, b"spam"), "smtp_message_rejected"),
        (smtplib.SMTPServerDisconnected(), "smtp_disconnected"),
        (ssl.SSLCertVerificationError("bad cert"), "smtp_tls_certificate_invalid"),
        (ssl.SSLError("wrong version"), "smtp_tls_failed"),
        (TimeoutError(), "smtp_timeout"),
        (ConnectionRefusedError(), "smtp_connection_refused"),
        (OSError("unreachable"), "smtp_connection_failed"),
    ],
)
def test_exception_mapping_is_safe(exc: BaseException, code: str) -> None:
    mapped = st._map_exception(exc)
    assert mapped.code == code
    assert mapped.message == st.FAILURE_MESSAGES[code]
    assert "bad credentials" not in mapped.message  # server text never surfaces


# --- Transient vs permanent (retry policy) -----------------------------------


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (smtplib.SMTPAuthenticationError(535, b"bad"), False),
        (smtplib.SMTPAuthenticationError(454, b"try later"), True),
        (smtplib.SMTPSenderRefused(550, b"no", "a@b.c"), False),
        (smtplib.SMTPSenderRefused(451, b"later", "a@b.c"), True),
        (smtplib.SMTPRecipientsRefused({"a@b.c": (550, b"no such user")}), False),
        (smtplib.SMTPRecipientsRefused({"a@b.c": (450, b"greylisted")}), True),
        (smtplib.SMTPDataError(554, b"rejected"), False),
        (smtplib.SMTPDataError(421, b"busy"), True),
        (smtplib.SMTPServerDisconnected(), True),
        (TimeoutError(), True),
        (ConnectionRefusedError(), True),
        (OSError("unreachable"), True),
        (ssl.SSLCertVerificationError("bad cert"), False),
        (ssl.SSLError("wrong version"), False),
    ],
)
def test_transient_classification(exc: BaseException, transient: bool) -> None:
    assert st._map_exception(exc).transient is transient


def test_policy_failures_are_permanent() -> None:
    for code in ("smtp_host_not_allowed", "smtp_port_not_allowed", "smtp_starttls_unsupported"):
        assert st.failure(code).transient is False


def test_sink_transport_is_refused_in_production() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(
            database_url="postgresql+psycopg://x/y",
            environment="production",
            cookie_secure=True,
            email_transport="sink",
        )
