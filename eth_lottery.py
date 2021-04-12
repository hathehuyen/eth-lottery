import os
import config
from datetime import datetime
from web3 import Web3

# IPCProvider:
w3 = Web3(Web3.IPCProvider('~/.ethereum/geth.ipc'))

# # HTTPProvider:
#w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))

# # WebsocketProvider:
#w3 = Web3(Web3.WebsocketProvider('ws://127.0.0.1:8546'))

if w3.isConnected():
    print('ETH Connected')
else:
    print('ETH NOT Connected')
    exit(1)


log_file = "eth_lottery.log"
jackpot_file = "eth_jackpot.gold"
if config.write_log:
    log_file = open(log_file, "a")
while True:
    check_time = str(datetime.now())
    key_bin = os.urandom(32)
    key_hex = key_bin.hex()
    account = w3.eth.account.privateKeyToAccount(key_bin)
    address = account.address
    txs = w3.eth.get_transaction_count(address)
    balance = w3.eth.get_balance(address)
    result = '{0} {1} {2} {3} {4}'.format(check_time, key_hex, address, balance, txs)
    print(result)
    if config.write_log:
        log_file.write(result + '\n')
    if balance != 0 or txs != 0:
        with open(jackpot_file, "a") as winfile:
            winfile.write(result + '\n')
