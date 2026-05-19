"""Tests for MessageBridge routing and loop prevention."""

import time

import pytest

from meshtop.bridge import MessageBridge
from meshtop.config import BridgeConfig
from meshtop.sources.meshtastic import TextMessage


class _FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_message(self, dest: str, text: str) -> None:
        self.sent.append((dest, text))


def _msg(source_type: str, text: str = "hello", from_id: str = "N0CALL") -> TextMessage:
    return TextMessage(from_id=from_id, to_id="N0BCK", text=text, source_type=source_type)


def test_mesh_to_aprs_disabled_by_default():
    aprs = _FakeSender()
    bridge = MessageBridge(BridgeConfig(), {"mesh": _FakeSender(), "aprs": aprs})
    bridge.route(_msg("mesh"))
    assert aprs.sent == []


def test_mesh_to_aprs_enabled():
    aprs = _FakeSender()
    cfg = BridgeConfig(mesh_to_aprs=True)
    bridge = MessageBridge(cfg, {"mesh": _FakeSender(), "aprs": aprs})
    bridge.route(_msg("mesh", text="test123"))
    assert len(aprs.sent) == 1
    assert aprs.sent[0][1] == "test123"


def test_aprs_to_mesh():
    mesh = _FakeSender()
    cfg = BridgeConfig(aprs_to_mesh=True)
    bridge = MessageBridge(cfg, {"mesh": mesh, "aprs": _FakeSender()})
    bridge.route(_msg("aprs", text="aprs_text"))
    assert len(mesh.sent) == 1
    assert mesh.sent[0][1] == "aprs_text"


def test_js8call_to_mesh():
    mesh = _FakeSender()
    cfg = BridgeConfig(js8call_to_mesh=True)
    bridge = MessageBridge(cfg, {"mesh": mesh, "js8call": _FakeSender()})
    bridge.route(_msg("js8call", text="js8_msg"))
    assert len(mesh.sent) == 1


def test_loop_prevention_same_minute():
    aprs = _FakeSender()
    cfg = BridgeConfig(mesh_to_aprs=True)
    bridge = MessageBridge(cfg, {"mesh": _FakeSender(), "aprs": aprs})
    msg = _msg("mesh", text="dup_msg")
    bridge.route(msg)
    bridge.route(msg)  # same message, same minute bucket
    assert len(aprs.sent) == 1  # second call dropped


def test_no_route_when_target_sender_missing():
    cfg = BridgeConfig(mesh_to_aprs=True)
    bridge = MessageBridge(cfg, {"mesh": _FakeSender()})  # no "aprs" sender
    bridge.route(_msg("mesh"))  # should not raise


def test_send_error_does_not_raise():
    class _BrokenSender:
        def send_message(self, dest, text):
            raise RuntimeError("send failed")

    cfg = BridgeConfig(mesh_to_aprs=True)
    bridge = MessageBridge(cfg, {"mesh": _FakeSender(), "aprs": _BrokenSender()})
    bridge.route(_msg("mesh"))  # must not raise


def test_mesh_to_js8call():
    js8 = _FakeSender()
    cfg = BridgeConfig(mesh_to_js8call=True)
    bridge = MessageBridge(cfg, {"mesh": _FakeSender(), "js8call": js8})
    bridge.route(_msg("mesh", text="to_js8"))
    assert len(js8.sent) == 1
    assert js8.sent[0][1] == "to_js8"
