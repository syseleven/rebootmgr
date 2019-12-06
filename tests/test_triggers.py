from rebootmgr.main import cli as rebootmgr

import datetime
import socket

def test_reboot_not_required(run_cli, forward_consul_port, default_config, reboot_task):
    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    assert "No reboot necessary" in result.output
    assert result.exit_code == 0


def test_reboot_required_because_consul(run_cli, forward_consul_port,
                                        consul_cluster, default_config,
                                        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/%s/reboot_required" % socket.gethostname(), "")

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_required_because_file(run_cli, forward_consul_port,
                                      default_config,
                                      reboot_task, mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocker.patch("os.path.isfile", new=lambda f: f == "/var/run/reboot-required")

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_on_holiday(run_cli, forward_consul_port,
                                      default_config,
                                      reboot_task, mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    today = datetime.date.today()
    mocker.patch("holidays.DE", new=lambda: [today])

    result = run_cli(rebootmgr, ["-v", "--check-holidays"])

    assert result.exit_code == 6


def test_reboot_on_not_a_holiday(run_cli, forward_consul_port,
                                      default_config,
                                      reboot_task, mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    mocker.patch("holidays.DE", new=lambda: [])

    result = run_cli(rebootmgr, ["-v", "--check-holidays"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_when_node_disabled(run_cli, forward_consul_port,
                                   consul_cluster,
                                   reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"disabled": true}')

    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert result.exit_code == 101


def test_reboot_when_node_disabled_but_ignored(run_cli, forward_consul_port,
                                   consul_cluster,
                                   reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"disabled": true}')

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-global-stop-flag"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_when_global_stop_flag(run_cli, forward_consul_port,
                                   consul_cluster, default_config,
                                   reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert result.exit_code == 102


def test_reboot_when_global_stop_flag_when_ignored(run_cli, forward_consul_port,
                                   consul_cluster, default_config,
                                   reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-global-stop-flag"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0
