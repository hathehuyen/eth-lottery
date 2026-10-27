"""User-editable defaults for eth-lottery.

Values here are the lowest-priority defaults. Override them with environment
variables (``ETH_LOTTERY_*``) or CLI flags; see README.md for the full table.

This module intentionally contains no secrets: it is safe to commit.
"""

from __future__ import annotations

# Path to a local node's IPC socket (fastest and most private option).
IPC_PATH = "~/.ethereum/geth.ipc"

# Optional JSON-RPC HTTP endpoint. When set, it takes precedence over IPC.
HTTP_URL: str | None = None

# Append every checked key to ``LOG_FILE``. This file contains private keys.
WRITE_LOG = True

LOG_FILE = "eth_lottery.log"
JACKPOT_FILE = "eth_jackpot.gold"

# Seconds to sleep between checks (useful to avoid hammering a shared node).
DELAY = 0.0

# Log a progress line every N successful checks. 0 disables progress output.
REPORT_EVERY = 1000

# Stop after N successful checks. 0 means "run until interrupted".
MAX_CHECKS = 0

# Provider request timeout, in seconds.
TIMEOUT = 10.0

# Seconds to wait before reconnecting after a connection/RPC failure.
RECONNECT_DELAY = 5.0

# Connection attempts before giving up. 0 means "retry forever".
CONNECT_RETRIES = 3
