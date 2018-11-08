import os
import signal
import logging
import subprocess

import pytest
import consul


@pytest.fixture
def consul1():
    return _wait_for_leader(consul.Consul(host="consul1"))


@pytest.fixture
def consul2():
    return _wait_for_leader(consul.Consul(host="consul2"))


@pytest.fixture
def consul3():
    return _wait_for_leader(consul.Consul(host="consul3"))


@pytest.fixture
def consul4():
    return _wait_for_leader(consul.Consul(host="consul4"))


@pytest.fixture
def run_click():
    from click.testing import CliRunner
    def run(*args, **kwargs): 
        # See https://github.com/pallets/click/issues/1053
        logging.getLogger("").handlers = []

        runner = CliRunner(mix_stderr=True)
        return runner.invoke(*args, catch_exceptions=False, **kwargs)
    return run

@pytest.fixture
def consul_maint():
    f = _ConsulMaintFixture()
    yield f
    f.restore()


@pytest.fixture
def consul_service():
    f = _ConsulServiceFixture()
    yield f
    f.restore()


@pytest.fixture
def consul_kv(consul1):
    f = _ConsulKVFixture(consul1)
    yield f
    f.restore()


@pytest.fixture
def forward_port():
    f = _PortForwardingFixture()
    yield f
    f.restore()


def _wait_for_leader(c):
    import time
    while not c.status.leader():
        time.sleep(.1)
    return c


class _ConsulServiceFixture:
    def __init__(self):
        self.registered_services = []

    def register(self, consul_client, name, *args, service_id=None, **kwargs):
        consul_client.agent.service.register(name, *args, **kwargs)
        self.registered_services += [(consul_client, service_id or name)]

    def restore(self):
        for consul_client, service_name in self.registered_services:
            consul_client.agent.service.deregister(service_name)


class _ConsulKVFixture:
    def __init__(self, con):
        self._written = []
        self._con = con

    def get(self, *args, **kwargs):
        self._con.kv.get(*args, **kwargs)

    def put(self, key, *args, **kwargs):
        self._con.kv.put(key, *args, **kwargs)
        self._written += [key]

    def delete(self, *args, **kwargs):
        self._con.kv.delete(*args, **kwargs)

    def restore(self):
        for x in self._written:
            self.delete(x)


class _ConsulMaintFixture:
    def __init__(self):
        self._enabled = []

    def enable(self, consul_client, reason=None):
        consul_client.agent.maintenance(True, reason)
        self._enabled += [consul_client]

    def disable(self, consul_client):
        consul_client.agent.maintenance(False)

    def restore(self):
        for client in self._enabled:
            self.disable(client)


class _PortForwardingFixture:
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

    def stop(self):
        self.process.terminate()
