import time

from rebootmgr.main import cli as rebootmgr
from consul import Check


def test_reboot_succeeds_with_failing_checks_if_whitelisted(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')

    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_reboot_succeeds_with_failing_checks_if_ignored(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-failed-checks"])

    assert result.exit_code == 0
    assert mocked_run.call_count == 1


def test_reboot_fails_with_failing_checks(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2


def test_reboot_fails_with_failing_consul_cluster(
        run_cli, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    # mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    def newmembers(self):
        return [
            {'Status': 1, 'Name': 'consul1'},
            {'Status': 0, 'Name': 'consul2'},
        ]

    mocker.patch("consul.base.Consul.Agent.members", new=newmembers)

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 3


def test_reboot_succeeds_with_failing_consul_cluster_if_whitelisted(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')
    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    def newmembers(self):
        return [
            {'Status': 1, 'Name': 'consul1'},
            {'Status': 0, 'Name': 'consul2'},
        ]

    mocker.patch("consul.base.Consul.Agent.members", new=newmembers)

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_reboot_succeeds_with_failing_consul_cluster_if_ignored(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    def newmembers(self):
        return [
            {'Status': 1, 'Name': 'consul1'},
            {'Status': 0, 'Name': 'consul2'},
        ]

    mocker.patch("consul.base.Consul.Agent.members", new=newmembers)

    result = run_cli(rebootmgr, ["-v", "--ignore-failed-checks"])

    assert result.exit_code == 0
    assert mocked_run.call_count == 1


# TODO(oseibert): Test cases where consul service checks succeed/fail after the
#  (2 * 60) + 10 seconds sleeping time, when they are done the second time.
