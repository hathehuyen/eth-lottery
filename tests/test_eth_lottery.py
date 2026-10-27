"""Unit tests for eth_lottery.

Run with:  python -m unittest discover -v

The suite uses fake node clients, so it does not need web3.py, network access
or a real Ethereum node.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import eth_lottery
from eth_lottery import (
    CheckResult,
    LotteryError,
    Settings,
    append_private_line,
    connect,
    new_private_key,
    parse_args,
    read_account,
    scan,
    settings_from_args,
    utc_timestamp,
)

FAKE_ADDRESS = "0x" + "ab" * 20


class FakeEth:
    """Minimal ``web3.eth`` replacement driven by iterables."""

    def __init__(self, balances, nonces, fail_first=False):
        self.balances = iter(balances)
        self.nonces = iter(nonces)
        self.fail_first = fail_first
        self.calls: list[tuple[str, str]] = []

    def get_balance(self, address, block_identifier=None):
        del block_identifier
        self.calls.append(("balance", address))
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("node went away")
        return next(self.balances)

    def get_transaction_count(self, address, block_identifier=None):
        del block_identifier
        self.calls.append(("nonce", address))
        return next(self.nonces)


class FakeClient:
    """Minimal ``web3.Web3`` replacement."""

    def __init__(self, balances=(0,), nonces=(0,), fail_first=False):
        self.eth = FakeEth(balances, nonces, fail_first=fail_first)

    def is_connected(self):
        return True


class UnreachableClient:
    def __init__(self):
        self.eth = FakeEth([], [])

    def is_connected(self):
        return False


def sequential_keys(count):
    """Deterministic key factory: 32-byte keys with distinct hex values."""
    values = iter(range(1, count + 1))

    def factory():
        index = next(values)
        key = bytes([index % 256]) * 32
        return key, key.hex()

    return factory


def fake_derive(private_key):
    del private_key
    return FAKE_ADDRESS


def make_settings(tmp_path, **overrides):
    values = {
        "write_log": True,
        "log_file": tmp_path / "eth_lottery.log",
        "jackpot_file": tmp_path / "eth_jackpot.gold",
        "delay": 0.0,
        "report_every": 0,
        "max_checks": 3,
        "timeout": 1.0,
        "reconnect_delay": 0.0,
        "connect_retries": 1,
    }
    values.update(overrides)
    return Settings(**values)


class SettingsTests(unittest.TestCase):
    def test_defaults_come_from_config_module(self):
        settings = Settings()
        self.assertEqual(
            settings.ipc_path, str(Path(eth_lottery.config.IPC_PATH).expanduser())
        )
        self.assertEqual(settings.http_url, eth_lottery.config.HTTP_URL)

    def test_rejects_negative_values(self):
        for field in ("delay", "report_every", "reconnect_delay", "connect_retries"):
            with self.subTest(field=field):
                with self.assertRaises(LotteryError):
                    Settings(**{field: -1})

    def test_rejects_zero_timeout_and_max_checks(self):
        with self.assertRaises(LotteryError):
            Settings(timeout=0)
        with self.assertRaises(LotteryError):
            Settings(max_checks=0)

    def test_requires_a_provider(self):
        with self.assertRaises(LotteryError):
            Settings(http_url=None, ipc_path="  ")

    def test_expands_user_in_paths(self):
        settings = Settings(
            ipc_path="~/node.ipc",
            log_file=Path("~/lottery.log"),
            jackpot_file=Path("~/jackpot.gold"),
        )
        self.assertNotIn("~", settings.ipc_path)
        self.assertNotIn("~", str(settings.log_file))


class KeyTests(unittest.TestCase):
    def test_new_private_key_is_32_bytes_and_hex(self):
        key, key_hex = new_private_key()
        self.assertIsInstance(key, bytes)
        self.assertEqual(len(key), 32)
        self.assertEqual(key_hex, key.hex())
        self.assertEqual(len(key_hex), 64)

    def test_utc_timestamp_is_iso_8601_utc(self):
        timestamp = utc_timestamp()
        self.assertTrue(timestamp.endswith("+00:00"), timestamp)
        self.assertIn("T", timestamp)


class CheckResultTests(unittest.TestCase):
    def test_line_has_original_column_order(self):
        result = CheckResult(
            checked_at="2026-01-01T00:00:00.000000+00:00",
            private_key_hex="cd" * 32,
            address=FAKE_ADDRESS,
            balance=123,
            nonce=2,
        )
        self.assertEqual(
            result.to_line().split(" "),
            [
                "2026-01-01T00:00:00.000000+00:00",
                "cd" * 32,
                FAKE_ADDRESS,
                "123",
                "2",
            ],
        )

    def test_win_when_balance_or_nonce_is_non_zero(self):
        base = dict(
            checked_at="now",
            private_key_hex="00" * 32,
            address=FAKE_ADDRESS,
        )
        self.assertFalse(CheckResult(balance=0, nonce=0, **base).is_win)
        self.assertTrue(CheckResult(balance=1, nonce=0, **base).is_win)
        self.assertTrue(CheckResult(balance=0, nonce=1, **base).is_win)


class OutputTests(unittest.TestCase):
    def test_append_private_line_creates_mode_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "jackpot.gold"
            append_private_line(path, "secret")
            self.assertEqual(path.read_text(encoding="utf-8"), "secret\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_append_private_line_tightens_existing_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jackpot.gold"
            path.write_text("old\n", encoding="utf-8")
            path.chmod(0o644)
            append_private_line(path, "new")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_text(encoding="utf-8"), "old\nnew\n")


class ScannerTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_read_account_uses_balance_and_transaction_count(self):
        client = FakeClient(balances=[7], nonces=[3])
        self.assertEqual(read_account(client, FAKE_ADDRESS), (7, 3))
        self.assertEqual(
            client.eth.calls,
            [("balance", FAKE_ADDRESS), ("nonce", FAKE_ADDRESS)],
        )

    def test_scan_counts_wins_and_writes_log_and_jackpot(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = make_settings(tmp_path)
            client = FakeClient(balances=[0, 1, 0], nonces=[0, 0, 5])
            seen = []

            stats = scan(
                client,
                settings,
                max_checks=3,
                derive=fake_derive,
                new_key=sequential_keys(3),
                on_result=seen.append,
            )

            self.assertEqual(stats.attempts, 3)
            self.assertEqual(stats.wins, 2)
            self.assertEqual(stats.errors, 0)
            self.assertEqual(len(seen), 3)
            self.assertEqual(len(settings.log_file.read_text().splitlines()), 3)

            jackpot_lines = settings.jackpot_file.read_text().splitlines()
            self.assertEqual(len(jackpot_lines), 2)
            self.assertTrue(all(FAKE_ADDRESS in line for line in jackpot_lines))
            self.assertEqual(
                stat.S_IMODE(settings.jackpot_file.stat().st_mode), 0o600
            )

    def test_scan_without_log_does_not_create_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), write_log=False, max_checks=1)
            stats = scan(
                FakeClient(balances=[2], nonces=[0]),
                settings,
                derive=fake_derive,
                new_key=sequential_keys(1),
            )
            self.assertEqual(stats.wins, 1)
            self.assertFalse(settings.log_file.exists())
            self.assertTrue(settings.jackpot_file.exists())

    def test_scan_recovers_from_rpc_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), max_checks=1, write_log=False)
            replacement = FakeClient(balances=[0], nonces=[0])
            clients = iter([replacement])

            def factory():
                return next(clients)

            stats = scan(
                FakeClient(fail_first=True),
                settings,
                max_checks=1,
                client_factory=factory,
                derive=fake_derive,
                new_key=sequential_keys(2),
            )

            self.assertEqual(stats.attempts, 1)
            self.assertEqual(stats.errors, 1)
            self.assertEqual(stats.reconnects, 1)

    def test_scan_raises_without_factory_on_rpc_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), write_log=False)
            with self.assertRaises(LotteryError):
                scan(
                    FakeClient(fail_first=True),
                    settings,
                    max_checks=1,
                    derive=fake_derive,
                    new_key=sequential_keys(1),
                )

    def test_scan_raises_when_reconnect_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(
                Path(tmp),
                write_log=False,
                max_checks=1,
                connect_retries=1,
            )
            with self.assertRaises(LotteryError):
                scan(
                    FakeClient(fail_first=True),
                    settings,
                    max_checks=1,
                    client_factory=UnreachableClient,
                    derive=fake_derive,
                    new_key=sequential_keys(1),
                )

    def test_scan_returns_immediately_when_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp))
            stop = threading.Event()
            stop.set()
            stats = scan(
                FakeClient(),
                settings,
                stop=stop,
                derive=fake_derive,
                new_key=sequential_keys(1),
            )
            self.assertEqual(stats.attempts, 0)

    def test_scan_discards_underivable_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), max_checks=1, write_log=False)

            def bad_derive(private_key):
                del private_key
                stop.set()
                raise ValueError("not a valid key")

            stop = threading.Event()
            stats = scan(
                FakeClient(),
                settings,
                stop=stop,
                max_checks=1,
                derive=bad_derive,
                new_key=sequential_keys(1),
            )
            self.assertEqual(stats.attempts, 0)
            self.assertEqual(stats.errors, 1)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_connect_gives_up_after_configured_attempts(self):
        settings = Settings(connect_retries=3, reconnect_delay=0.0)
        calls = []

        def factory():
            calls.append(1)
            return UnreachableClient()

        self.assertIsNone(connect(factory, settings))
        self.assertEqual(len(calls), 3)

    def test_connect_returns_working_client(self):
        settings = Settings(connect_retries=1, reconnect_delay=0.0)
        client = FakeClient()
        self.assertIs(connect(lambda: client, settings), client)

    def test_connect_propagates_configuration_errors(self):
        settings = Settings(connect_retries=3, reconnect_delay=0.0)

        def factory():
            raise LotteryError("web3.py is not installed")

        with self.assertRaises(LotteryError):
            connect(factory, settings)


class CliTests(unittest.TestCase):
    def test_parse_args_reads_environment(self):
        env = {
            "ETH_LOTTERY_MAX_CHECKS": "7",
            "ETH_LOTTERY_WRITE_LOG": "off",
            "ETH_LOTTERY_HTTP_URL": "http://127.0.0.1:8545",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            args = parse_args([])
        self.assertEqual(args.max_checks, 7)
        self.assertFalse(args.write_log)
        self.assertEqual(args.http_url, "http://127.0.0.1:8545")

    def test_flags_override_environment(self):
        env = {"ETH_LOTTERY_MAX_CHECKS": "7", "ETH_LOTTERY_WRITE_LOG": "off"}
        with mock.patch.dict(os.environ, env, clear=True):
            args = parse_args(["--max-checks", "2", "--write-log"])
        self.assertEqual(args.max_checks, 2)
        self.assertTrue(args.write_log)

    def test_settings_from_args_maps_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "a.log"
            jackpot_path = Path(tmp) / "b.gold"
            args = parse_args(
                [
                    "--ipc",
                    "/tmp/node.ipc",
                    "--no-write-log",
                    "--log-file",
                    str(log_path),
                    "--jackpot-file",
                    str(jackpot_path),
                    "--delay",
                    "0.5",
                    "--report-every",
                    "10",
                    "--max-checks",
                    "4",
                    "--timeout",
                    "2.5",
                    "--reconnect-delay",
                    "1.5",
                    "--connect-retries",
                    "2",
                ]
            )
            settings = settings_from_args(args)
            self.assertEqual(settings.ipc_path, "/tmp/node.ipc")
            self.assertFalse(settings.write_log)
            self.assertEqual(settings.log_file, log_path)
            self.assertEqual(settings.jackpot_file, jackpot_path)
            self.assertEqual(settings.delay, 0.5)
            self.assertEqual(settings.report_every, 10)
            self.assertEqual(settings.max_checks, 4)
            self.assertEqual(settings.timeout, 2.5)
            self.assertEqual(settings.reconnect_delay, 1.5)
            self.assertEqual(settings.connect_retries, 2)

    def test_help_exits_zero(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as raised:
                parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--max-checks", buffer.getvalue())

    def test_version_exits_zero(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as raised:
                parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(eth_lottery.__version__, buffer.getvalue())

    def test_invalid_environment_value_returns_usage_error(self):
        with mock.patch.dict(os.environ, {"ETH_LOTTERY_DELAY": "soon"}, clear=True):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(eth_lottery.main([]), eth_lottery.EXIT_USAGE)

    def test_invalid_flag_returns_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                parse_args(["--timeout", "0"])
        self.assertEqual(raised.exception.code, 2)


class Web3ImportTests(unittest.TestCase):
    def test_build_client_reports_missing_web3(self):
        try:
            import web3  # noqa: F401
        except ImportError:
            settings = Settings(http_url="http://127.0.0.1:8545", timeout=1.0)
            with self.assertRaises(LotteryError):
                eth_lottery.build_client(settings)
        else:
            self.skipTest("web3.py is installed")

    def test_build_client_uses_http_provider_when_configured(self):
        try:
            import web3  # noqa: F401
        except ImportError:
            self.skipTest("web3.py is not installed")

        settings = Settings(http_url="http://127.0.0.1:8545", timeout=1.0)
        client = eth_lottery.build_client(settings)
        self.assertTrue(client.provider.endpoint_uri.startswith("http://"))


if __name__ == "__main__":
    unittest.main()


