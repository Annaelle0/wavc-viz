"""Guards the donation addresses against typos and accidental edits."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDR = json.loads((ROOT / "docs" / "donate" / "addresses.json").read_text(encoding="utf-8"))

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def bech32_valid(addr: str) -> bool:
    addr = addr.lower()
    hrp, _, data = addr.rpartition("1")
    vals = [_CHARSET.find(c) for c in data]
    if not hrp or -1 in vals:
        return False
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    return _polymod(expanded + vals) == 1  # witness v0 (bech32)


def base58_len(addr: str) -> int:
    n = 0
    for c in addr:
        n = n * 58 + _B58.index(c)
    return len(n.to_bytes((n.bit_length() + 7) // 8, "big"))


def test_address_formats_and_checksums():
    assert re.fullmatch(r"0x[0-9a-fA-F]{40}", ADDR["evm"])
    assert ADDR["btc"].startswith("bc1q") and bech32_valid(ADDR["btc"])
    assert ADDR["ltc"].startswith("ltc1q") and bech32_valid(ADDR["ltc"])
    assert base58_len(ADDR["sol"]) == 32


def test_readme_lists_exactly_the_stored_addresses():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for addr in ADDR.values():
        assert f"`{addr}`" in readme
    # no other crypto-looking address sneaked into the README
    found = set(re.findall(r"`(0x[0-9a-fA-F]{40}|bc1[a-z0-9]{20,}|ltc1[a-z0-9]{20,})`", readme))
    assert found <= set(ADDR.values())


def test_qr_images_exist():
    for key in ADDR:
        assert (ROOT / "docs" / "donate" / f"{key}.png").stat().st_size > 500
