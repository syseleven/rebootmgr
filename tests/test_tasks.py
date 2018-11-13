import json
import socket

import pytest

from rebootmgr.main import cli as rebootmgr


@pytest.mark.xfail # TODO(sneubauer): Fix bug in rebootmgr
def test_reboot_task_timeout(run_cli, forward_port, consul_cluster, reboot_task, mocker):
    forward_port.consul(consul_cluster[0])

    mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh", raise_timeout_expired=True)

    result = run_cli(rebootmgr)

    assert "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 2 hours" in result.output
    assert result.exit_code == 100

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(socket.gethostname()))
    assert json.loads(data["Value"].decode()) == {
        "enabled": False,
        "message": "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 2 hours"
    }




def test_reboot_task_timeout_preexisting_config(run_cli, forward_port, consul_cluster, reboot_task, mocker):
    forward_port.consul(consul_cluster[0])

    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"test_preserved": true}')
    mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh", raise_timeout_expired=True)

    result = run_cli(rebootmgr)

    assert "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 2 hours" in result.output
    assert result.exit_code == 100

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(socket.gethostname()))
    assert json.loads(data["Value"].decode()) == {
        "test_preserved": True,
        "enabled": False,
        "message": "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 2 hours"
    }


@pytest.mark.xfail # TODO(sneubauer): Fix bug in rebootmgr
def test_post_reboot_phase_task_timeout(run_cli, forward_port, consul_cluster, reboot_task):
    forward_port.consul(consul_cluster[0])

    reboot_task("post_boot", "50_another_task.sh", raise_timeout_expired=True)

    mocker.patch("time.sleep")
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr)

    assert "Could not finish task /etc/rebootmgr/pre_boot_tasks/50_another_task.sh in 2 hours" in result.output
    assert result.exit_code == 100

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(socket.gethostname()))
    assert json.loads(data["Value"].decode()) == {
        "enabled": False,
        "message": "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 2 hours"
    }


