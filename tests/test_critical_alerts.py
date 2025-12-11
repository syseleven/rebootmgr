import pytest
import socket
from unittest.mock import patch
import requests.exceptions

from rebootmgr.main import (
    cli as rebootmgr,
    EXIT_CRITICAL_ALERTS_STILL_ACTIVE,
    CHECK_CRITICAL_ALERTS_TIMEOUT,
    get_firing_critical_alerts,
    wait_for_critical_alerts,
)


@pytest.fixture
def reboot_in_progress(consul_cluster):
    # Set up kv so that rebootmgr runs in post-reboot mode
    hostname = socket.gethostname().split(".")[0]
    try:
        consul_cluster[0].kv.put("service/rebootmgr/reboot_in_progress", hostname)
        yield
    finally:
        consul_cluster[0].kv.delete("service/rebootmgr/reboot_in_progress")


@pytest.fixture
def mock_prometheus_response():

    return {
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "labels": {
                        "severity": "critical",
                        "node": socket.gethostname().split(".")[0],
                    },
                },
                {
                    "state": "firing",
                    "labels": {
                        "severity": "warning",
                        "node": socket.gethostname().split(".")[0],
                    },
                },
                {
                    "state": "firing",
                    "labels": {"severity": "critical", "node": "other-host"},
                },
            ]
        }
    }


def test_get_firing_critical_alerts(mock_prometheus_response):
    """Test that get_firing_critical_alerts returns only critical alerts for the current host"""
    hostname = socket.gethostname().split(".")[0]

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = mock_prometheus_response
        mock_get.return_value.raise_for_status.return_value = None

        alerts = get_firing_critical_alerts(
            hostname, "https://prometheus:9090/api/v1/alerts"
        )

        assert len(alerts) == 1
        assert alerts[0]["labels"]["node"] == hostname
        assert alerts[0]["labels"]["severity"] == "critical"


def test_get_firing_critical_alerts_request_exception():
    """Test that get_firing_critical_alerts returns empty list when request exception occurs"""
    hostname = socket.gethostname().split(".")[0]
    prometheus_url = "https://prometheus:9090/api/v1/alerts"

    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException(
            "Test request exception"
        )

        # Call the function
        alerts = get_firing_critical_alerts(hostname, prometheus_url)

        # Verify the result
        assert alerts == []


def test_wait_for_critical_alerts_with_alerts(mocker, consul_cluster):
    """Test that wait_for_critical_alerts waits when there are critical alerts"""
    hostname = socket.gethostname().split(".")[0]
    group_key = f"service/rebootmgr/{hostname}_reboot_in_progress"
    prometheus_server_domain = "prometheus"

    # Mock the get_firing_critical_alerts function to return a list with one alert
    mocker.patch(
        "rebootmgr.main.get_firing_critical_alerts", return_value=[{"state": "firing"}]
    )

    # Mock time.sleep to avoid actual sleeping
    mocker.patch("time.sleep")

    # Set a short timeout for the test
    original_timeout = CHECK_CRITICAL_ALERTS_TIMEOUT
    import rebootmgr.main

    rebootmgr.main.CHECK_CRITICAL_ALERTS_TIMEOUT = 30  # 30 seconds

    try:
        with pytest.raises(TimeoutError):
            wait_for_critical_alerts(
                consul_cluster[0], None, hostname, group_key, prometheus_server_domain
            )
    finally:
        # Restore original timeout
        rebootmgr.main.CHECK_CRITICAL_ALERTS_TIMEOUT = original_timeout


def test_wait_for_critical_alerts_without_alerts(mocker, consul_cluster):
    """Test that wait_for_critical_alerts releases the host when there are no critical alerts"""
    hostname = socket.gethostname().split(".")[0]
    group_key = f"service/rebootmgr/{hostname}_reboot_in_progress"
    prometheus_server_domain = "prometheus"

    # Mock the get_firing_critical_alerts function to return an empty list
    mocker.patch("rebootmgr.main.get_firing_critical_alerts", return_value=[])

    # Mock release_host to verify it gets called
    mock_release_host = mocker.patch("rebootmgr.main.release_host")

    wait_for_critical_alerts(
        consul_cluster[0], None, hostname, group_key, prometheus_server_domain
    )

    assert mock_release_host.called


def test_post_reboot_with_prometheus(
    mocker,
    run_cli,
    consul_cluster,
    forward_consul_port,
    default_config,
    reboot_in_progress,
    reboot_task,
):
    """Test that post_reboot_state waits for critical alerts when prometheus_server is provided"""
    hostname = socket.gethostname().split(".")[0]
    prometheus_server_domain = "prometheus"

    # Mock wait_for_critical_alerts
    mock_wait = mocker.patch("rebootmgr.main.wait_for_critical_alerts")
    mock_release_host = mocker.patch("rebootmgr.main.release_host")

    # Set up flags with prometheus_server
    flags = {
        "prometheus_server": prometheus_server_domain,
        "dryrun": False,
        "ignore_failed_checks": False,
    }
    reboot_task("post_boot", "50_another_task.sh")
    # Call post_reboot_state directly
    from rebootmgr.main import post_reboot_state

    post_reboot_state(consul_cluster[0], None, hostname, flags, False, 120, "")

    assert mock_wait.called
    assert not mock_release_host.called


def test_post_reboot_without_prometheus(
    mocker,
    run_cli,
    consul_cluster,
    forward_consul_port,
    default_config,
    reboot_in_progress,
    reboot_task,
):
    """Test that post_reboot_state releases the host directly when no prometheus_server is provided"""
    hostname = socket.gethostname().split(".")[0]

    # Mock wait_for_critical_alerts
    mock_wait = mocker.patch("rebootmgr.main.wait_for_critical_alerts")
    mock_release_host = mocker.patch("rebootmgr.main.release_host")

    # Set up flags without prometheus_server
    flags = {"prometheus_server": None, "dryrun": False, "ignore_failed_checks": False}

    reboot_task("post_boot", "50_another_task.sh")

    # Call post_reboot_state directly
    from rebootmgr.main import post_reboot_state

    post_reboot_state(consul_cluster[0], None, hostname, flags, False, 120, "")

    assert not mock_wait.called
    assert mock_release_host.called


def test_post_reboot_with_timeout(
    mocker,
    run_cli,
    consul_cluster,
    forward_consul_port,
    default_config,
    reboot_in_progress,
    reboot_task,
):
    """Test that post_reboot_state exits with EXIT_CRITICAL_ALERTS_STILL_ACTIVE on timeout"""
    prometheus_server_domain = "prometheus"

    # Mock wait_for_critical_alerts to raise TimeoutError
    mocker.patch(
        "rebootmgr.main.wait_for_critical_alerts",
        side_effect=TimeoutError("Test timeout"),
    )
    reboot_task("post_boot", "50_another_task.sh")
    result = run_cli(rebootmgr, ["-v", "--prometheus-server", prometheus_server_domain])

    assert result.exit_code == EXIT_CRITICAL_ALERTS_STILL_ACTIVE
