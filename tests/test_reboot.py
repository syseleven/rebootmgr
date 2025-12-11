import socket

from rebootmgr.main import cli as rebootmgr
from rebootmgr.main import (
    EXIT_CONSUL_LOCK_FAILED,
    EXIT_CONSUL_CHECKS_FAILED,
    EXIT_CONFIGURATION_IS_MISSING,
)


def test_reboot_fails_without_config(run_cli, forward_consul_port):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Configuration data missing" in result.output
    assert "Executing pre reboot tasks" not in result.output
    assert result.exit_code == EXIT_CONFIGURATION_IS_MISSING


def test_reboot_fails_without_tasks(run_cli, forward_consul_port, default_config):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Executing pre reboot tasks" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_reboot_succeeds_with_tasks(
    run_cli,
    forward_consul_port,
    consul_cluster,
    default_config,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
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


def test_dryrun_reboot_succeeds_with_tasks(
    run_cli,
    forward_consul_port,
    consul_cluster,
    default_config,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_popen = reboot_task("pre_boot", "00_some_task.sh")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-vv", "--dryrun"])

    assert "00_some_task.sh" in result.output
    assert "service/rebootmgr/reboot_in_progress" in result.output
    assert result.exit_code == 0

    # shutdown must not be called
    mocked_run.assert_not_called()
    # task should be called
    assert mocked_popen.call_count == 1
    args, kwargs = mocked_popen.call_args
    assert args[0] == "/etc/rebootmgr/pre_boot_tasks/00_some_task.sh"
    assert "env" in kwargs
    assert "REBOOTMGR_DRY_RUN" in kwargs["env"]
    assert kwargs["env"]["REBOOTMGR_DRY_RUN"] == "1"
    # In particular, 'shutdown' is not called

    # We want rebootmgr to sleep for 2 minutes after running the pre boot tasks,
    # so that we can notice when the tasks broke some consul checks.
    mocked_sleep.assert_any_call(130)

    # Check that it does not set the reboot_in_progress flag
    _, data = consul_cluster[0].kv.get("service/rebootmgr/reboot_in_progress")
    assert not data


def test_reboot_fail(
    run_cli,
    forward_consul_port,
    default_config,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
    mocked_sleep = mocker.patch("time.sleep")

    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(
        ["shutdown", "-r", "+1"], side_effect=Exception("Failed to run reboot command")
    )

    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert result.exit_code == 1

    mocked_popen.assert_not_called()
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)

    # We want rebootmgr to sleep for 2 minutes after running the pre boot tasks,
    # so that we can notice when the tasks broke some consul checks.
    mocked_sleep.assert_any_call(130)


def test_reboot_fails_if_another_reboot_is_in_progress(
    run_cli, forward_consul_port, default_config, consul_cluster
):
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", "some_hostname")

    result = run_cli(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == EXIT_CONSUL_LOCK_FAILED


def test_reboot_succeeds_if_this_node_is_in_maintenance(
    run_cli,
    forward_consul_port,
    default_config,
    consul_cluster,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[0].agent.maintenance(True)

    mocker.patch("time.sleep")
    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_popen.assert_not_called()
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert result.exit_code == 0


def test_reboot_fails_if_another_node_is_in_maintenance(
    run_cli,
    forward_consul_port,
    default_config,
    consul_cluster,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.maintenance(True)

    mocker.patch("time.sleep")
    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_popen.assert_not_called()
    mocked_run.assert_not_called()
    assert "There were failed consul checks" in result.output
    assert "_node_maintenance on consul2" in result.output

    assert result.exit_code == EXIT_CONSUL_CHECKS_FAILED


def test_reboot_succeeds_if_another_node_is_in_maintenance_but_ignoring(
    run_cli,
    forward_consul_port,
    default_config,
    consul_cluster,
    reboot_task,
    mock_subprocess_run,
    mocker,
):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register(
        "A", tags=["rebootmgr", "ignore_maintenance"]
    )
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.maintenance(True)

    mocker.patch("time.sleep")
    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_popen.assert_not_called()
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert result.exit_code == 0
