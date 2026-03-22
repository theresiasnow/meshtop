from pathlib import Path
from typing import Literal

import tomllib
from pydantic import BaseModel


class LoraSourceConfig(BaseModel):
    broker: str = "eu1.cloud.thethings.network"
    port: int = 1883
    username: str = ""
    password: str = ""
    topic: str = "v3/+/devices/+/up"


class SourceConfig(BaseModel):
    type: Literal["serial", "lora"] = "serial"
    port: str = "COM3"
    baud: int = 9600
    lora: LoraSourceConfig = LoraSourceConfig()


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
