"""Sanity test for FakePlatformIO fixture."""


def test_fake_platform_io_basic(fake_platform_io):
    fake_platform_io.add_drive(2, size=1024 * 1024)
    drives = fake_platform_io.enumerate_removable_drives()
    assert len(drives) == 1
    assert drives[0].physical_drive_id == 2
    dev = fake_platform_io.open_raw_device(2)
    dev.write(0, b"hello")
    assert dev.read(0, 5) == b"hello"
    dev.close()
