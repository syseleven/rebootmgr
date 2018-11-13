import socket
import time
import itertools

import pytest

from unittest.mock import DEFAULT

from rebootmgr.main import cli as rebootmgr
from consul import Check


def test_reboot_succeeds_with_failed_checks_if_whitelisted(run_cli, forward_consul_port, consul_cluster, reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')

    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_rebooting_fails_with_failing_checks(run_cli, forward_consul_port, consul_cluster, reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2
