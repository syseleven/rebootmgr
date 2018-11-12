import socket

import pytest

from rebootmgr.main import cli as rebootmgr


def test_reboot_fails_without_tasks(run_click, forward_port, consul1):
    forward_port.consul(consul1)

    result = run_click(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Executing pre reboot tasks" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_reboot_success_with_tasks(run_click, forward_port, consul1, consul_kv, reboot_task, mocked_run, mocker):
    forward_port.consul(consul1)

    mocked_sleep = mocker.patch("time.sleep")

    reboot_task("pre_boot", "00_some_task.sh")

    result = run_click(rebootmgr, ["-v"])

    assert "00_some_task.sh" in result.output
    assert result.exit_code == 0

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)


def test_reboot_in_progress_other(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)

    consul_kv.put("service/rebootmgr/reboot_in_progress", "some_hostname")

    result = run_click(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == 4


def test_post_reboot_phase_fails_without_tasks(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)

    consul_kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_click(rebootmgr, ["-v"], catch_exceptions=True)

    assert "Entering post reboot state" in result.output
    assert result.exit_code == 1
    assert isinstance(result.exception, FileNotFoundError)


def test_post_reboot_phase_success_with_tasks(run_click, forward_port, consul_kv, consul1, reboot_task):
    forward_port.consul(consul1)

    reboot_task("post_boot", "50_another_task.sh")

    consul_kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_click(rebootmgr, ["-v"])

    assert result.exit_code == 0
    assert "50_another_task.sh" in result.output
