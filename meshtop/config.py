import base64
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

# Meshtastic uses a 1-byte shorthand PSK "AQ==" (0x01) for the primary channel.
# The firmware expands this to the well-known 128-bit default key below.
# Users can paste PSKs directly from the Meshtastic app (AQ==, or a full base64 key).
_DEFAULT_PSK = "AQ=="
_EXPANDED_DEFAULT_KEY = bytes.fromhex("d4f1bb3a202907 59f0bcffabcf4e4df6".replace(" ", ""))


def expand_psk(psk_b64: str) -> bytes:
    """Expand a Meshtastic base64 PSK to raw AES key bytes.

    Valid input lengths (decoded):
      0  — no encryption (returns empty bytes)
      1  — shorthand: 0x01 expands to the 128-bit Meshtastic default key
      16 — AES-128 key, used as-is
      32 — AES-256 key, used as-is
    """
    if not psk_b64:
        return b""
    raw = base64.b64decode(psk_b64)
    if len(raw) == 0:
        return b""
    if len(raw) == 1:
        if raw[0] == 0x01:
            return _EXPANDED_DEFAULT_KEY
        raise ValueError(f"single-byte PSK must be 0x01 (got {raw[0]:#04x})")
    if len(raw) in (16, 32):
        return raw
    raise ValueError(
        f"PSK must decode to 0, 1, 16 (AES-128), or 32 (AES-256) bytes; got {len(raw)}"
    )


def _validate_psk(v: str) -> str:
    """Validate a base64 PSK field (raises ValueError on bad input)."""
    if not v:
        return v
    try:
        expand_psk(v)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("key must be valid base64") from exc
    return v


class ChannelConfig(BaseModel):
    enabled: bool = True
    encrypted: bool = False   # True = decrypt with key below
    key: str = ""             # base64 PSK — 1 byte shorthand, 16 (AES-128), or 32 (AES-256) bytes

    @field_validator("key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        return _validate_psk(v)


class LoraSourceConfig(BaseModel):
    broker: str = "mqtt.meshtastic.org"
    port: int = 1883
    username: str = "meshdev"
    password: str = "large4cats"
    topic: str = "msh/EU_868/SE/#"
    node_id: str = ""                        # e.g. "!7a78e5e3" — filter to own node only
    # Primary channel (index 0) has no user-assigned name; uses this predetermined PSK.
    # "AQ==" is the Meshtastic shorthand for the default 128-bit key (as shown in the app).
    primary_key: str = _DEFAULT_PSK          # base64 PSK — 1, 16, or 32 bytes
    channels: dict[str, ChannelConfig] = {}  # named secondary channels (index 1+) → config
    # Meshtastic TCP server for sending (e.g. "192.168.1.100")
    device_host: str = ""

    @field_validator("primary_key")
    @classmethod
    def _check_primary_key(cls, v: str) -> str:
        return _validate_psk(v)


class BleSourceConfig(BaseModel):
    device: str = ""   # device name or BLE address; empty = auto-discover first found


class TcpSourceConfig(BaseModel):
    host: str = ""     # IP or hostname of the Meshtastic device
    port: int = 4403   # default Meshtastic TCP port


class SourceConfig(BaseModel):
    type: Literal["serial", "lora", "ble", "tcp", "none"] = "none"
    port: str = "COM3"
    baud: int = 9600
    lora: LoraSourceConfig = LoraSourceConfig()
    ble: BleSourceConfig = BleSourceConfig()
    tcp: TcpSourceConfig = TcpSourceConfig()


class NmeaServerConfig(BaseModel):
    enabled: bool = True
    port: int = 10110


class AprsConfig(BaseModel):
    enabled: bool = False
    callsign: str = ""
    passcode: int = 0
    server: str = "rotate.aprs2.net"
    port: int = 14580
    interval: int = 60
    comment: str = "meshtop"


class GpsdConfig(BaseModel):
    enabled: bool = True
    port: int = 2947


class RigtopConfig(BaseModel):
    enabled: bool = False
    port: int = 10111


class Config(BaseModel):
    source: SourceConfig = SourceConfig()
    nmea_server: NmeaServerConfig = NmeaServerConfig()
    aprs: AprsConfig = AprsConfig()
    gpsd: GpsdConfig = GpsdConfig()
    rigtop: RigtopConfig = RigtopConfig()


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        data = tomllib.load(f)
    return Config.model_validate(data)


def save_config(cfg: Config, path: Path) -> None:
    import tomli_w
    with path.open("wb") as f:
        tomli_w.dump(cfg.model_dump(), f)
