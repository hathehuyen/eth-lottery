#!/usr/bin/env python3
"""Scan randomly generated Ethereum keys for on-chain activity.

The tool derives an address from a random 32-byte private key and asks an
Ethereum node for that address' balance and nonce. Matches are appended to a
private "jackpot" file.

This is a research/educational tool: the probability of finding a funded
account is effectively zero. See README.md before running it.

Usage:
    python eth_lottery.py                     # IPC provider
    python eth_lottery.py --http http://...   # HTTP provider
    python eth_lottery.py --max-checks 1000   # bounded run
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, Protocol, TextIO

import config

__version__ = "2.0.0"

LOG = logging.getLogger("eth_lottery")

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class LotteryError(RuntimeError):
    """Fatal runtime problem: bad configuration, connectivity or output file."""


class EthApi(Protocol):
    """Subset of ``web3.eth`` used by the scanner."""

    def get_balance(self, account: str, block_identifier: Any = ...) -> int:
        ...

    def get_transaction_count(
        self, account: str, block_identifier: Any = ...
    ) -> int:
        ...

    @property
    def chain_id(self) -> int:
        ...

    @property
    def block_number(self) -> int:
        ...


class ChainClient(Protocol):
    """Subset of ``web3.Web3`` used by the scanner."""

    eth: EthApi

    def is_connected(self) -> bool:
        ...


KeyFactory = Callable[[], "tuple[bytes, str]"]
AddressDeriver = Callable[[bytes], str]
ResultHandler = Callable[["CheckResult"], None]
ClientFactory = Callable[[], ChainClient]


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings built from ``config.py``, environment and CLI flags."""

    ipc_path: str = config.IPC_PATH
    http_url: str | None = config.HTTP_URL
    write_log: bool = config.WRITE_LOG
    log_file: Path = Path(config.LOG_FILE)
    jackpot_file: Path = Path(config.JACKPOT_FILE)
    delay: float = config.DELAY
    report_every: int = config.REPORT_EVERY
    max_checks: int | None = config.MAX_CHECKS or None
    timeout: float = config.TIMEOUT
    reconnect_delay: float = config.RECONNECT_DELAY
    connect_retries: int = config.CONNECT_RETRIES

    def __post_init__(self) -> None:
        if self.delay < 0:
            raise LotteryError("delay must be greater than or equal to 0")
        if self.report_every < 0:
            raise LotteryError("report_every must be greater than or equal to 0")
        if self.max_checks is not None and self.max_checks <= 0:
            raise LotteryError("max_checks must be greater than 0 (0 = unlimited)")
        if self.timeout <= 0:
            raise LotteryError("timeout must be greater than 0")
        if self.reconnect_delay < 0:
            raise LotteryError("reconnect_delay must be greater than or equal to 0")
        if self.connect_retries < 0:
            raise LotteryError("connect_retries must be greater than or equal to 0")
        if not self.http_url and not str(self.ipc_path).strip():
            raise LotteryError("either an IPC path or an HTTP URL is required")

        object.__setattr__(self, "ipc_path", str(Path(self.ipc_path).expanduser()))
        object.__setattr__(self, "log_file", Path(self.log_file).expanduser())
        object.__setattr__(
            self, "jackpot_file", Path(self.jackpot_file).expanduser()
        )


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One checked key."""

    checked_at: str
    private_key_hex: str
    address: str
    balance: int
    nonce: int

    @property
    def is_win(self) -> bool:
        """A hit means the address has funds or has sent transactions."""
        return self.balance != 0 or self.nonce != 0

    def to_line(self) -> str:
        """Tab-free, space-separated record written to logs."""
        return " ".join(
            (
                self.checked_at,
                self.private_key_hex,
                self.address,
                str(self.balance),
                str(self.nonce),
            )
        )


@dataclass(slots=True)
class ScanStats:
    """Counters for a scan run."""

    attempts: int = 0
    wins: int = 0
    errors: int = 0
    reconnects: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return max(time.monotonic() - self.started_at, 0.0)

    def rate(self) -> float:
        elapsed = self.elapsed()
        return self.attempts / elapsed if elapsed else 0.0


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_private_key() -> tuple[bytes, str]:
    """Return a cryptographically secure 32-byte key and its hex form."""
    key = secrets.token_bytes(32)
    return key, key.hex()


def derive_address(private_key: bytes) -> str:
    """Derive a checksummed Ethereum address from a private key.

    ``eth_account`` is imported lazily so the pure helpers in this module stay
    usable (and testable) without the web3 stack installed.
    """
    from eth_account import Account

    return Account.from_key(private_key).address


def read_account(client: ChainClient, address: str) -> tuple[int, int]:
    """Return ``(balance_in_wei, transaction_count)`` for ``address``."""
    balance = int(client.eth.get_balance(address))
    nonce = int(client.eth.get_transaction_count(address))
    return balance, nonce


def _ensure_parent(path: Path) -> None:
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def append_private_line(path: Path, line: str) -> None:
    """Append a line to a file that may contain secrets, mode ``0600``."""
    _ensure_parent(path)
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except OSError as exc:
        raise LotteryError(f"cannot write to {path}: {exc}") from exc


def warn_if_permissive(path: Path) -> None:
    """Warn when an existing jackpot file is readable by other users."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        LOG.warning(
            "%s contains private keys and is readable by other users; "
            "run: chmod 600 %s",
            path,
            path,
        )


def _open_log(settings: Settings) -> TextIO | None:
    if not settings.write_log:
        return None
    _ensure_parent(settings.log_file)
    try:
        return settings.log_file.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        raise LotteryError(
            f"cannot open log file {settings.log_file}: {exc}"
        ) from exc


def build_client(settings: Settings) -> ChainClient:
    """Create a synchronous web3 client for the configured provider."""
    try:
        from web3 import Web3
        from web3.providers.ipc import IPCProvider
        from web3.providers.rpc import HTTPProvider
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LotteryError(
            "web3.py is not installed; run: pip install -e ."
        ) from exc

    if settings.http_url:
        LOG.info("Using HTTP provider: %s", settings.http_url)
        provider = HTTPProvider(
            settings.http_url,
            request_kwargs={"timeout": settings.timeout},
        )
    else:
        LOG.info("Using IPC provider: %s", settings.ipc_path)
        provider = IPCProvider(
            ipc_path=Path(settings.ipc_path),
            timeout=max(1, int(settings.timeout)),
        )
    return Web3(provider)


def connect(
    client_factory: ClientFactory,
    settings: Settings,
    stop: threading.Event | None = None,
) -> ChainClient | None:
    """Build a client and wait until the node answers.

    Returns ``None`` when ``stop`` is set or all attempts are exhausted.
    ``connect_retries == 0`` means retry forever.
    """
    attempt = 0
    while stop is None or not stop.is_set():
        attempt += 1
        try:
            client = client_factory()
            if client.is_connected():
                LOG.info("Connected to Ethereum node.")
                return client
            LOG.warning("Node did not answer (attempt %d).", attempt)
        except LotteryError:
            raise
        except Exception as exc:  # noqa: BLE001 - report any provider failure
            LOG.warning("Connection failed (attempt %d): %s", attempt, exc)

        if settings.connect_retries and attempt >= settings.connect_retries:
            LOG.error("Giving up after %d connection attempt(s).", attempt)
            return None

        LOG.info("Retrying in %.1f seconds ...", settings.reconnect_delay)
        if stop is not None:
            if stop.wait(settings.reconnect_delay):
                return None
        else:
            time.sleep(settings.reconnect_delay)
    return None


def _reconnect(
    client_factory: ClientFactory,
    settings: Settings,
    stop: threading.Event,
) -> ChainClient | None:
    if stop.wait(settings.reconnect_delay):
        return None
    LOG.info("Reconnecting to the Ethereum node ...")
    return connect(client_factory, settings, stop)


def scan(
    client: ChainClient,
    settings: Settings,
    *,
    stop: threading.Event | None = None,
    max_checks: int | None = None,
    client_factory: ClientFactory | None = None,
    derive: AddressDeriver = derive_address,
    new_key: KeyFactory = new_private_key,
    on_result: ResultHandler | None = None,
) -> ScanStats:
    """Run the key scan until the limit or ``stop`` is reached.

    ``client_factory`` enables automatic reconnection after RPC failures. The
    ``derive``/``new_key``/``on_result`` hooks keep the loop testable without
    a live node.
    """
    stop = stop if stop is not None else threading.Event()
    limit = settings.max_checks if max_checks is None else max_checks
    if limit is not None and limit <= 0:
        limit = None

    stats = ScanStats()
    log_handle = _open_log(settings)
    try:
        while not stop.is_set() and (limit is None or stats.attempts < limit):
            key_bytes, key_hex = new_key()
            try:
                address = derive(key_bytes)
            except Exception as exc:  # noqa: BLE001 - invalid curve scalar
                stats.errors += 1
                LOG.debug("Discarding invalid private key: %s", exc)
                continue

            try:
                balance, nonce = read_account(client, address)
            except Exception as exc:  # noqa: BLE001 - any RPC failure
                stats.errors += 1
                LOG.warning("RPC request failed for %s: %s", address, exc)
                if client_factory is None:
                    raise LotteryError(f"RPC request failed: {exc}") from exc
                replacement = _reconnect(client_factory, settings, stop)
                if replacement is None:
                    if stop.is_set():
                        break
                    raise LotteryError(
                        "Could not reconnect to the Ethereum node."
                    ) from exc
                client = replacement
                stats.reconnects += 1
                continue

            stats.attempts += 1
            result = CheckResult(
                checked_at=utc_timestamp(),
                private_key_hex=key_hex,
                address=address,
                balance=balance,
                nonce=nonce,
            )

            if log_handle is not None:
                log_handle.write(result.to_line() + "\n")

            if result.is_win:
                stats.wins += 1
                append_private_line(settings.jackpot_file, result.to_line())
                LOG.warning(
                    "Match: address=%s balance=%d wei nonce=%d (saved to %s)",
                    result.address,
                    result.balance,
                    result.nonce,
                    settings.jackpot_file,
                )

            if on_result is not None:
                on_result(result)

            if settings.report_every and stats.attempts % settings.report_every == 0:
                LOG.info(
                    "%d keys checked (%.2f keys/s, %d match(es), %d error(s)).",
                    stats.attempts,
                    stats.rate(),
                    stats.wins,
                    stats.errors,
                )

            if settings.delay:
                stop.wait(settings.delay)
    finally:
        if log_handle is not None:
            log_handle.close()

    return stats


def _env_str(name: str, default: str | None) -> str | None:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean (1/0, true/false), got {raw!r}")


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected an integer, got {value!r}"
        ) from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number


def _non_negative_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a number, got {value!r}"
        ) from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return number


def _positive_float(value: str) -> float:
    number = _non_negative_float(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags. Precedence: flags > environment > config.py."""
    parser = argparse.ArgumentParser(
        prog="eth-lottery",
        description=(
            "Generate random Ethereum private keys and check whether the "
            "derived addresses have a balance or transaction history."
        ),
        epilog=(
            "The probability of finding a funded account is effectively zero. "
            "This tool is for research and education only."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--ipc",
        metavar="PATH",
        default=_env_str("ETH_LOTTERY_IPC_PATH", config.IPC_PATH),
        help="path to the node's IPC socket",
    )
    parser.add_argument(
        "--http",
        dest="http_url",
        metavar="URL",
        default=_env_str("ETH_LOTTERY_HTTP_URL", config.HTTP_URL) or None,
        help="JSON-RPC HTTP endpoint (overrides --ipc)",
    )
    parser.add_argument(
        "--write-log",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("ETH_LOTTERY_WRITE_LOG", config.WRITE_LOG),
        help="append every checked key to the log file",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        metavar="PATH",
        default=Path(
            _env_str("ETH_LOTTERY_LOG_FILE", config.LOG_FILE) or config.LOG_FILE
        ),
        help="file that receives one line per checked key",
    )
    parser.add_argument(
        "--jackpot-file",
        type=Path,
        metavar="PATH",
        default=Path(
            _env_str("ETH_LOTTERY_JACKPOT_FILE", config.JACKPOT_FILE)
            or config.JACKPOT_FILE
        ),
        help="file that receives matching keys (created with mode 0600)",
    )
    parser.add_argument(
        "--delay",
        type=_non_negative_float,
        metavar="SECONDS",
        default=_env_float("ETH_LOTTERY_DELAY", config.DELAY),
        help="sleep between checks",
    )
    parser.add_argument(
        "--report-every",
        type=_non_negative_int,
        metavar="N",
        default=_env_int("ETH_LOTTERY_REPORT_EVERY", config.REPORT_EVERY),
        help="log a progress line every N checks (0 disables)",
    )
    parser.add_argument(
        "--max-checks",
        type=_non_negative_int,
        metavar="N",
        default=_env_int("ETH_LOTTERY_MAX_CHECKS", config.MAX_CHECKS),
        help="stop after N keys (0 = unlimited)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        metavar="SECONDS",
        default=_env_float("ETH_LOTTERY_TIMEOUT", config.TIMEOUT, minimum=0.001),
        help="provider request timeout",
    )
    parser.add_argument(
        "--reconnect-delay",
        type=_non_negative_float,
        metavar="SECONDS",
        default=_env_float(
            "ETH_LOTTERY_RECONNECT_DELAY", config.RECONNECT_DELAY
        ),
        help="wait before retrying the node connection",
    )
    parser.add_argument(
        "--connect-retries",
        type=_non_negative_int,
        metavar="N",
        default=_env_int(
            "ETH_LOTTERY_CONNECT_RETRIES", config.CONNECT_RETRIES
        ),
        help="connection attempts before giving up (0 = retry forever)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only print matches; progress and summaries still go to stderr",
    )
    parser.add_argument(
        "--debug", action="store_true", help="enable debug logging"
    )
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> Settings:
    """Merge parsed arguments into an immutable ``Settings`` object."""
    return Settings(
        ipc_path=args.ipc,
        http_url=args.http_url,
        write_log=args.write_log,
        log_file=args.log_file,
        jackpot_file=args.jackpot_file,
        delay=args.delay,
        report_every=args.report_every,
        max_checks=args.max_checks or None,
        timeout=args.timeout,
        reconnect_delay=args.reconnect_delay,
        connect_retries=args.connect_retries,
    )


def _configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        force=True,
    )


def _install_signal_handlers(stop: threading.Event) -> None:
    def _handle(signum: int, frame: FrameType | None) -> None:
        del frame
        name = signal.Signals(signum).name
        if stop.is_set():
            LOG.error("Second %s received; exiting immediately.", name)
            raise SystemExit(EXIT_INTERRUPTED)
        LOG.info("Received %s; finishing the current check ...", name)
        stop.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signal_number, _handle)
        except (ValueError, OSError):  # not the main thread / unsupported
            pass


def _log_node_info(client: ChainClient) -> None:
    try:
        LOG.info(
            "Node reports chain id %s at block %s.",
            client.eth.chain_id,
            client.eth.block_number,
        )
    except Exception as exc:  # noqa: BLE001 - metadata is optional
        LOG.debug("Could not read node metadata: %s", exc)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    try:
        args = parse_args(argv)
        settings = settings_from_args(args)
    except (LotteryError, ValueError) as exc:
        print(f"eth-lottery: configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    _configure_logging(args.debug)
    LOG.info("eth-lottery %s (Python %s)", __version__, sys.version.split()[0])
    warn_if_permissive(settings.jackpot_file)

    stop = threading.Event()
    _install_signal_handlers(stop)

    def client_factory() -> ChainClient:
        return build_client(settings)

    try:
        client = connect(client_factory, settings, stop)
    except LotteryError as exc:
        LOG.error("%s", exc)
        return EXIT_ERROR

    if client is None:
        if stop.is_set():
            LOG.info("Interrupted before a connection was established.")
            return EXIT_OK
        LOG.error("Could not connect to an Ethereum node. Check --ipc/--http.")
        return EXIT_ERROR

    _log_node_info(client)

    def report(result: CheckResult) -> None:
        if result.is_win or not args.quiet:
            print(result.to_line(), flush=True)

    try:
        stats = scan(
            client,
            settings,
            stop=stop,
            client_factory=client_factory,
            on_result=report,
        )
    except LotteryError as exc:
        LOG.error("%s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        LOG.info("Interrupted by user.")
        return EXIT_OK

    LOG.info(
        "Stopped after %d key(s): %d match(es), %d error(s), %d reconnect(s), "
        "%.2f keys/s.",
        stats.attempts,
        stats.wins,
        stats.errors,
        stats.reconnects,
        stats.rate(),
    )
    if stats.wins:
        LOG.warning(
            "Matches were saved to %s (mode 0600). Move the keys offline now.",
            settings.jackpot_file,
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())


