import json
import socket

from rebootmgr.main import cli as rebootmgr


def test_reboot_task_timeout(run_cli, consul_cluster, forward_consul_port, default_config, reboot_task, mocker):
    mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh", raise_timeout_expired=True)

    result = run_cli(rebootmgr)

    assert "Could not finish task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh in 120 minutes" in result.output
    assert result.exit_code == 100

    # TODO(oseibert): check that shutdown is NOT called.


def test_reboot_preboot_task_fails(run_cli, consul_cluster, forward_consul_port, default_config, reboot_task, mocker):
    mocker.patch("time.sleep")
    reboot_task("pre_boot", "00_some_task.sh", exit_code=1)

    result = run_cli(rebootmgr)

    assert "Task /etc/rebootmgr/pre_boot_tasks/00_some_task.sh failed with return code 1" in result.output
    assert result.exit_code == 100

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(socket.gethostname()))
    assert json.loads(data["Value"].decode()) == {
        "enabled": True,
    }
    # TODO(oseibert): check that shutdown is NOT called.


def test_post_reboot_phase_task_timeout(run_cli, consul_cluster, forward_consul_port, default_config, reboot_task, mocker):
    reboot_task("post_boot", "50_another_task.sh", raise_timeout_expired=True)

    mocker.patch("time.sleep")
    consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", socket.gethostname())

    result = run_cli(rebootmgr)

    assert "Could not finish task /etc/rebootmgr/post_boot_tasks/50_another_task.sh in 120 minutes" in result.output
    assert result.exit_code == 100

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(socket.gethostname()))
    assert json.loads(data["Value"].decode()) == {
        "enabled": False,
        "message": "Could not finish task /etc/rebootmgr/post_boot_tasks/50_another_task.sh in 120 minutes"
    }
