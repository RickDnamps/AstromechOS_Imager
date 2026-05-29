# tests/unit/test_cli_parse.py
import pytest
from astromechos_imager.cli.main import build_parser


def test_flash_subcommand_required():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_flash_master_only():
    args = build_parser().parse_args([
        "flash", "--master-image", "m.img", "--master-drive", "2",
        "--keys-file", "/tmp/id.pub",
    ])
    assert args.master_image == "m.img"
    assert args.master_drive == 2
    assert args.slave_image is None


def test_flash_both():
    args = build_parser().parse_args([
        "flash", "--master-image", "m.img.xz", "--master-drive", "2",
        "--slave-image", "s.img.xz", "--slave-drive", "3",
        "--keys-file", "/tmp/id.pub",
    ])
    assert args.master_drive == 2 and args.slave_drive == 3


def test_no_verify_flag():
    args = build_parser().parse_args([
        "flash", "--master-image", "m", "--master-drive", "2",
        "--keys-file", "k", "--no-verify",
    ])
    assert args.no_verify is True
