from rebootmgr.main import cli as rebootmgr


def test_reboot_not_required(run_cli, forward_consul_port, reboot_task):
    result = run_cli(rebootmgr, ["-v", "--check-triggers"])

    assert "No reboot necessary" in result.output
    assert result.exit_code == 0
