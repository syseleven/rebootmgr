from rebootmgr.main import cli as rebootmgr

import json
import pytest
import socket


def test_ensure_config_when_already_valid(run_cli, forward_consul_port, default_config):
    result = run_cli(rebootmgr, ["-vv", "--ensure-config"])

    assert "Did not create default configuration, since there already was one." in result.output
    assert result.exit_code == 0

@pytest.mark.parametrize("bad_config",
                         [None, '', '{}', 'disabled', '{"disabled": false}'])
def test_ensure_config_when_invalid(run_cli, forward_consul_port,
                                    consul_cluster, bad_config):
    hostname = socket.gethostname()
    if bad_config is not None:
        consul_cluster[0].kv.put("service/rebootmgr/nodes/%s/config" % hostname, bad_config)

    result = run_cli(rebootmgr, ["-v", "--ensure-config"])

    assert "Created default configuration, since it was missing or invalid." in result.output

    _, data = consul_cluster[0].kv.get("service/rebootmgr/nodes/{}/config".format(
        hostname))
    assert json.loads(data["Value"].decode()) == {
        "enabled": True,
        "message": "Default config created"
    }

    assert result.exit_code == 0
