# © 2026 Andy217Ace
"""Watchdog: 3 consecutive failed checks -> exactly one restart; a valid answer resets the
count; at most one restart per RESTART_COOLDOWN_S (fake clock)."""
import pytest

from app.watchdog import RESTART_COOLDOWN_S, THRESHOLD, Watchdog


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _dog(results, clock=None):
    """Watchdog whose check returns `results` in order; restarts are recorded."""
    seq = iter(results)
    restarts = []
    clock = clock or Clock()
    dog = Watchdog(check=lambda: next(seq), on_fail=lambda: restarts.append(clock()),
                   interval_s=60, clock=clock)
    return dog, restarts, clock


def test_constants_match_the_spec():
    assert THRESHOLD == 3
    assert RESTART_COOLDOWN_S == 600


def test_three_consecutive_failures_restart_exactly_once():
    dog, restarts, _ = _dog([False, False, False, False])
    assert [dog.tick() for _ in range(3)] == ["fail", "fail", "restart"]
    assert len(restarts) == 1


def test_valid_answer_resets_the_count():
    dog, restarts, _ = _dog([False, False, True, False, False])
    for _ in range(5):
        dog.tick()
    assert restarts == []  # 2 + reset + 2 never reaches 3


def test_failures_after_a_reset_count_from_zero():
    dog, restarts, _ = _dog([False, False, True, False, False, False])
    for _ in range(6):
        dog.tick()
    assert len(restarts) == 1


def test_exception_in_check_counts_as_a_failure():
    def boom():
        raise OSError("connection refused")

    restarts = []
    dog = Watchdog(check=boom, on_fail=lambda: restarts.append(1), interval_s=60,
                   clock=Clock())
    assert [dog.tick() for _ in range(3)] == ["fail", "fail", "restart"]
    assert restarts == [1]


def test_at_most_one_restart_per_cooldown_fake_clock():
    clock = Clock(1000.0)
    dog, restarts, _ = _dog([False] * 9, clock)
    assert [dog.tick() for _ in range(3)] == ["fail", "fail", "restart"]
    clock.t += RESTART_COOLDOWN_S - 1  # still inside the cooldown
    assert [dog.tick() for _ in range(3)] == ["fail", "fail", "throttled"]
    assert len(restarts) == 1
    clock.t += 1  # cooldown over, measured from the first restart
    assert [dog.tick() for _ in range(3)] == ["fail", "fail", "restart"]
    assert len(restarts) == 2


def test_no_restart_while_checks_pass():
    dog, restarts, _ = _dog([True] * 20)
    assert {dog.tick() for _ in range(20)} == {"ok"}
    assert restarts == []


def test_state_round_trip_keeps_count_and_cooldown():
    """The timer runs one check per process: the count and the last restart persist."""
    clock = Clock(1000.0)
    dog, _, _ = _dog([False, False], clock)
    dog.tick()
    dog.tick()
    saved = dog.state()
    assert saved == {"failures": 2, "last_restart": None}

    seq = iter([False])
    restarts = []
    again = Watchdog(check=lambda: next(seq), on_fail=lambda: restarts.append(1),
                     interval_s=60, clock=clock, state=saved)
    assert again.tick() == "restart"
    assert again.state()["last_restart"] == 1000.0
    assert restarts == [1]


@pytest.mark.parametrize("bad", [None, "x", {"failures": "a"}])
def test_corrupt_state_starts_clean(bad):
    dog = Watchdog(check=lambda: True, on_fail=lambda: None, interval_s=60,
                   clock=Clock(), state=bad)
    assert dog.state() == {"failures": 0, "last_restart": None}
