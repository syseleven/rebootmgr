import socket

from rebootmgr.main import cli as rebootmgr


def test_reboot_fails_without_tasks(run_cli, forward_consul_port):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Executing pre reboot tasks" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_reboot_success_with_tasks(run_cli, forward_consul_port, reboot_task, mock_subprocess_run, mocker):
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


def test_reboot_fail(run_cli, forward_consul_port, reboot_task, mock_subprocess_run, mocker):
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


def test_reboot_fails_if_another_reboot_is_in_progress(run_cli, forward_consul_port, consul_cluster):
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", "some_hostname")

    result = run_cli(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == 4


def test_post_reboot_phase_fails_without_tasks(run_cli, forward_consul_port, consul_cluster):
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Entering post reboot state" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_post_reboot_phase_success_with_tasks(run_cli, forward_consul_port, consul_cluster, reboot_task):
    reboot_task("post_boot", "50_another_task.sh")

    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0
    assert "50_another_task.sh" in result.output
