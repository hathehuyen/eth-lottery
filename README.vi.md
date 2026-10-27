# eth-lottery

[English](README.md) | **Tiếng Việt**

> ⚠️ **Đọc kỹ trước khi chạy:** đây **không phải** công cụ kiếm tiền hay khôi
> phục ví. Chương trình sinh khóa riêng Ethereum ngẫu nhiên, suy ra địa chỉ và
> hỏi node xem địa chỉ đó từng có ETH hoặc từng gửi giao dịch hay chưa. Xác
> suất một khóa ngẫu nhiên trùng với địa chỉ có tài sản là khoảng **1 trên
> 10⁴⁰** — chạy đến hết tuổi thọ vũ trụ trên phần cứng thông thường cũng không
> tìm thấy gì. Dự án được công bố như một ví dụ nhỏ về sinh khóa, suy ra địa
> chỉ và giao tiếp JSON-RPC bằng `web3.py` hiện đại.
>
> Dùng phần mềm này để chiếm đoạt tài sản không thuộc sở hữu của bạn có thể vi
> phạm pháp luật. Tác giả không cổ vũ hành vi đó.

## Dự án làm gì?

Với mỗi khóa được sinh ra, chương trình:

1. sinh 32 byte bằng `secrets.token_bytes()` (CSPRNG của Python);
2. suy ra địa chỉ checksum bằng `eth_account.Account.from_key()`;
3. gọi `eth_getBalance` và `eth_getTransactionCount` trên node Ethereum;
4. in (và ghi log nếu bật) một dòng gồm thời gian, khóa riêng, địa chỉ, số dư
   (wei) và nonce;
5. ghi các trường hợp trùng (số dư khác 0 **hoặc** nonce khác 0) vào file
   jackpot riêng với quyền `0600`.

Chương trình **không ký giao dịch**, không cần tài khoản mở khóa và không tốn
gas.

## Vì sao gần như không thể tìm thấy?

| Đại lượng | Giá trị xấp xỉ |
| --- | --- |
| Số địa chỉ có thể có | 2¹⁶⁰ ≈ 1,46 × 10⁴⁸ |
| Số địa chỉ từng có hoạt động | ~10⁸ |
| Xác suất mỗi khóa ngẫu nhiên | ~7 × 10⁻⁴¹ |
| Số khóa cần cho một lần trúng kỳ vọng | ~1,5 × 10⁴⁰ |
| Thời gian ở 1.000 khóa/giây | ~4,6 × 10²⁹ năm |

Tuổi vũ trụ chỉ khoảng 1,4 × 10¹⁰ năm, tức thời gian tìm kiếm kỳ vọng gấp
khoảng 3 × 10¹⁹ lần tuổi vũ trụ. Đây là giới hạn của không gian khóa, không
phải vấn đề tốc độ code.

## Yêu cầu

- **Python ≥ 3.10** (web3.py 8 yêu cầu; dự án hỗ trợ 3.10–3.13)
- **web3.py ≥ 8.0, < 9.0** (pip tự cài)
- Một node Ethereum được phép truy vấn:
  - **geth** cục bộ qua IPC `~/.ethereum/geth.ipc` (mặc định), hoặc
  - endpoint **JSON-RPC HTTP** hỗ trợ `eth_getBalance` và
    `eth_getTransactionCount`, ví dụ `geth --http --http.api eth,net`.

## Cài đặt

```bash
git clone https://github.com/hathehuyen/eth-lottery.git
cd eth-lottery

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Chỉ cần dependency chạy:

```bash
python -m pip install -r requirements.txt
python eth_lottery.py --help
```

Sau khi cài, lệnh `eth-lottery` tương đương `python eth_lottery.py`.

## Cấu hình

Thứ tự ưu tiên: **cờ CLI > biến môi trường `ETH_LOTTERY_*` > `config.py`**.

| Biến môi trường | Cờ CLI | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `ETH_LOTTERY_IPC_PATH` | `--ipc PATH` | `~/.ethereum/geth.ipc` | Socket IPC của node |
| `ETH_LOTTERY_HTTP_URL` | `--http URL` | không đặt | Endpoint HTTP (ưu tiên hơn IPC) |
| `ETH_LOTTERY_WRITE_LOG` | `--write-log` / `--no-write-log` | `true` | Ghi mọi khóa vào log |
| `ETH_LOTTERY_LOG_FILE` | `--log-file PATH` | `eth_lottery.log` | File log |
| `ETH_LOTTERY_JACKPOT_FILE` | `--jackpot-file PATH` | `eth_jackpot.gold` | File lưu khóa trùng |
| `ETH_LOTTERY_DELAY` | `--delay SECONDS` | `0` | Nghỉ giữa các lần kiểm tra |
| `ETH_LOTTERY_REPORT_EVERY` | `--report-every N` | `1000` | Chu kỳ in tiến độ (`0` = tắt) |
| `ETH_LOTTERY_MAX_CHECKS` | `--max-checks N` | `0` | Dừng sau N khóa (`0` = vô hạn) |
| `ETH_LOTTERY_TIMEOUT` | `--timeout SECONDS` | `10` | Timeout request |
| `ETH_LOTTERY_RECONNECT_DELAY` | `--reconnect-delay SECONDS` | `5` | Chờ trước khi kết nối lại |
| `ETH_LOTTERY_CONNECT_RETRIES` | `--connect-retries N` | `3` | Số lần thử (`0` = mãi mãi) |

Biến boolean nhận `1/0`, `true/false`, `yes/no`, `on/off`. Giá trị sai khiến
chương trình thoát với mã `2` và thông báo rõ biến/cờ bị lỗi.

## Sử dụng

```bash
# Trợ giúp và phiên bản
python eth_lottery.py --help
python eth_lottery.py --version

# 1.000 khóa qua IPC cục bộ
python eth_lottery.py --max-checks 1000

# Node HTTP, có giãn cách, chạy giới hạn
python eth_lottery.py \
  --http http://127.0.0.1:8545 \
  --max-checks 5000 \
  --delay 0.05

# Cấu hình qua biến môi trường
ETH_LOTTERY_HTTP_URL=http://127.0.0.1:8545 \
ETH_LOTTERY_MAX_CHECKS=1000 \
  python eth_lottery.py --quiet
```

`--quiet` ẩn các dòng kết quả từng khóa trên stdout; các dòng trùng và tiến
độ/tổng kết trên stderr vẫn được in. Nhấn `Ctrl+C` lần đầu để dừng êm (ghi
xong khóa hiện tại, đóng log, in tổng kết); nhấn lần hai để thoát ngay (mã
`130`).

## Định dạng kết quả

Mỗi khóa là một dòng, các trường cách nhau bởi dấu cách:

```text
<thời-gian-ISO-8601-UTC> <khóa-riêng-64-hex> <địa-chỉ> <số-dư-wei> <nonce>
```

Ví dụ (đã che bớt):

```text
2026-10-27T08:00:00.123456+00:00 3f2a…c91d 0x4c8b…19f2 0 0
```

- `eth_lottery.log`: mọi khóa đã kiểm tra (chứa khóa riêng — hãy coi là bí mật).
- `eth_jackpot.gold`: chỉ các dòng trùng, tự tạo với quyền `0600`, được thêm
  vào `.gitignore`.

## An toàn và pháp lý

- Khóa riêng được sinh **cục bộ** bằng `secrets`; chỉ địa chỉ được gửi tới
  node. Không có khóa/seed nào rời khỏi máy.
- Log và file jackpot là **bí mật**: chứa khóa riêng dạng văn bản. Hãy giới hạn
  quyền, mã hóa hoặc xóa sau khi dùng; tuyệt đối không commit hay gửi lên mạng.
- **Nên dùng node riêng.** Nhà cung cấp RPC công khai thấy mọi địa chỉ bạn
  truy vấn (gắn với IP/API key), có thể giới hạn tần suất hoặc cấm quét tự
  động. IPC vừa nhanh vừa riêng tư hơn.
- Không chạy trên máy dùng chung/không tin cậy: ai đọc được log có thể lấy khóa
  nếu sau này khóa đó nhận được tiền.
- Việc dùng khóa tìm được để chuyển tiền từ địa chỉ không thuộc sở hữu của bạn
  có thể cấu thành trộm cắp hoặc truy cập trái phép tùy quốc gia. Va chạm khóa
  không tạo ra quyền sở hữu hợp pháp.
- Nếu mất seed phrase, hãy dùng bản sao lưu — đừng brute force.

## Kiểm thử và phát triển

```bash
python -m unittest discover -v     # chỉ cần thư viện chuẩn
python -m pytest -q                # nếu đã cài extras [dev]
ruff check .
```

Bộ test dùng node giả, không cần web3.py, mạng hay node thật. Bộ test tương
thích Python 3.10–3.13; có thể chạy trong CI bằng
`python -m unittest discover -v` và `ruff check .`.

## Nâng cấp từ v1

v2 thay đổi không tương thích để dùng Python và web3.py được hỗ trợ; định
dạng log vẫn giữ 5 cột như cũ.

| Hạng mục | v1 (2021) | v2 (hiện tại) |
| --- | --- | --- |
| Runtime | Python 3.8 + Pipenv | Python ≥ 3.10 + `pyproject.toml` |
| web3.py | 5.x (không còn bảo trì) | 8.x |
| Kiểm tra kết nối | `w3.isConnected()` | `w3.is_connected()` |
| Sinh tài khoản | `privateKeyToAccount()` | `Account.from_key(...).address` |
| Thời gian | giờ địa phương, không timezone | ISO-8601 UTC |
| Ghi log | `open()` không flush | log line-buffered, đóng/ghi đầy đủ khi thoát |
| Giới hạn | vòng lặp vô hạn | `--max-checks`, `--delay`, thống kê |
| Dừng | traceback khi `Ctrl+C` | dừng êm với SIGINT/SIGTERM |
| Lỗi mạng | không xử lý | thử lại và tự kết nối lại |
| File jackpot | quyền theo umask | ép `0600` + cảnh báo |
| Kiểm thử | không có | 31 test với node giả |

`Pipfile`/`Pipfile.lock` đã được bỏ vì khóa phiên bản cũ (web3 5.x, Python 3.8)
không thể tái tạo cho web3 8. Dùng `pip install -e .` hoặc
`pip install -r requirements.txt`.

## Giấy phép

Phát hành theo **GNU Lesser General Public License v2.1**. Xem [LICENSE](LICENSE).

