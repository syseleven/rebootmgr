import pytest

from rebootmgr.main import cli as rebootmgr


def test_stopflag(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)
    consul_kv.put("service/rebootmgr/stop", "reason: stopped for testing")

    result = run_click(rebootmgr)

    # There is a distinct exit code when the global stop flag is set
    assert result.exit_code == 102

    # We did not ask for verbose logging
    assert not result.output


def test_verbose(run_click, forward_port, consul_kv, consul1):
    forward_port.consul(consul1)
    consul_kv.put("service/rebootmgr/stop", "reason: stopped for testing")

    result1 = run_click(rebootmgr, ["-v"])
    assert "Global stop flag is set" in result1.output
    assert "service/rebootmgr/stop" not in result1.output

    result2 = run_click(rebootmgr, ["-vv"])
    assert "Global stop flag is set" in result2.output
    assert "service/rebootmgr/stop" in result2.output
