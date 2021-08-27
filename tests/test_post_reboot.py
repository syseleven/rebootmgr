import pytest
import socket
import threading
import time

from consul import Check
from rebootmgr.main import cli as rebootmgr
from rebootmgr.main import EXIT_CONSUL_CHECKS_FAILED, \
    EXIT_DID_NOT_REALLY_REBOOT
from unittest.mock import mock_open

WAIT_UNTIL_HEALTHY_SLEEP_TIME = 120

@pytest.fixture
def reboot_in_progress(consul_cluster):
    # Set up kv so that rebootmgr runs in post-reboot mode
    hostname = socket.gethostname().split(".")[0]
    try:
        consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", hostname)
        yield
    finally:
        consul_cluster[0].kv.delete("service/rebootmgr/reboot_in_progress")


def test_post_reboot_consul_checks_passing(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_in_progress, reboot_task, mocker):
    """
    Test if we succeed if consul checks are passing after reboot.
    """
    mocker.patch("time.sleep")
    mocked_run = mocker.patch("subprocess.run")

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert result.exit_code == 0


def test_post_reboot_consul_checks_failing(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_in_progress, reboot_task, mocker):
    """
    Test if we fail if consul checks are failing after reboot.
    """
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1ms"))  # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mocked_run = mocker.patch("subprocess.run")

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert result.exit_code == EXIT_CONSUL_CHECKS_FAILED


def test_post_reboot_wait_until_healthy_and_are_healthy(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_in_progress, reboot_task, mocker):
    """
    Test if we wait until consul checks are passing after reboot
    (when we don't actually need to wait)
    """
    mocker.patch("time.sleep")
    mocked_run = mocker.patch("subprocess.run")

    result = run_cli(rebootmgr, ["-v", "--post-reboot-wait-until-healthy"])

    mocked_run.assert_not_called()
    assert result.exit_code == 0


def test_post_reboot_wait_until_healthy(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_in_progress, reboot_task, mocker):
    """
    Test if we wait until consul checks are passing after reboot.
    """
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"],
                                             check=Check.ttl("1000s"))
    consul_cluster[1].agent.check.ttl_fail("service:A")

    sleep_counter = 2

    def fake_sleep(seconds):
        """
        While we're waiting for consul checks to start passing,
        we sleep 120 seconds at a time.
        Count how often this happens, and after a few times, we
        will set the failing check to passing.

        We ignore sleep requests for different amounts of time.
        """
        nonlocal sleep_counter
        if seconds == WAIT_UNTIL_HEALTHY_SLEEP_TIME:
            sleep_counter -= 1
            if sleep_counter <= 0:
                consul_cluster[1].agent.check.ttl_pass("service:A")

    mocker.patch("time.sleep", new=fake_sleep)
    mocked_run = mocker.patch("subprocess.run")

    result = run_cli(rebootmgr, ["-v", "--post-reboot-wait-until-healthy"])

    mocked_run.assert_not_called()
    assert sleep_counter == 0
    assert result.exit_code == 0


def test_post_reboot_phase_fails_without_tasks(
        run_cli, forward_consul_port, default_config, reboot_in_progress):
    result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Entering post reboot state" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_post_reboot_phase_succeeds_with_tasks(
        run_cli, forward_consul_port, default_config, reboot_in_progress,
        reboot_task):
    reboot_task("post_boot", "50_another_task.sh")

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0
    assert "50_another_task.sh" in result.output


def test_post_reboot_phase_fails_with_uptime(
        run_cli, forward_consul_port, default_config, reboot_in_progress,
        reboot_task, mocker):
    mocker.patch('rebootmgr.main.open', new=mock_open(read_data='99999999.9 99999999.9'))
    reboot_task("post_boot", "50_another_task.sh")

    result = run_cli(rebootmgr, ["-v", "--check-uptime"])

    assert "We are in post reboot state but uptime is higher then 2 hours." in result.output
    assert result.exit_code == EXIT_DID_NOT_REALLY_REBOOT


def test_post_reboot_succeeds_with_current_node_in_maintenance(
        run_cli, consul_cluster, reboot_in_progress, forward_consul_port,
        default_config, reboot_task, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])

    consul_cluster[0].agent.maintenance(True)

    result = run_cli(rebootmgr, ["-v"])

    assert "All consul checks passed." in result.output
    assert "Remove consul key service/rebootmgr/reboot_in_progress" in result.output

    assert result.exit_code == 0


def test_post_reboot_fails_with_other_node_in_maintenance(
        run_cli, consul_cluster, reboot_in_progress, forward_consul_port,
        default_config, reboot_task, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])

    consul_cluster[1].agent.maintenance(True)

    result = run_cli(rebootmgr, ["-v"])

    assert 'There were failed consul checks' in result.output
    assert '_node_maintenance on consul2' in result.output

    assert result.exit_code == EXIT_CONSUL_CHECKS_FAILED


def test_post_reboot_succeeds_with_other_node_in_maintenance_but_ignoring(
        run_cli, consul_cluster, reboot_in_progress, forward_consul_port,
        default_config, reboot_task, mocker):

    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr", "ignore_maintenance"])
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])

    consul_cluster[1].agent.maintenance(True)

    result = run_cli(rebootmgr, ["-v"])

    assert "All consul checks passed." in result.output
    assert "Remove consul key service/rebootmgr/reboot_in_progress" in result.output

    assert result.exit_code == 0


def test_post_reboot_wait_until_healthy_with_maintenance(
        run_cli, consul_cluster, forward_consul_port, default_config,
        reboot_in_progress, reboot_task, mocker):
    """
    Test if we wait until consul checks are passing after reboot.
    Since none of these services have the tag "ignore_maintenance", they count
    as broken when their node is in maintenance mode.
    """
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[2].agent.service.register("A", tags=["rebootmgr"])

    consul_cluster[1].agent.maintenance(True)

    sleep_counter = 2

    def fake_sleep(seconds):
        """
        While we're waiting for consul checks to start passing,
        we sleep 120 seconds at a time.
        Count how often this happens, and after a few times, we
        will remove the maintenance.

        We ignore sleep requests for different amounts of time.
        """
        nonlocal sleep_counter
        if seconds == WAIT_UNTIL_HEALTHY_SLEEP_TIME:
            sleep_counter -= 1
            if sleep_counter <= 0:
                consul_cluster[1].agent.maintenance(False)

    mocker.patch("time.sleep", new=fake_sleep)
    mocked_run = mocker.patch("subprocess.run")

    result = run_cli(rebootmgr, ["-v", "--post-reboot-wait-until-healthy"])

    mocked_run.assert_not_called()
    assert sleep_counter == 0
    assert 'There were failed consul checks' in result.output
    assert '_node_maintenance on consul2' in result.output
    assert "All consul checks passed." in result.output
    assert result.exit_code == 0
