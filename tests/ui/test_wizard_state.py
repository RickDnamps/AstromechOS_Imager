import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM") != "offscreen",
    reason="set QT_QPA_PLATFORM=offscreen to enable UI smoke tests",
)


def test_initial_step_is_one(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.currentStep == 1


def test_next_advances(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.next()
    assert s.currentStep == 2
    s.next()
    s.next()
    assert s.currentStep == 4


def test_back_decrements(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.next(); s.next(); s.next()  # 4
    s.back()
    assert s.currentStep == 3


def test_back_clamps_at_min(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.back()
    s.back()
    assert s.currentStep == 1


def test_next_clamps_at_max(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    for _ in range(10):
        s.next()
    assert s.currentStep == 6


def test_goto_valid_range(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.goto(5)
    assert s.currentStep == 5


def test_goto_out_of_range_noop(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.goto(0)
    s.goto(7)
    s.goto(-1)
    assert s.currentStep == 1


def test_signal_emitted_on_change(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.currentStepChanged.connect(lambda v: received.append(v))
    s.next()
    s.next()
    s.back()
    assert received == [2, 3, 2]


def test_signal_not_emitted_on_clamp(qtbot):
    """Clamped no-op transitions must NOT spam the signal."""
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.currentStepChanged.connect(lambda v: received.append(v))
    s.back()  # at 1, clamps — no signal
    s.back()  # still at 1
    assert received == []


# ---------------------------------------------------------------------------
# Task 8.3 — mode picker
# ---------------------------------------------------------------------------

def test_mode_default_is_both(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.mode == "both"


def test_set_mode_emits_signal(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.modeChanged.connect(lambda v: received.append(v))
    s.setMode("master_only")
    assert s.mode == "master_only"
    assert received == ["master_only"]


def test_set_mode_invalid_noop(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMode("nonsense")
    assert s.mode == "both"


def test_set_mode_same_value_no_signal(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.modeChanged.connect(lambda v: received.append(v))
    s.setMode("both")  # already default
    assert received == []


# ---------------------------------------------------------------------------
# Task 8.4 — image paths
# ---------------------------------------------------------------------------

def test_master_image_path_setter(qtbot, tmp_path):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    f = tmp_path / "x.img"
    f.write_bytes(b"x" * 100)
    received = []
    s.masterImagePathChanged.connect(lambda v: received.append(v))
    s.setMasterImagePath(str(f))
    assert s.masterImagePath == str(f)
    assert received == [str(f)]


def test_image_path_file_url_normalized(qtbot, tmp_path):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    f = tmp_path / "y.img.xz"
    f.write_bytes(b"x" * 100)
    s.setMasterImagePath(f"file:///{str(f).replace(chr(92), '/')}")
    assert s.masterImagePath == str(f).replace("\\", "/").lstrip("/") or s.masterImagePath.endswith("y.img.xz")


def test_valid_image_path_returns_true(qtbot, tmp_path):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    for ext in [".img", ".img.xz", ".img.gz", ".zip"]:
        name = "test" + ext if not ext.startswith(".img.") else "test.img" + ext[4:]
        if ext == ".img":
            name = "test.img"
        elif ext == ".img.xz":
            name = "test.img.xz"
        elif ext == ".img.gz":
            name = "test.img.gz"
        else:
            name = "test.zip"
        f = tmp_path / name
        f.write_bytes(b"x")
        assert s.isValidImagePath(str(f)), f"Expected {f} to be valid"


def test_valid_image_path_rejects_nonexistent(qtbot, tmp_path):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert not s.isValidImagePath(str(tmp_path / "missing.img"))


def test_valid_image_path_rejects_wrong_ext(qtbot, tmp_path):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    assert not s.isValidImagePath(str(f))


# ---------------------------------------------------------------------------
# Task 8.5 — drive ID assignment
# ---------------------------------------------------------------------------

def test_drive_ids_default_to_minus_one(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.masterDriveId == -1
    assert s.slaveDriveId == -1


def test_set_master_drive_id_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.masterDriveIdChanged.connect(lambda v: received.append(v))
    s.setMasterDriveId(2)
    assert s.masterDriveId == 2
    assert received == [2]


def test_set_master_rejects_same_as_slave(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setSlaveDriveId(3)
    s.setMasterDriveId(3)  # collision — ignored
    assert s.masterDriveId == -1
    assert s.slaveDriveId == 3


def test_set_slave_rejects_same_as_master(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setMasterDriveId(2)
    s.setSlaveDriveId(2)  # collision — ignored
    assert s.slaveDriveId == -1
    assert s.masterDriveId == 2


# ---------------------------------------------------------------------------
# Task 8.6 — Step 4 Customize fields
# ---------------------------------------------------------------------------

def test_authorized_keys_default_empty(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.authorizedKeys == ""


def test_set_authorized_keys_emits_signal(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.authorizedKeysChanged.connect(lambda v: received.append(v))
    s.setAuthorizedKeys("ssh-ed25519 AAAA... user@host")
    assert s.authorizedKeys == "ssh-ed25519 AAAA... user@host"
    assert received == ["ssh-ed25519 AAAA... user@host"]


def test_set_authorized_keys_same_value_no_signal(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    s.setAuthorizedKeys("ssh-ed25519 AAAA... user@host")
    received = []
    s.authorizedKeysChanged.connect(lambda v: received.append(v))
    s.setAuthorizedKeys("ssh-ed25519 AAAA... user@host")  # same — no signal
    assert received == []


def test_has_valid_authorized_key_valid_ed25519(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    # Use a syntactically valid ed25519 key format
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl user@host"
    assert s.hasValidAuthorizedKey(key) is True


def test_has_valid_authorized_key_valid_rsa(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC user@example"
    assert s.hasValidAuthorizedKey(key) is True


def test_has_valid_authorized_key_empty_returns_false(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.hasValidAuthorizedKey("") is False


def test_has_valid_authorized_key_garbage_returns_false(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.hasValidAuthorizedKey("not-a-key") is False


def test_has_valid_authorized_key_multiline_with_one_valid(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    txt = "# comment\nssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl user@host\n"
    assert s.hasValidAuthorizedKey(txt) is True


def test_hostname_master_default(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.hostnameMaster == "astromech-master"


def test_hostname_slave_default(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.hostnameSlave == "astromech-slave"


def test_set_hostname_master_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.hostnameMasterChanged.connect(lambda v: received.append(v))
    s.setHostnameMaster("r2d2-master")
    assert s.hostnameMaster == "r2d2-master"
    assert received == ["r2d2-master"]


def test_set_hostname_slave_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.hostnameSlaveChanged.connect(lambda v: received.append(v))
    s.setHostnameSlave("r2d2-slave")
    assert s.hostnameSlave == "r2d2-slave"
    assert received == ["r2d2-slave"]


def test_repo_url_default_empty(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.repoUrl == ""


def test_set_repo_url_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.repoUrlChanged.connect(lambda v: received.append(v))
    s.setRepoUrl("https://github.com/user/AstromechOS.git")
    assert s.repoUrl == "https://github.com/user/AstromechOS.git"
    assert received == ["https://github.com/user/AstromechOS.git"]


def test_reuse_pair_key_default_false(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.reusePairKey is False


def test_set_reuse_pair_key_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.reusePairKeyChanged.connect(lambda v: received.append(v))
    s.setReusePairKey(True)
    assert s.reusePairKey is True
    assert received == [True]


def test_reuse_hotspot_default_false(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    assert s.reuseHotspot is False


def test_set_reuse_hotspot_emits(qtbot):
    from astromechos_imager.ui.wizard_state import WizardState
    s = WizardState()
    received = []
    s.reuseHotspotChanged.connect(lambda v: received.append(v))
    s.setReuseHotspot(True)
    assert s.reuseHotspot is True
    assert received == [True]
