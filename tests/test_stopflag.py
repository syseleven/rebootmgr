import json
import socket

from rebootmgr.main import cli as rebootmgr


def test_not_verbose(run_cli, consul_cluster, forward_consul_port, default_config):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "reason: stopped for testing")

    result = run_cli(rebootmgr)

    # There is a distinct exit code when the global stop flag is set
    assert result.exit_code == 102

    # We did not ask for verbose logging
    assert not result.output


def test_verbose(run_cli, consul_cluster, forward_consul_port, default_config):
    consul_cluster[0].kv.put("service/rebootmgr/stop", "reason: stopped for testing")

    result1 = run_cli(rebootmgr, ["-v"])
    assert "Stop flag is set" in result1.output

    result2 = run_cli(rebootmgr, ["-vv"])
    assert "Stop flag is set" in result2.output
    assert "service/rebootmgr/stop" in result2.output


def test_set_global_stop_flag(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")
    datacenter = "test"

    result = run_cli(rebootmgr, ["-v", "--set-global-stop-flag", datacenter])

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    assert "Set " + datacenter + " global stop flag:" in result.output
    idx, data = consul_cluster[0].kv.get("service/rebootmgr/stop", dc=datacenter)
    assert idx is not None
    assert data["Value"]
    assert result.exit_code == 0


def test_set_global_stop_flag_with_reason(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    datacenter = "test"

    result = run_cli(
        rebootmgr,
        ["-v", "--set-global-stop-flag", datacenter, "--stop-reason", "My reason"],
    )

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    assert "Set " + datacenter + " global stop flag:" in result.output
    idx, data = consul_cluster[0].kv.get("service/rebootmgr/stop", dc=datacenter)
    assert idx is not None
    assert "My reason" in data["Value"].decode()
    assert result.exit_code == 0


def test_unset_global_stop_flag(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    datacenter = "test"

    result = run_cli(rebootmgr, ["-v", "--set-global-stop-flag", datacenter])

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    idx, data = consul_cluster[0].kv.get("service/rebootmgr/stop", dc=datacenter)
    assert idx is not None
    assert data
    assert result.exit_code == 0

    result = run_cli(rebootmgr, ["-v", "--unset-global-stop-flag", datacenter])
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    idx, data = consul_cluster[0].kv.get("service/rebootmgr/stop", dc=datacenter)
    assert "Remove " + datacenter + " global stop flag" in result.output
    assert idx is not None
    assert data is None
    assert result.exit_code == 0


def test_set_local_stop_flag(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    mocked_popen = mocker.patch("subprocess.Popen")
    hostname = socket.gethostname().split(".")[0]

    result = run_cli(rebootmgr, ["-v", "--set-local-stop-flag"])

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    mocked_popen.assert_not_called()
    assert "Set " + hostname + " local stop flag:" in result.output
    idx, data = consul_cluster[0].kv.get(
        "service/rebootmgr/nodes/{}/config".format(hostname)
    )
    assert idx is not None
    config = json.loads(data["Value"].decode())
    assert config["enabled"] is False
    assert result.exit_code == 0


def test_set_local_stop_flag_with_reason(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    hostname = socket.gethostname().split(".")[0]

    result = run_cli(
        rebootmgr, ["-v", "--set-local-stop-flag", "--stop-reason", "My reason"]
    )

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    assert "Set " + hostname + " local stop flag:" in result.output
    idx, data = consul_cluster[0].kv.get(
        "service/rebootmgr/nodes/{}/config".format(hostname)
    )
    assert idx is not None
    config = json.loads(data["Value"].decode())
    assert config["enabled"] is False
    assert "My reason" in config["message"]
    assert result.exit_code == 0


def test_unset_local_stop_flag(
    run_cli, forward_consul_port, consul_cluster, mock_subprocess_run, mocker
):
    mocked_sleep = mocker.patch("time.sleep")
    mocked_run = mock_subprocess_run(["shutdown", "-r", "+1"])
    hostname = socket.gethostname().split(".")[0]

    result = run_cli(rebootmgr, ["-v", "--set-local-stop-flag"])

    consul_key = "service/rebootmgr/nodes/{}/config".format(hostname)
    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    idx, data = consul_cluster[0].kv.get(consul_key)
    assert idx is not None
    config = json.loads(data["Value"].decode())
    assert config["enabled"] is False
    assert result.exit_code == 0

    result = run_cli(rebootmgr, ["-v", "--unset-local-stop-flag"])

    mocked_sleep.assert_not_called()
    mocked_run.assert_not_called()
    assert "Unset " + hostname + " local stop flag" in result.output
    idx, data = consul_cluster[0].kv.get(consul_key)
    assert idx is not None
    config = json.loads(data["Value"].decode())
    assert config["enabled"] is True
    assert result.exit_code == 0
