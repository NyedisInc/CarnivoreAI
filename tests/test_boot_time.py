
from src.core.boot_time import (
    BOOT_CANNOT_DETERMINE,
    BOOT_MEASURED,
    CHANGE_CANNOT_DETERMINE,
    CHANGE_FIRST_RECORD,
    CHANGE_REBOOTED,
    CHANGE_SAME_BOOT,
    BootTime,
    compare_boots,
    parse_kern_boottime,
    parse_proc_stat_btime,
    read_boot_time,
)


def test_parses_the_real_sysctl_shape():
    text = "{ sec = 1787980124, usec = 404857 } Thu Sep  3 09:48:44 2026\n"
    assert parse_kern_boottime(text) == 1787980124


def test_parses_proc_stat_btime():
    assert parse_proc_stat_btime("cpu  1 2 3\nbtime 1700000000\nprocesses 9\n") == 1700000000


def test_garbage_parses_to_none():
    assert parse_kern_boottime("nope") is None
    assert parse_proc_stat_btime("") is None


def test_a_moved_boot_time_is_a_reboot():
    assert compare_boots(1000, BootTime(BOOT_MEASURED, 9000, "kern.boottime")) == CHANGE_REBOOTED


def test_rounding_is_not_a_reboot():
    assert compare_boots(1000, BootTime(BOOT_MEASURED, 1001, "proc_stat")) == CHANGE_SAME_BOOT


def test_an_unmeasurable_boot_time_never_claims_a_reboot():
    unmeasured = BootTime(BOOT_CANNOT_DETERMINE)
    assert compare_boots(1000, unmeasured) == CHANGE_CANNOT_DETERMINE
    assert compare_boots(None, unmeasured) == CHANGE_CANNOT_DETERMINE


def test_nothing_recorded_is_a_first_record_not_a_reboot():
    assert compare_boots(None, BootTime(BOOT_MEASURED, 5, "kern.boottime")) == CHANGE_FIRST_RECORD


def test_the_real_probe_answers_on_this_platform():
    reading = read_boot_time()
    assert reading.outcome in (BOOT_MEASURED, BOOT_CANNOT_DETERMINE)
    if reading.measured:
        assert reading.epoch > 1_000_000_000
