"""Shared physical constants (audit WP9: 512 was defined in three modules)."""

#: Logical sector size of SD cards / the raw device I/O granularity.
#: Every offset/length passed to the raw writers must be a multiple of this.
SECTOR_SIZE = 512
