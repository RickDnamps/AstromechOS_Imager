"""Session-scoped hotspot SSID — FlashViewModel.startSession() contract.

Sequential Deployment Assistant: the bootstrap SSID is generated ONCE
on Screen 01 Landing and reused for both flash cycles so master/slave
boot into the SAME wlan0 rendezvous. This module pins:
  * sessionSsid is empty until startSession() runs.
  * startSession() produces an ``Astromech-XXXX`` SSID.
  * startSession() is idempotent — the SSID is stable across calls.
  * sessionSsidChanged fires exactly once on the first call.

The QObject needs a Qt platform plugin to instantiate, so we replicate
the offscreen-Qt pytestmark guard used elsewhere in the suite.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable session-ssid tests",
)


def _fake_wizard_state(*, hotspot_password: str = "") -> SimpleNamespace:
    """Minimal wizard_state surface FlashViewModel.startSession reads."""
    return SimpleNamespace(hotspotPassword=hotspot_password)


def test_session_ssid_empty_until_started():
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state())
    assert fvm.sessionSsid == ""


def test_startSession_generates_ssid():
    """SSID format follows ``generate_hotspot_bootstrap``: ``Astromech-XXXX``."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    assert fvm.sessionSsid.startswith("Astromech-")


def test_startSession_idempotent():
    """Re-calling must NOT mint a fresh SSID — both cards in the session
    rely on the original to bake into /boot/astromech_init.cfg."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    first = fvm.sessionSsid
    fvm.startSession()
    assert fvm.sessionSsid == first


def test_session_ssid_signal_emitted():
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    received: list[str] = []
    fvm.sessionSsidChanged.connect(lambda v: received.append(v))
    fvm.startSession()
    assert len(received) == 1
    assert received[0].startswith("Astromech-")


def test_startSession_signal_not_emitted_on_idempotent_call():
    """Re-call must NOT spam sessionSsidChanged — UI bindings shouldn't
    flicker."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    received: list[str] = []
    fvm.sessionSsidChanged.connect(lambda v: received.append(v))
    fvm.startSession()
    assert received == []


def test_startSession_falls_back_to_astropass_when_psk_too_short():
    """An operator who hasn't visited Step 2 Config yet has hotspotPassword
    == "". The fallback to "astropass" keeps generate_hotspot_bootstrap
    happy (WPA2-PSK ≥ 8 chars)."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password=""))
    fvm.startSession()
    # SSID generated successfully → fallback worked.
    assert fvm.sessionSsid.startswith("Astromech-")


def test_startSession_uses_operator_psk_when_long_enough():
    """When Step 2 Config has populated a valid PSK, that one wins (the
    SSID is random; the PSK comes from the operator)."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="mySecretPSK!"))
    fvm.startSession()
    # We don't expose the PSK directly via QML for security; verify
    # internal storage to lock the contract.
    assert fvm._session_hotspot is not None
    assert fvm._session_hotspot.password == "mySecretPSK!"


# ── endSession() — audit bugs C3 + H1 ────────────────────────────────


def test_endSession_clears_session_hotspot():
    """startSession() then endSession() must zero out the SSID so the
    next sequential deployment mints a fresh one."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    assert fvm.sessionSsid.startswith("Astromech-")
    fvm.endSession()
    assert fvm.sessionSsid == ""
    assert fvm._session_hotspot is None


def test_endSession_emits_signal():
    """sessionSsidChanged fires with the empty string on session end so
    UI bindings drop the SSID preview rectangle."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    received: list[str] = []
    fvm.sessionSsidChanged.connect(lambda v: received.append(v))
    fvm.endSession()
    assert received == [""]


def test_endSession_then_startSession_mints_fresh_ssid():
    """End-to-end: a 'FLASH ANOTHER' cycle must produce an SSID that
    is independent of the previous run's SSID."""
    from astromechos_imager.ui.flash_view_model import FlashViewModel
    fvm = FlashViewModel(_fake_wizard_state(hotspot_password="astropass"))
    fvm.startSession()
    first_ssid = fvm.sessionSsid
    fvm.endSession()
    fvm.startSession()
    second_ssid = fvm.sessionSsid
    assert second_ssid.startswith("Astromech-")
    # Cryptographic randomness — collision probability is 1/65536, so
    # this is effectively a paternity check.
    assert second_ssid != first_ssid
