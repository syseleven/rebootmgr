import socket

from rebootmgr.main import cli as rebootmgr


def test_chat_escalation_on_task_failure(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mocker):
    """A failing pre-boot task fires a chat_escalation consul event."""
    mocker.patch("time.sleep")
    mocker.patch("subprocess.run")
    reboot_task("pre_boot", "00_some_task.sh", exit_code=1)
    mocked_fire = mocker.patch("consul.Consul.Event.fire")

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 100
    mocked_fire.assert_called_once()
    assert mocked_fire.call_args[0][0] == "chat_escalation"
    assert "failed with return code 1" in mocked_fire.call_args[0][1]


def test_chat_escalation_on_task_timeout(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mocker):
    """A timed-out pre-boot task fires a chat_escalation consul event."""
    mocker.patch("time.sleep")
    mocker.patch("subprocess.run")
    reboot_task("pre_boot", "00_some_task.sh", raise_timeout_expired=True)
    mocked_fire = mocker.patch("consul.Consul.Event.fire")

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 100
    mocked_fire.assert_called_once()
    assert mocked_fire.call_args[0][0] == "chat_escalation"
    assert "Could not finish task" in mocked_fire.call_args[0][1]


def test_chat_escalation_includes_group(
        run_cli, forward_consul_port, consul_cluster, reboot_task, mocker):
    """Chat escalation message includes the group name when configured."""
    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put(
        f"service/rebootmgr/nodes/{hostname}/config",
        '{"enabled": true, "group": "compute"}')
    mocker.patch("time.sleep")
    mocker.patch("subprocess.run")
    reboot_task("pre_boot", "00_some_task.sh", exit_code=1)
    mocked_fire = mocker.patch("consul.Consul.Event.fire")

    result = run_cli(rebootmgr, ["-v", "--group", "compute"])

    assert result.exit_code == 100
    mocked_fire.assert_called_once()
    body = mocked_fire.call_args[0][1]
    assert "(compute)" in body
    assert f"({hostname})" in body
    consul_cluster[0].kv.delete("service/rebootmgr", recurse=True)


def test_chat_escalation_failure_does_not_block(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mocker):
    """If firing the consul event fails, the task failure still proceeds normally."""
    mocker.patch("time.sleep")
    mocker.patch("subprocess.run")
    reboot_task("pre_boot", "00_some_task.sh", exit_code=1)
    mocker.patch("consul.Consul.Event.fire", side_effect=Exception("connection refused"))

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 100
    assert "Failed to fire chat_escalation event" in result.output
