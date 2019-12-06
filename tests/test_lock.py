from rebootmgr.main import cli as rebootmgr
from consul_lib import Lock


def test_consul_lock_fails(
        run_cli, forward_consul_port, consul_cluster, default_config):
    with Lock(consul_cluster[0], "service/rebootmgr/lock"):
        result = run_cli(rebootmgr, ["-v"], catch_exceptions=True)

        assert "Could not get consul lock. Exit" in result.output
        assert result.exit_code == 4

# TODO(oseibert): Test when the lock is lost during the 2 minute sleep.
