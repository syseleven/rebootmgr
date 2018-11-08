import socket

import pytest

from rebootmgr.main import cli as rebootmgr


@pytest.mark.xfail()
def test_reboot_success_without_tasks(run_click, forward_port, consul1):
    forward_port.consul(consul1)

    result = run_click(rebootmgr, ["-v"])

    assert result.exit_code == 0


@pytest.mark.xfail()
def test_reboot_success_with_tasks(run_click, forward_port, consul1):
    forward_port.consul(consul1)

    # TODO(sneubauer): add tasks

    result = run_click(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_reboot_in_progress_other(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)

    consul_kv.put("service/rebootmgr/reboot_in_progress", "some_hostname")

    result = run_click(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == 4


@pytest.mark.xfail()
def test_post_reboot_phase_without_tasks(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)

    consul_kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_click(rebootmgr, ["-v"])

    assert "some_hostname" in result.output
    assert result.exit_code == 4


@pytest.mark.xfail()
def test_post_reboot_phase_with_tasks(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)

    # TODO(sneubauer): add tasks

    consul_kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_click(rebootmgr, ["-v"])

    assert result.exit_code == 0
