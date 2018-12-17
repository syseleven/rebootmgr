import os
import click
import logging
import socket
import sys
import json
import subprocess
import time
import colorlog
import holidays
import datetime

from retrying import retry
from consul import Consul
from consul_lib import Lock
from consul_lib.services import get_local_checks, get_failed_cluster_checks

LOG = logging.getLogger(__name__)

EXIT_UNKNOWN_ERROR = 1

# exit codes < 100 are transient
EXIT_CONSUL_CHECKS_FAILED = 2
EXIT_CONSUL_NODE_FAILED = 3
EXIT_CONSUL_LOCK_FAILED = 4
EXIT_CONSUL_LOST_LOCK = 5
EXIT_HOLIDAY = 6

# exit codes >= 100 are permanent
EXIT_TASK_FAILED = 100
EXIT_NODE_DISABLED = 101
EXIT_GLOBAL_STOP_FLAG_SET = 102
EXIT_DID_NOT_REALLY_REBOOT = 103


def logsetup(verbosity):
    level = logging.WARNING

    if verbosity > 0:
        level = logging.INFO
    if verbosity > 1:
        level = logging.DEBUG

    stderr_formatter = colorlog.ColoredFormatter("%(log_color)s%(name)s [%(levelname)s] %(message)s")
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(stderr_formatter)

    logging.basicConfig(handlers=[stderr_handler], level=level)

    LOG.info("Verbose logging enabled")
    LOG.debug("Debug logging enabled")


def run_tasks(tasktype, con, hostname, dryrun):
    """
    run every script in /etc/rebootmgr/pre_boot_tasks or
    /etc/rebootmgr/post_boot_tasks

    tasktype is either pre_boot or post_boot
    dryrun If true the environment variable REBOOTMGR_DRY_RUN=1 is passed to
           the scripts
    """
    env = dict(os.environ)
    if dryrun:
        env["REBOOTMGR_DRY_RUN"] = "1"

    for task in sorted(os.listdir("/etc/rebootmgr/%s_tasks/" % tasktype)):
        task = os.path.join("/etc/rebootmgr/%s_tasks" % tasktype, task)
        LOG.info("Run task %s" % task)
        try:
            subprocess.run(task, check=True, env=env, timeout=(2 * 60 * 60))
        except subprocess.TimeoutExpired:
            LOG.error("Could not finish task %s in 2 hours. Exit" % task)
            LOG.error("Disable rebootmgr in consul for this node")
            idx, data = con.kv.get("service/rebootmgr/nodes/%s/config" % hostname)
            data = json.loads(data["Value"].decode())
            data["enabled"] = False
            data["message"] = "Could not finish task %s in 2 hours" % task
            con.kv.put("service/rebootmgr/nodes/%s/config" % hostname, json.dumps(data))
            con.kv.delete("service/rebootmgr/reboot_in_progress")
            sys.exit(EXIT_TASK_FAILED)
        LOG.info("task %s finished" % task)


def get_whitelist(con):
    """
    Reads a list of host which should be ignored
    """

    k, v = con.kv.get("service/rebootmgr/ignore_failed_checks")
    if v and "Value" in v.keys() and v["Value"]:
        return json.loads(v["Value"].decode())
    return []


def check_consul_services(con):
    """
    check all consul services for this node with the tag "rebootmgr"
    """
    whitelist = get_whitelist(con)

    if whitelist:
        LOG.warning("Checks from the following hosts will be ignored, " +
                    "because service/rebootmgr/ignore_failed_checks is set: {}".format(", ".join(whitelist)))

    local_checks = get_local_checks(con, tags=["rebootmgr"])
    LOG.debug("relevant_checks: %s" % local_checks)

    for name, check in get_failed_cluster_checks(con, local_checks).items():
        if check["Node"] in whitelist:
            continue

        LOG.error("There were failed consul checks. Exit")
        sys.exit(EXIT_CONSUL_CHECKS_FAILED)

    LOG.info("All checks passed")


@retry(wait_fixed=2000, stop_max_delay=20000)
def check_reboot_in_progress(con):
    """
    check for the key service/rebootmgr/reboot_in_progress
    If the key contains the nodename, this node is in post reboot state
    """
    k, v = con.kv.get("service/rebootmgr/reboot_in_progress")
    if v and "Value" in v.keys() and v["Value"]:
        return v["Value"].decode()
    return False


@retry(wait_fixed=2000, stop_max_delay=20000)
def check_stop_flag(con):
    """
    check the global stop flag
    """
    k, v = con.kv.get("service/rebootmgr/stop")
    if v:
        return True
    return False


@retry(wait_fixed=2000, stop_max_delay=20000)
def is_reboot_required(con, nodename):
    k, v = con.kv.get("service/rebootmgr/nodes/%s/reboot_required" % nodename)
    if v:
        LOG.debug("Found key %s. Reboot required" % nodename)
        return True
    if os.path.isfile("/var/run/reboot-required"):
        LOG.debug("Found file /var/run/reboot-required. Reboot required")
        return True
    LOG.info("No reboot necessary")
    return False


def uptime():
    with open('/proc/uptime', 'r') as f:
        uptime = float(f.readline().split()[0])
        return uptime


def check_consul_cluster(con):
    whitelist = get_whitelist(con)
    if whitelist:
        LOG.warning("Status of the following hosts will be ignored, " +
                    "because service/rebootmgr/ignore_failed_checks is set: {}".format(", ".join(whitelist)))
    for member in con.agent.members():
        if "Status" in member.keys() and member["Status"] != 1 and member["Name"] not in whitelist:
            LOG.error("Consul cluster not healthy: Node %s failed. Exit" % member["Name"])
            sys.exit(EXIT_CONSUL_NODE_FAILED)


@retry(wait_fixed=2000, stop_max_delay=20000)
def is_node_disabled(con, hostname):
    idx, data = con.kv.get("service/rebootmgr/nodes/%s/config" % hostname)
    if data and "Value" in data.keys() and data["Value"]:
        data = json.loads(data["Value"].decode())
        if "disabled" in data.keys() and data["disabled"]:
            return True
    return False


@click.command()
@click.option("-v", "--verbose", count=True, help="Once for INFO logging, twice for DEBUG")
@click.option("--check-triggers", help="Only reboot if a reboot is necessary", is_flag=True)
@click.option("-n", "--dryrun", help="Run tasks and check services but don't reboot", is_flag=True)
@click.option("-u", "--check-uptime", help="Make sure, that the uptime is less than 2 hours.", is_flag=True)
@click.option("-s", "--ignore-global-stop-flag", help="ignore the global stop flag (service/rebootmgr/stop).", is_flag=True)
@click.option("--check-holidays", help="Don't reboot on holidays", is_flag=True)
@click.option("--lazy-consul-checks", help="Don't repeat consul checks after two minutes", is_flag=True)
@click.option("-l", "--ignore-node-disabled", help="ignore the node specific stop flag (service/rebootmgr/hostname/config)", is_flag=True)
@click.option("--maintenance-reason", help="""Reason for the downtime in consul. If the text starts with "reboot", """ +
              "a 15 minute maintenance period is scheduled in zabbix\nDefault: reboot by rebootmgr",
              default="reboot by rebootmgr")
@click.option("--consul", help="Address of Consul. Default env REBOOTMGR_CONSUL_ADDR or 127.0.0.1.",
              default=os.environ.get("REBOOTMGR_CONSUL_ADDR", "127.0.0.1"))
@click.option("--consul-port", help="Port of Consul. Default env REBOOTMGR_CONSUL_PORT or 8500",
              default=os.environ.get("REBOOTMGR_CONSUL_PORT", 8500))
@click.version_option()
def cli(verbose, consul, consul_port, check_triggers, check_uptime, dryrun, maintenance_reason, ignore_global_stop_flag,
        ignore_node_disabled, check_holidays, lazy_consul_checks):
    """Reboot Manager

    Default values of parameteres are environment variables (if set)
    """
    logsetup(verbose)

    con = Consul(host=consul, port=int(consul_port))
    hostname = socket.gethostname().split(".")[0]

    check_consul_cluster(con)

    # Get Lock
    with Lock(con, "service/rebootmgr/lock") as consul_lock:
        if not consul_lock.acquire(blocking=False):
            LOG.error("Could not get consul lock. Exit")
            sys.exit(EXIT_CONSUL_LOCK_FAILED)

        reboot_in_progress = check_reboot_in_progress(con)
        if reboot_in_progress:
            if reboot_in_progress.startswith(hostname):
                LOG.info("Found my hostname in service/rebootmgr/reboot_in_progress")
                LOG.info("Entering post reboot state")

                # Uptime greater 2 hours
                if check_uptime and uptime() > 2 * 60 * 60:
                    LOG.error("We are in post reboot state but uptime is higher then 2 hours. Exit")
                    sys.exit(EXIT_DID_NOT_REALLY_REBOOT)

                LOG.info("Entering post reboot state")
                # Disable consul (and Zabbix) maintenance
                con.agent.maintenance(False)

                check_consul_services(con)
                run_tasks("post_boot", con, hostname, dryrun)
                check_consul_services(con)

                LOG.info("Remove consul key service/rebootmgr/nodes/%s/reboot_required" % hostname)
                con.kv.delete("service/rebootmgr/nodes/%s/reboot_required" % hostname)
                LOG.info("Remove consul key service/rebootmgr/reboot_in_progress")
                con.kv.delete("service/rebootmgr/reboot_in_progress")

                consul_lock.release()
                sys.exit(0)

            # Another node has the lock
            else:
                LOG.info("Another Node %s is rebooting. Exit" % reboot_in_progress)
                sys.exit(EXIT_CONSUL_LOCK_FAILED)

        # consul-key reboot_in_progress does not exist
        # we are free to reboot
        else:
            # We are in pre_reboot state
            today = datetime.date.today()
            if check_holidays and today in holidays.DE():
                LOG.info("Refuse to run on holiday")
                sys.exit(EXIT_HOLIDAY)

            if check_stop_flag(con) and not ignore_global_stop_flag:
                LOG.info("Global stop flag is set: exit")
                sys.exit(EXIT_GLOBAL_STOP_FLAG_SET)

            if is_node_disabled(con, hostname) and not ignore_node_disabled:
                LOG.info("Rebootmgr is disabled in consul config for this node. Exit")
                sys.exit(EXIT_NODE_DISABLED)

            if check_triggers and not is_reboot_required(con, hostname):
                sys.exit(0)

            LOG.info("Entering pre reboot state")

            check_consul_services(con)

            LOG.info("Executing pre reboot tasks")
            run_tasks("pre_boot", con, hostname, dryrun)

            if not lazy_consul_checks:
                LOG.info("Sleep for 2 minutes. Waiting for consul checks.")
                time.sleep((60 * 2) + 10)

            check_consul_cluster(con)
            check_consul_services(con)

            if not consul_lock.acquired:
                LOG.error("Lost consul lock. Exit")
                sys.exit(EXIT_CONSUL_LOST_LOCK)

            if check_stop_flag(con) and not ignore_global_stop_flag:
                LOG.info("Global stop flag is set: exit")
                sys.exit(EXIT_GLOBAL_STOP_FLAG_SET)

            if not dryrun:
                LOG.debug("Write %s in key service/rebootmgr/reboot_in_progress" % hostname)
                con.kv.put("service/rebootmgr/reboot_in_progress", hostname)

            consul_lock.release()

            if not dryrun:
                # Set a consul maintenance, which creates a 15 maintenance window in Zabbix
                con.agent.maintenance(True, maintenance_reason)

                LOG.warning("Reboot now ...")
                try:
                    # NOTE(sneubauer): Reboot after 1 minutes. This was added
                    # for the MachineDB reboot task, so it can report success
                    # to the API before the actual reboot happens.
                    subprocess.run(["shutdown", "-r", "+1"], check=True)
                except Exception as e:
                    LOG.error("Could not run reboot")
                    LOG.error("Remove consul key service/rebootmgr/reboot_in_progress")
                    con.kv.delete("service/rebootmgr/reboot_in_progress")
                    raise e


if __name__ == "__main__":
    cli()
