import socket
import time
import itertools

import pytest

from unittest.mock import DEFAULT

from rebootmgr.main import cli as rebootmgr
from consul import Check


def test_reboot_success_whitelisted_checks(run_cli, forward_port, consul_service, consul_cluster, consul_kv, reboot_task, mocked_run, mocker):
    consul_kv.put("service/rebootmgr/ignore_failed_checks", '["consul2"]')

    consul_service.register(consul_cluster[0], "A", tags=["rebootmgr"])
    consul_service.register(consul_cluster[1], "A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    forward_port.consul(consul_cluster[0])

    mocker.patch("time.sleep")

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 0


def test_reboot_fail_checks(run_cli, forward_port, consul_cluster, consul_service, consul_kv, reboot_task, mocked_run, mocker):
    consul_service.register(consul_cluster[0], "A", tags=["rebootmgr"])
    consul_service.register(consul_cluster[1], "A", tags=["rebootmgr"], check=Check.ttl("1ms")) # Failing
    time.sleep(0.01)

    forward_port.consul(consul_cluster[0])

    mocker.patch("time.sleep")

    result = run_cli(rebootmgr, ["-v"])

    assert result.exit_code == 2