import time
import json
import logging
import requests
import socket
import subprocess

from unittest.mock import DEFAULT

import pytest
import consul


@pytest.fixture
def consul_cluster():
    clients = [consul.Consul(host="consul{}".format(i + 1)) for i in range(4)]

    while not clients[0].status.leader():
        time.sleep(.1)

    snapshot_url = 'http://consul1:8500/v1/snapshot'
    snapshot = requests.get(snapshot_url)
    snapshot.raise_for_status()

    try:
        yield clients
    finally:
        # Consul cluster state includes the KV store.
        resp = requests.put(snapshot_url, data=snapshot.content)
        resp.raise_for_status()
        for c in clients:
            c.agent.maintenance(False)
            for name, service in c.agent.services().items():
                c.agent.service.deregister(name)


@pytest.fixture
def mock_subprocess_run(mocker):
    """
    Fixture for testing `subprocess.run`. Returns and configures a `MagicMock` instance.

    You can optionally pass a `side_effect` as a second argument.

    `side_effect` can be an Exception and will then be raised; see the `MagicMock.side_effect` documentation for more information.

    Example:

        mocked_run = mock_subprocess_run(["reboot"])

        call_your_tested_code()

        mocked_run.assert_any_call(["reboot"])
    """
    side_effects = {}

    def get_side_effect(command, *args, **kwargs):
        if isinstance(command, str):
            command = [command]
        elif isinstance(command, list):
            pass
        else:
            raise ValueError("command must be either string or list")

        side_effect = side_effects[json.dumps(command)]
        if isinstance(side_effect, Exception):
            raise side_effect
        if side_effect:
            return side_effect
        return DEFAULT

    mocked_run = mocker.patch("subprocess.run")
    mocked_run.side_effect = get_side_effect

    def add(command, side_effect=None):
        side_effects[json.dumps(command)] = side_effect
        return mocked_run

    return add


@pytest.fixture
def run_cli():
    from click.testing import CliRunner

    def run(*args, catch_exceptions=False, **kwargs):
        # See https://github.com/pallets/click/issues/1053
        logging.getLogger("").handlers = []

        runner = CliRunner(mix_stderr=True)
        result = runner.invoke(*args, catch_exceptions=catch_exceptions, **kwargs)
        print(result.output)
        return result

    return run


@pytest.fixture
def reboot_task(mocker, mock_subprocess_run):
    tasks = {"pre_boot": [], "post_boot": []}

    def listdir(directory):
        # TODO: Make task directories configurable to avoid mocking them in tests.
        # Hence, we would be able to use Pytest's tmpdir fixture.
        if directory == "/etc/rebootmgr/pre_boot_tasks/":
            return tasks["pre_boot"]
        elif directory == "/etc/rebootmgr/post_boot_tasks/":
            return tasks["post_boot"]
        else:
            raise FileNotFoundError
    mocker.patch("os.listdir", new=listdir)

    def create_task(tasktype, filename, exit_code=0, raise_timeout_expired=False):
        assert tasktype in ["pre_boot", "post_boot"], "task type must be either pre_boot or post_boot"

        tasks[tasktype] += [filename]

        side_effect = None
        if exit_code != 0:
            side_effect = subprocess.CalledProcessError(exit_code, filename)
        elif raise_timeout_expired:
            side_effect = subprocess.TimeoutExpired(filename, 1234)

        mock_subprocess_run(
            ["/etc/rebootmgr/{}_tasks/{}".format(tasktype, filename)],
            side_effect)

    return create_task


@pytest.fixture
def default_config(consul_cluster):
    hostname = socket.gethostname()
    key = "service/rebootmgr/nodes/%s/config" % hostname
    consul_cluster[0].kv.put(key, '{"enabled": true}')

    yield

    consul_cluster[0].kv.delete("service/rebootmgr", recurse=True)


@pytest.fixture
def forward_consul_port(forward_port, consul_cluster):
    forward_port.consul(consul_cluster[0])


@pytest.fixture
def forward_port():
    """
    Forwards tcp ports.

    We need this, because rebootmgr assumes that consul is reachable on localhost:8500.

    This example will forward `127.0.0.1:8500` to `10.0.0.1:8500`

        forward_port.tcp("10.0.0.1", 8500)
    """
    f = _PortForwardingFixture()
    try:
        yield f
    finally:
        f.restore()


class _PortForwardingFixture:
    """
    See the `forward_port` fixture for an explanation and an example.
    """
    def __init__(self):
        self.forwarders = []

    def consul(self, con):
        self.tcp(8500, con.http.host, con.http.port)

    def tcp(self, listen_port, forward_host, forward_ip):
        forwarder = _TCPPortForwarder(listen_port, forward_host, forward_ip)
        forwarder.start()
        self.forwarders += [forwarder]

    def restore(self):
        for forwarder in self.forwarders:
            forwarder.stop()


class _TCPPortForwarder():
    """
    Forward TCP port using socat under the hood.

    See the `forward_port` fixture for an explanation and an example.

    This is known to be a hack; usinfg socat was the simplest and most reliable solution I found.
    """
    def __init__(self, listen_port, forward_host, forward_port):
        self.listen_port = listen_port
        self.forward_host = forward_host
        self.forward_port = forward_port
        self.process = None

    def start(self):
        self.process = subprocess.Popen([
             "socat",
             "tcp-listen:{},reuseaddr,fork".format(self.listen_port),
             "tcp:{}:{}".format(self.forward_host, self.forward_port)
        ])
        # XXX(sneubauer): Dirty fix for race condition, where socat is not ready yet when test runs.
        time.sleep(0.05)

    def stop(self):
        self.process.terminate()
