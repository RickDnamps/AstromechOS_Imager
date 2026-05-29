# tests/unit/test_fake_boot_partition.py


def test_fake_boot_partition(fake_boot_partition):
    fake_boot_partition.mkdir("/a")
    fake_boot_partition.write_bytes("/a/x", b"hello")
    assert fake_boot_partition.read_bytes("/a/x") == b"hello"
    assert fake_boot_partition.exists("/a/x")
    assert not fake_boot_partition.exists("/missing")
