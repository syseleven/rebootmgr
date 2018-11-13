import socket
import time
import itertools

import pytest

from unittest.mock import DEFAULT

from rebootmgr.main import cli as rebootmgr
from consul import Check


def test_reboot_success_whitelisted_checks(run_cli, forward_port, consul_cluster, reboot_task, mock_subprocess_run, mocker):
    consul_cluster[0].kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')

    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    forward_port.consul(consul_cluster[0])

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_reboot_fail_checks(run_cli, forward_port, consul_cluster, boot_task, mock_subprocess_run, mocker):
    consul_cluster[0].agent.service.register("A", tags=["rebootmgr"])
    consul_cluster[1].agent.service.register("A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    forward_port.consul(consul_cluster[0])

    mocker.patch("time.sleep")
    mock_subprocess_run(["shutdown", "-r", "+1"])

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2
