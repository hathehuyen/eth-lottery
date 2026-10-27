# eth-lottery

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![web3.py](https://img.shields.io/badge/web3.py-8.x-orange.svg)](https://web3py.readthedocs.io/)
[![License: LGPL-2.1](https://img.shields.io/badge/license-LGPL--2.1-blue.svg)](LICENSE)

> **Read this first — this is not a way to get rich.**
>
> `eth-lottery` generates random secp256k1 private keys, derives the matching
> Ethereum address, and asks a node whether that address has ever held ether
> or sent a transaction. The chance that a random key maps to a funded account
> is roughly **1 in 10⁴⁰**. Running it for the lifetime of the universe on
> ordinary hardware will not find anything. It is published as a compact
> example of key generation, address derivation and JSON-RPC interaction with
> modern `web3.py` — not as a practical key-recovery or profit tool.
>
> Using this software to take control of funds you do not own is likely
> illegal in your jurisdiction and is not condoned by the author. You are
> responsible for how you use it. See [Security, ethics and legality](#security-ethics-and-legality).

English | [Tiếng Việt](README.vi.md)

---

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Why finding a match is unrealistic](#why-finding-a-match-is-unrealistic)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Output files](#output-files)
- [Exit codes and signals](#exit-codes-and-signals)
- [Security, ethics and legality](#security-ethics-and-legality)
- [Project structure](#project-structure)
- [Development](#development)
- [Upgrading from v1](#upgrading-from-v1)
- [Troubleshooting](#troubleshooting)
- [Limitations and roadmap](#limitations-and-roadmap)
- [License](#license)

## What it does

For every generated key the program:

1. generates 32 bytes with `secrets.token_bytes()` (CSPRNG);
2. derives the checksummed `0x…` address with `eth_account.Account.from_key()`;
3. calls `eth_getBalance` and `eth_getTransactionCount` on an Ethereum node;
4. prints and optionally logs one line with timestamp, private key, address,
   balance and nonce;
5. appends matches (non-zero balance **or** non-zero nonce) to a private
   jackpot file created with mode `0600`.

It never sends transactions, never needs an unlocked account and never spends
gas.

## How it works

```text
        secrets.token_bytes(32)
                  │
                  ▼
      Account.from_key(key).address        (secp256k1 + Keccak-256)
                  │
                  ▼
   eth_getBalance(address, "latest")  ──┐
   eth_getTransactionCount(address)   ──┤  JSON-RPC over IPC or HTTP
                  │                     │
                  ▼                     ▼
     CheckResult ──► stdout / log file / jackpot file (if match)
```

Two JSON-RPC calls are made per key, so throughput is dominated by node
latency rather than CPU. A local IPC socket is the fastest and most private
option; HTTP is convenient for remote nodes.

## Why finding a match is unrealistic

| Quantity | Approximate value |
| --- | --- |
| Possible addresses | 2¹⁶⁰ ≈ 1.46 × 10⁴⁸ |
| Addresses with any activity | ~10⁸ (order of magnitude) |
| Probability per random key | ~7 × 10⁻⁴¹ |
| Keys needed for one expected hit | ~1.5 × 10⁴⁰ |
| Time at 1,000 keys/s | ~4.6 × 10²⁹ years |

The universe is about 1.4 × 10¹⁰ years old, so the expected search takes
roughly 3 × 10¹⁹ times the age of the universe. GPU farms do not change the
conclusion: this is a birthday-problem / key-space argument, not an
implementation bottleneck.

## Requirements

- **Python ≥ 3.10** (web3.py 8 requires it; tested on 3.10–3.13)
- **web3.py ≥ 8.0, < 9.0** (installed automatically)
- An Ethereum node you are allowed to query:
  - local **geth** with IPC at `~/.ethereum/geth.ipc` (default), or
  - any **JSON-RPC HTTP** endpoint exposing `eth_getBalance` and
    `eth_getTransactionCount`, e.g. `geth --http --http.api eth,net`.

No API key is bundled. The script does not read environment files and does
not embed credentials.

## Installation

```bash
git clone https://github.com/hathehuyen/eth-lottery.git
cd eth-lottery

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"  # runtime + test/lint tools
```

If you only need the runtime dependency:

```bash
python -m pip install -r requirements.txt
python eth_lottery.py --help
```

Installing the project also provides the `eth-lottery` console command, which
is equivalent to `python eth_lottery.py`.

## Configuration

Settings are resolved in this order (highest priority first):

1. **CLI flags**
2. **Environment variables** (`ETH_LOTTERY_*`)
3. **`config.py`** defaults committed to the repository

`config.py` contains no secrets and is safe to edit or commit.

| Environment variable | `config.py` | CLI flag | Default | Meaning |
| --- | --- | --- | --- | --- |
| `ETH_LOTTERY_IPC_PATH` | `IPC_PATH` | `--ipc PATH` | `~/.ethereum/geth.ipc` | Node IPC socket |
| `ETH_LOTTERY_HTTP_URL` | `HTTP_URL` | `--http URL` | unset | JSON-RPC HTTP endpoint (overrides IPC) |
| `ETH_LOTTERY_WRITE_LOG` | `WRITE_LOG` | `--write-log` / `--no-write-log` | `true` | Append every key to the log |
| `ETH_LOTTERY_LOG_FILE` | `LOG_FILE` | `--log-file PATH` | `eth_lottery.log` | Per-key log path |
| `ETH_LOTTERY_JACKPOT_FILE` | `JACKPOT_FILE` | `--jackpot-file PATH` | `eth_jackpot.gold` | Match file path |
| `ETH_LOTTERY_DELAY` | `DELAY` | `--delay SECONDS` | `0` | Sleep between checks |
| `ETH_LOTTERY_REPORT_EVERY` | `REPORT_EVERY` | `--report-every N` | `1000` | Progress line interval (`0` = off) |
| `ETH_LOTTERY_MAX_CHECKS` | `MAX_CHECKS` | `--max-checks N` | `0` | Stop after N keys (`0` = unlimited) |
| `ETH_LOTTERY_TIMEOUT` | `TIMEOUT` | `--timeout SECONDS` | `10` | Provider request timeout |
| `ETH_LOTTERY_RECONNECT_DELAY` | `RECONNECT_DELAY` | `--reconnect-delay SECONDS` | `5` | Wait before reconnect |
| `ETH_LOTTERY_CONNECT_RETRIES` | `CONNECT_RETRIES` | `--connect-retries N` | `3` | Attempts before giving up (`0` = forever) |

Boolean environment variables accept `1/0`, `true/false`, `yes/no`, `on/off`.

Invalid values fail fast with exit code `2` and a message naming the variable
or flag.

## Usage

```bash
# Help and version
python eth_lottery.py --help
python eth_lottery.py --version

# 1,000 keys against the local IPC node
python eth_lottery.py --max-checks 1000

# HTTP node, throttled, bounded run
python eth_lottery.py \
  --http http://127.0.0.1:8545 \
  --max-checks 5000 \
  --delay 0.05

# Same, configured through the environment
ETH_LOTTERY_HTTP_URL=http://127.0.0.1:8545 \
ETH_LOTTERY_MAX_CHECKS=1000 \
  python eth_lottery.py --quiet

# Keep results in a private directory
python eth_lottery.py \
  --log-file ~/.local/state/eth-lottery/scan.log \
  --jackpot-file ~/.local/state/eth-lottery/jackpot.gold
```

`--quiet` suppresses per-key lines on stdout; matches and stderr progress /
summary lines are still emitted.

Example stdout line (values redacted):

```text
2026-10-27T08:00:00.123456+00:00 3f2a…c91d 0x4c8b…19f2 0 0
```

### Output format

Each checked key is one space-separated line:

```text
<timestamp> <private-key-hex> <address> <balance-wei> <nonce>
```

- `timestamp` — ISO-8601 UTC with microseconds (`…+00:00`)
- `private-key-hex` — 64 lowercase hex characters, no `0x` prefix
- `address` — EIP-55 checksummed address
- `balance-wei` — integer wei as returned by `eth_getBalance("latest")`
- `nonce` — integer transaction count (`eth_getTransactionCount`)

Matches are written in the same format to the jackpot file and reported on
stderr at `WARNING` level.

## Output files

| File | Contents | Permissions |
| --- | --- | --- |
| `eth_lottery.log` | One line per checked key | Consult your umask; contains private keys |
| `eth_jackpot.gold` | Only matching key lines | Forced to `0600`, created on first match |

Both patterns (`*.log`, `*.gold`) are ignored by Git. **Treat the log as
sensitive**: it contains every generated private key, including any future
match. The script warns if an existing jackpot file is group/world-readable.

## Exit codes and signals

| Code | Meaning |
| --- | --- |
| `0` | Limit reached, scan completed, or interrupted cleanly |
| `1` | Connection could not be established, RPC failed fatally, web3.py is missing, or an output file could not be written |
| `2` | Invalid CLI flag or environment value |
| `130` | Second `SIGINT`/`SIGTERM` forced an immediate exit |

The first `Ctrl+C` (SIGINT) or SIGTERM sets a stop flag, finishes the current
check, flushes the log, prints a summary and exits cleanly. A second signal
exits immediately.

## Security, ethics and legality

- **Private keys are generated locally** with Python's `secrets` module. No
  key or seed is ever transmitted; only addresses leave the machine.
- **Logs and the jackpot file are secrets.** They are written in plain text.
  Restrict permissions, encrypt or delete them after use, and never commit,
  paste or upload them. The jackpot file is created with mode `0600`.
- **Prefer your own node.** A remote/public RPC provider sees every address
  you query (linkable to your IP and API key), may rate-limit you, and may
  prohibit automated scanning in its terms of service. IPC is both faster and
  more private.
- **Do not run this on shared or untrusted machines.** Anyone with access to
  the log can sweep any key that later receives funds.
- **Legality.** Randomly probing the chain is generally harmless, but moving
  funds from an address whose key you found is not. Depending on where you
  live it can constitute theft, unauthorized access or money laundering.
  Nothing here grants you ownership of an address, and a collision does not
  create a legal right to its funds.
- **This is deliberately impractical.** It demonstrates cryptography and RPC
  plumbing; it is not a key-recovery service. If you lost a seed phrase, use
  your backup — not brute force.

## Project structure

```text
eth-lottery/
├── eth_lottery.py            # CLI, scanner loop, providers, secure output
├── config.py                 # user-editable defaults (no secrets)
├── requirements.txt          # runtime dependency pin (web3 8.x)
├── pyproject.toml            # packaging, console script, test/lint config
├── tests/
│   ├── __init__.py
│   └── test_eth_lottery.py   # stdlib unittest suite with fake node clients
├── README.md                 # this file
├── README.vi.md              # Vietnamese overview
└── LICENSE                   # LGPL-2.1
```

The scanner is intentionally dependency-injected: `scan()` accepts a fake
node client, key factory and address deriver, so the loop can be tested
without web3.py or network access. web3 is imported lazily in `build_client()`
and `derive_address()`, keeping the pure logic importable in lightweight
environments.

## Development

```bash
python -m unittest discover -v       # standard library, no extra deps
python -m pip install -e ".[dev]"    # optional: pytest + ruff
python -m pytest -q                  # pytest can also run the unittest suite
ruff check .
python eth_lottery.py --help
```

The suite is compatible with Python 3.10–3.13 and never contacts a real node.
Wire it into your CI provider with `python -m unittest discover -v` and
`ruff check .`.
To add a provider, implement the small `ChainClient`/`EthApi` protocols in
`eth_lottery.py` (or return a real `Web3` instance) and teach `build_client()`
how to construct it. Keep `max_checks` bounded when testing.

## Upgrading from v1

v2 is a breaking upgrade to a supported Python and web3.py release; the
on-disk log format keeps the original five columns.

| Area | v1 (2021) | v2 (current) |
| --- | --- | --- |
| Runtime | Python 3.8 via Pipenv | Python ≥ 3.10 via `pyproject.toml` |
| web3.py | 5.x (unmaintained) | 8.x |
| Connection check | `w3.isConnected()` | `w3.is_connected()` |
| Key handling | `w3.eth.account.privateKeyToAccount()` | `Account.from_key(...).address` |
| Timestamps | naive local `str(datetime.now())` | ISO-8601 UTC with offset |
| Logging | bare `print` + unflushed `open()` | line-buffered log, flushed/closed on exit |
| Limits | infinite loop only | `--max-checks`, `--delay`, progress stats |
| Shutdown | `Ctrl+C` traceback | graceful SIGINT/SIGTERM, summary |
| Resilience | none | connection retries and automatic reconnect |
| Jackpot file | default umask (often `0644`) | forced `0600` + permission warning |
| Config | `config.write_log` only | `config.py` + `ETH_LOTTERY_*` + CLI flags |
| Tests | none | 31 stdlib tests with a fake node |
| Dependency lock | `Pipfile.lock` pinned web3 5.x | `requirements.txt` / `pyproject.toml` |

`Pipfile`/`Pipfile.lock` were removed: the lock could not be regenerated for
web3 8 and pinned a Python 3.8-era dependency set. Use `pip install -e .` or
`pip install -r requirements.txt` instead.

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `Could not connect to an Ethereum node` | Node not running, wrong `--ipc` path, or HTTP RPC disabled. Start `geth --http --http.api eth,net` and set `--http http://127.0.0.1:8545`. |
| `FileNotFoundError` / IPC socket missing | `~` expansion is applied, but the socket must exist. Check `geth attach` works first. |
| HTTP 401/403/429 | The endpoint needs a key, blocks your region, or rate-limits you. Use a local node and `--delay`. |
| `web3.py is not installed` | Activate the virtualenv and run `pip install -e .`. |
| SSL certificate errors with pip | Corporate proxy interception; configure `PIP_CERT`/`REQUESTS_CA_BUNDLE` or use an internal index. |
| `configuration error: ETH_LOTTERY_…` | An environment value is malformed; unset it or pass the CLI flag explicitly. |
| Slow throughput | Each key costs two RPC round trips. Use IPC, lower `--timeout`, avoid remote HTTP, and do not add `--delay` unless required. |
| Log/jackpot permission warning | Run `chmod 600 <file>`; the jackpot file is tightened automatically on the next write. |

## Limitations and roadmap

- **Synchronous providers only.** web3.py 8's WebSocket provider is async-only,
  so `--http` and `--ipc` are supported. An async WebSocket mode would require
  restructuring the loop; contributions are welcome.
- **No batching.** Balance/nonce calls are sequential. JSON-RPC batching would
  improve throughput on HTTP nodes but complicate rate-limit handling.
- **No deduplication.** Keys are random, so repeats are not tracked; a local
  Bloom filter or database would only matter for deterministic key derivation.
- **Chain-agnostic.** Any EVM node works; there is no testnet/mainnet switch
  because the script never signs or sends transactions.
- **No wallet recovery features.** It does not accept a mnemonic, a target
  address or a key range. That is intentional.

## License

Distributed under the **GNU Lesser General Public License v2.1**. See
[LICENSE](LICENSE) for the full text.

## Acknowledgements

- [web3.py](https://github.com/ethereum/web3.py) and
  [eth-account](https://github.com/ethereum/eth-account) for the Ethereum
  plumbing.
- [Ethereum Yellow Paper](https://ethereum.github.io/yellowpaper/paper.pdf)
  for the address-derivation details.
- Originally written by [Huyen Ha](https://github.com/hathehuyen) in 2021 and
  modernized in 2026.



