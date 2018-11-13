import socket

import pytest

from rebootmgr.main import cli as rebootmgr


def test_reboot_not_required(run_cli, forward_port, consul_cluster, reboot_task, mocker):
    forward_port.consul(consul_cluster[0])

    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    assert "No reboot necessary" in result.output
    assert result.exit_code == 0
