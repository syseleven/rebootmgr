import socket

import pytest

from rebootmgr.main import cli as rebootmgr


@pytest.mark.xfail # TODO(sneubauer): Fix bug in rebootmgr
def test_reboot_task_timeout(run_click, forward_port, consul1, consul_kv, reboot_task, mocked_run, mocker):
    forward_port.consul(consul1)

    mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh", raise_timeout_expired=True)

    result = run_click(rebootmgr)

    assert "Could not finish task 00_some_task.sh in 2 hours" in result.output
    assert result.exit_code == 100



@pytest.mark.xfail # TODO(sneubauer): Fix bug in rebootmgr
def test_post_reboot_phase_task_timeout(run_click, forward_port, consul_kv, consul1, reboot_task):
    forward_port.consul(consul1)

    reboot_task("post_boot", "50_another_task.sh", raise_timeout_expired=True)

    mocker.patch("time.sleep")
    consul_kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_click(rebootmgr)

    assert "Could not finish task 50_another_task.sh in 2 hours" in result.output
    assert result.exit_code == 100
