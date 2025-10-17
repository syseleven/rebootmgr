import socket

from rebootmgr.main import cli as rebootmgr


def test_reboot_fails_if_only_global_stop_flag(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    mocker.patch("time.sleep")
    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_popen.assert_not_called()
    mocked_run.assert_not_called()
    assert "Stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_fails_if_global_stop_flag_with_group_in_config(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")
    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true, "group": "consul" }')
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")
    mocker.patch("time.sleep")
    mocked_popen = mocker.patch("subprocess.Popen")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])
    mocked_popen.assert_not_called()
    mocked_run.assert_not_called()
    assert "Stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_fails_if_global_stop_flag_with_group_in_command(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true }')
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v", "--group", "consul"])
    assert "Stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_fails_if_not_global_stop_flag_and_correct_group_stop_flag_in_command(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true }')
    consul_cluster[0].kv.put("service/rebootmgr/consul_stop", "")
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v", "--group", "consul"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_fails_if_not_global_stop_flag_and_correct_group_stop_flag_in_config(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true, "group": "consul" }')
    consul_cluster[0].kv.put("service/rebootmgr/consul_stop", "")
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_succeeds_if_not_global_stop_flag_and_wrong_group_stop_flag_in_command(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true }')
    consul_cluster[0].kv.put("service/rebootmgr/wrong_stop", "")
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v", "--group", "consul"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Reboot now" in result.output
    assert result.exit_code == 0


def test_reboot_succeeds_if_not_global_stop_flag_and_wrong_group_stop_flag_in_config(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true, "group": "consul" }')
    consul_cluster[0].kv.put("service/rebootmgr/wrong_stop", "")
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Reboot now" in result.output
    assert result.exit_code == 0


def test_reboot_succeeds_if_not_global_stop_flag_not_group_stop_flag_in_command(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true }')
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v", "--group", "consul"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Reboot now" in result.output
    assert result.exit_code == 0


def test_reboot_succeeds_if_not_global_stop_flag_not_group_stop_flag_in_config(
        run_cli, forward_consul_port, consul_cluster,
        mock_subprocess_run, reboot_task, mocker):

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")

    hostname = socket.gethostname().split(".")[0]
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(hostname), '{ "enabled": true, "group": "consul" }')
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    result = run_cli(rebootmgr, ["-v", "--group", "consul"])
    assert "Looking up Global stop flag from: service/rebootmgr/stop" in result.output
    assert "Looking up stop flag from: /service/rebootmgr/consul_stop" in result.output
    assert "Reboot now" in result.output
    assert result.exit_code == 0
