from rebootmgr.main import cli as rebootmgr

import datetime
import pytest
import socket


def test_reboot_not_required(run_cli, forward_consul_port, default_config, reboot_task):
    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    assert "No reboot necessary" in result.output
    assert result.exit_code == 0


def test_reboot_required_because_consul(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/%s/reboot_required" % socket.gethostname(), "")

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_required_because_consul_but_removed_after_sleep(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/%s/reboot_required" % socket.gethostname(), "")

    def remove_reboot_required(seconds):
        if seconds == 130:
            consul_cluster[0].kv.delete("service/rebootmgr/nodes/%s/reboot_required" % socket.gethostname())

    mocked_sleep = mocker.patch("time.sleep", side_effect=remove_reboot_required)
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_not_called()
    assert "No reboot necessary" in result.output
    assert result.exit_code == 0


def test_reboot_required_because_file(
        run_cli, forward_consul_port, default_config, reboot_task,
        mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocker.patch("os.path.isfile", new=lambda f: f == "/var/run/reboot-required")

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_required_because_file_but_removed_after_sleep(
        run_cli, forward_consul_port, default_config, reboot_task,
        mock_subprocess_run, mocker):
    reboot_required_file_is_present = True

    def remove_file(seconds):
        nonlocal reboot_required_file_is_present
        if seconds == 130:
            reboot_required_file_is_present = False

    def new_isfile(f):
        return reboot_required_file_is_present and \
               f == "/var/run/reboot-required"

    mocked_sleep = mocker.patch("time.sleep", side_effect=remove_file)
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocker.patch("os.path.isfile", new=new_isfile)

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_not_called()
    assert "No reboot necessary" in result.output
    assert result.exit_code == 0


def test_reboot_on_holiday(
        run_cli, forward_consul_port, default_config, reboot_task,
        mock_subprocess_run, mocker):
    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    mocker.patch("holidays.DE", new=lambda: [today, tomorrow])

    result = run_cli(rebootmgr, ["-v", "--check-holidays"])

    mocked_run.assert_not_called()
    assert "Refuse to run on holiday" in result.output
    assert result.exit_code == 6


def test_reboot_on_not_a_holiday(
        run_cli, forward_consul_port, default_config, reboot_task,
        mock_subprocess_run, mocker):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    mocker.patch("holidays.DE", new=lambda: [])

    result = run_cli(rebootmgr, ["-v", "--check-holidays"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_when_node_disabled(
        run_cli, forward_consul_port, consul_cluster, reboot_task,
        mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"disabled": true}')

    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert "Rebootmgr is disabled in consul config for this node" in result.output
    assert result.exit_code == 101


def test_reboot_when_node_disabled_but_ignored(
        run_cli, forward_consul_port, consul_cluster, reboot_task,
        mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"disabled": true}')

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-node-disabled"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0

# TODO(oseibert): Should a MISSING configuration also be ignored with --ignore-node-disabled?

# TODO(oseibert): Fix this bug.
@pytest.mark.xfail
def test_reboot_when_node_disabled_after_sleep(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    def set_configuration_disabled(seconds):
        if seconds == 130:
            consul_cluster[0].kv.put("service/rebootmgr/nodes/{}/config".format(socket.gethostname()), '{"disabled": true}')

    # When rebootmgr sleeps for 2 minutes, the stop flag will be set.
    mocked_sleep = mocker.patch("time.sleep", side_effect=set_configuration_disabled)
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_not_called()
    assert "Reboot now ..." in result.output
    assert result.exit_code == 101


def test_reboot_when_global_stop_flag(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_run.assert_not_called()
    assert "Global stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_when_global_stop_flag_after_sleep(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    def set_stop_flag(seconds):
        if seconds == 130:
            consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    # When rebootmgr sleeps for 2 minutes, the stop flag will be set.
    mocked_sleep = mocker.patch("time.sleep", side_effect=set_stop_flag)
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_not_called()
    assert "Global stop flag is set: exit" in result.output
    assert result.exit_code == 102


def test_reboot_when_global_stop_flag_when_ignored(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-global-stop-flag"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0


def test_reboot_when_global_stop_flag_after_sleep_when_ignored(
        run_cli, forward_consul_port, consul_cluster, default_config,
        reboot_task, mock_subprocess_run, mocker):
    def set_stop_flag(seconds):
        if seconds == 130:
            consul_cluster[0].kv.put("service/rebootmgr/stop", "")

    # When rebootmgr sleeps for 2 minutes, the stop flag will be set.
    mocked_sleep = mocker.patch("time.sleep", side_effect=set_stop_flag)
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v", "--ignore-global-stop-flag"])

    mocked_sleep.assert_any_call(130)
    mocked_run.assert_any_call(["shutdown", "-r", "+1"], check=True)
    assert "Reboot now ..." in result.output
    assert result.exit_code == 0
