import time

from rebootmgr.main import cli as rebootmgr
from consul import Check

from pathlib import Path
from types import SimpleNamespace


def test_reboot_succeeds_with_failing_checks_if_whitelisted(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')

    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mocker.patch("subprocess.Popen")
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
    mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-failed-checks"])

    assert result.exit_code == 0
    assert mocked_run.call_count == 1


def test_reboot_succeeds_with_failing_checks_if_local_ignored(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])

    mocker.patch("time.sleep")
    mocker.patch("subprocess.Popen")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    def break_consul_service():
        """ Break consul service A on localhost as soon as "open" is called. """
        consul_cluster[0].agent.service.deregister("A")
        consul_cluster[0].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms"))
        time.sleep(0.01)
        import pprint
        pprint.pp(consul_cluster[0].health.service('A'))

    opener = mocker.mock_open(read_data='A')
    def mocked_open(self, *args, **kwargs):
        break_consul_service()
        return opener(self, *args, **kwargs)

    mocker.patch.object(Path, "unlink")
    mocker.patch.object(Path, "is_file", return_value=True)
    mocker.patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1))
    mocker.patch.object(Path, "open", mocked_open)
    result = run_cli(rebootmgr, ["-v"])

    assert False
    assert result.exit_code == 0


def test_reboot_fails_with_remote_failing_checks_if_local_ignored(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])

    mocker.patch("time.sleep")
    mocker.patch("subprocess.Popen")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    def break_consul_service():
        """ Break consul service A on the other node as soon as "open" is called. """
        consul_cluster[1].agent.service.deregister("A")
        consul_cluster[1].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms"))
        time.sleep(0.01)

    opener = mocker.mock_open(read_data='A')
    def mocked_open(self, *args, **kwargs):
        break_consul_service()
        return opener(self, *args, **kwargs)

    mocker.patch.object(Path, "unlink")
    mocker.patch.object(Path, "is_file", return_value=True)
    mocker.patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1))
    mocker.patch.object(Path, "open", mocked_open)
    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2


def test_reboot_fails_with_failing_checks(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mocker.patch("subprocess.Popen")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2


def test_reboot_fails_with_failing_consul_cluster(
        run_cli, forward_consul_port, default_config,
        reboot_task, mock_subprocess_run, mocker):
    # mocker.patch("time.sleep")
    mocker.patch("subprocess.Popen")
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
    mocker.patch("subprocess.Popen")
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
    mocker.patch("subprocess.Popen")
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

