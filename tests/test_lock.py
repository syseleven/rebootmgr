from unittest.mock import PropertyMock

from rebootmgr.main import cli as rebootmgr
from consul_lib import Lock


def test_consul_lock_fails(
        run_cli, forward_consul_port, consul_cluster, default_config):
    with Lock(consul_cluster[0], "service/rebootmgr/lock"):
        result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

        assert "Could not get consul lock. Exit" in result.output
        assert result.exit_code == 4


def test_consul_lock_fails_later(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    # Lock.acquired is called only once, after the sleep period.
    mocker.patch("consul_lib.lock.Lock.acquired",
                 new_callable=PropertyMock,
                 return_value=False)

    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Lost consul lock. Exit" in result.output
    mocked_sleep.assert_any_call(130)
    assert result.exit_code == 5
