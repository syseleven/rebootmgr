import socket

from rebootmgr.main import cli as rebootmgr
from unittest.mock import mock_open


def test_reboot_fails_without_config(run_cli, forward_consul_port):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Configuration data missing" in result.output
    assert "Executing pre reboot tasks" not in result.output
    assert result.exit_code == 104


def test_reboot_fails_without_tasks(run_cli, forward_consul_port, default_config):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Executing pre reboot tasks" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_reboot_success_with_tasks(run_cli, forward_consul_port, consul_cluster,
                                   default_config, reboot_task,
                                   mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert "00_some_task.sh" in result.output
    assert result.exit_code == 0

    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)

    # We want rebootmgr to sleep for 2 minutes after running the pre boot tasks,
    # so that we can notice when the tasks broke some consul checks.
    mocked_sleep.assert_any_call(130)

    # Check that it sets the reboot_in_progress flag
    _, data = consul_cluster[0].kv.get("service/rebootmgr/reboot_in_progress")
    assert data["Value"].decode() == socket.gethostname()


def test_dryrun_reboot_success_with_tasks(run_cli, forward_consul_port,
                                          consul_cluster, default_config,
                                          reboot_task, mock_subprocess_run,
                                          mocker):
    mocked_sleep = mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-vv", "--dryrun"])

    assert "00_some_task.sh" in result.output
    assert "in key service/rebootmgr/reboot_in_progress" in result.output
    assert result.exit_code == 0

    assert mocked_run.call_count == 1
    args, kwargs = mocked_run.call_args
    assert args[0] == "/etc/rebootmgr/pre_boot_tasks/00_some_task.sh"
    assert 'env' in kwargs
    assert 'REBOOTMGR_DRY_RUN' in kwargs['env']
    assert kwargs['env']['REBOOTMGR_DRY_RUN'] == "1"
    # In particular, 'shutdown' is not called

    # We want rebootmgr to sleep for 2 minutes after running the pre boot tasks,
    # so that we can notice when the tasks broke some consul checks.
    mocked_sleep.assert_any_call(130)

    # Check that it does not set the reboot_in_progress flag
    _, data = consul_cluster[0].kv.get("service/rebootmgr/reboot_in_progress")
    assert not data


def test_reboot_fail(run_cli, forward_consul_port, default_config, reboot_task, mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")

    mocked_run = mock_subprocess_run(
        ["shutdown", "-r", "+1"],
        side_effect=Exception("Failed to run reboot command"))

    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert result.exit_code == 1

    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)

    # We want rebootmgr to sleep for 2 minutes after running the pre boot tasks,
    # so that we can notice when the tasks broke some consul checks.
    mocked_sleep.assert_any_call(130)


def test_reboot_fails_if_another_reboot_is_in_progress(run_cli, forward_consul_port, default_config, consul_cluster):
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", "some_hostname")

    result = run_cli(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == 4


def test_post_reboot_phase_fails_without_tasks(run_cli, forward_consul_port, default_config, consul_cluster):
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Entering post reboot state" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_post_reboot_phase_success_with_tasks(run_cli, forward_consul_port, default_config, consul_cluster, reboot_task):
    reboot_task("post_boot", "50_another_task.sh")

    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0
    assert "50_another_task.sh" in result.output


def test_post_reboot_phase_failure_with_uptime(run_cli, forward_consul_port,
                                               default_config, consul_cluster,
                                               reboot_task, mocker):
    mocker.patch('rebootmgr.main.open', new=mock_open(read_data='99999999.9 99999999.9'))
    reboot_task("post_boot", "50_another_task.sh")

    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr, ["-v", "--check-uptime"])

    assert "We are in post reboot state but uptime is higher then 2 hours." in result.output
    assert result.exit_code == 103
