import os
import click
import getpass
import logging
import socket
import sys
import json
import subprocess
import time
import colorlog
import holidays
import datetime
from typing import List
from typing import Tuple

from retrying import retry
from consul import Consul
from consul_lib import Lock
from consul_lib.services import get_local_checks, get_failed_cluster_checks
from consul_lib.session import SessionRenewer

LOG = logging.getLogger(__name__)

EXIT_UNKNOWN_ERROR = 1

# exit codes < 100 are transient
EXIT_CONSUL_CHECKS_FAILED = 2
EXIT_CONSUL_NODE_FAILED = 3
EXIT_CONSUL_LOCK_FAILED = 4
EXIT_CONSUL_LOST_LOCK = 5
EXIT_HOLIDAY = 6
EXIT_STOP_FLAG_FAILED = 7

# exit codes >= 100 are permanent
EXIT_TASK_FAILED = 100
EXIT_NODE_DISABLED = 101
EXIT_STOP_FLAG_SET = 102
EXIT_DID_NOT_REALLY_REBOOT = 103
EXIT_CONFIGURATION_IS_MISSING = 104


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


def fire_chat_escalation(con, hostname, message, group=None):
    """Fire a consul event to escalate a failure to chat.

    Format: (hostname) (group) message
    """
    hostname_str = f"({hostname}) " if hostname else ""
    group_str = f"({group}) " if group else ""
    body = f"{hostname_str}{group_str}{message}"
    try:
        con.event.fire("chat_escalation", body)
    except Exception as e:
        LOG.error("Failed to fire chat_escalation event: %s", e)


def run_tasks(tasktype, con, hostname, dryrun, task_timeout, group):
    """
    run every script in /etc/rebootmgr/pre_boot_tasks or
    /etc/rebootmgr/post_boot_tasks

    tasktype is either pre_boot or post_boot
    dryrun If true the environment variable REBOOTMGR_DRY_RUN=1 is passed to
           the scripts
    """
    group_key = resolve_group_key(con, group, hostname)
    LOG.info("Looking up group from hostname: %s", group_key)
    env = dict(os.environ)
    if dryrun:
        env["REBOOTMGR_DRY_RUN"] = "1"

    for task in sorted(os.listdir("/etc/rebootmgr/%s_tasks/" % tasktype)):
        task = os.path.join("/etc/rebootmgr/%s_tasks" % tasktype, task)
        LOG.info("Run task %s" % task)
        p = subprocess.Popen(task, env=env)
        try:
            ret = p.wait(timeout=(task_timeout * 60))
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            message = "Could not finish task %s in %i minutes" % (task, task_timeout)
            LOG.error("%s. Exit" % message)
            LOG.error("Disable rebootmgr in consul for this node")
            data = get_config(con, hostname)
            data["enabled"] = False
            data["message"] = message
            put_config(con, hostname, data)
            con.kv.delete(group_key)
            fire_chat_escalation(con, hostname, message, resolve_group_name(con, group, hostname))
            sys.exit(EXIT_TASK_FAILED)
        if ret != 0:
            message = "Task %s failed with return code %s" % (task, ret)
            LOG.error("%s. Exit" % message)
            fire_chat_escalation(con, hostname, message, resolve_group_name(con, group, hostname))
            sys.exit(EXIT_TASK_FAILED)
        LOG.info("task %s finished" % task)


def get_whitelist(con) -> List[str]:
    """
    Reads a list of hosts which should be ignored. May be absent.
    """
    k, v = con.kv.get("service/rebootmgr/ignore_failed_checks")
    if v and "Value" in v.keys() and v["Value"]:
        return json.loads(v["Value"].decode())
    return []


def check_consul_services(con, hostname, ignore_failed_checks: bool, tags: List[str], wait_until_healthy=False):
    """
    check all consul services for this node with the tag "rebootmgr"
    """
    whitelist = get_whitelist(con)

    if whitelist:
        LOG.warning("Checks from the following hosts will be ignored, " +
                    "because service/rebootmgr/ignore_failed_checks is set: {}".format(", ".join(whitelist)))

    local_checks = get_local_checks(con, tags=tags)
    LOG.debug("local_checks: %s" % local_checks)

    if ignore_failed_checks:
        LOG.warning("All consul service checks are ignored.")
    else:
        failed_cluster_checks = get_failed_cluster_checks(con, local_checks).items()
        failed_names = []

        LOG.debug("failed_cluster_checks: %s" % failed_cluster_checks)
        for name, check in failed_cluster_checks:
            if check["Node"] not in whitelist:
                # If the check is failing because the node is us and it is the
                # is-in-maintenance-mode check, ignore it.
                if name == '_node_maintenance' and check["Node"] == hostname:
                    pass
                else:
                    failed_names.append(name + " on " + check["Node"])

        if failed_names:
            if wait_until_healthy:
                LOG.error("There were failed consul checks (%s). Trying again in 2 minutes.", failed_names)
                time.sleep(120)
                check_consul_services(con, hostname, ignore_failed_checks, tags, wait_until_healthy)
            else:
                LOG.error("There were failed consul checks (%s). Exit.", failed_names)
                sys.exit(EXIT_CONSUL_CHECKS_FAILED)
        else:
            LOG.info("All consul checks passed.")


def resolve_group_name(con, group, hostname):
    """
    Resolve the group name for this node.

    Priority:
    1. Use explicit group if provided.
    2. Use hostname-based group from config.
    3. Return None if no group is configured.
    """
    if group:
        return group
    config = get_config(con, hostname)
    return config.get('group')


def resolve_group_key(con, group, hostname):
    """
    Resolve the correct reboot status key from Consul KV store.

    Group resolution is delegated to resolve_group_name:
    1. Use explicit group if provided.
    2. Use hostname-based group from config.
    3. Fallback to default key.

    Returns:
        Full key path as string.
    """
    group_name = resolve_group_name(con, group, hostname)
    if group_name:
        return f"service/rebootmgr/{group_name}_reboot_in_progress"
    return "service/rebootmgr/reboot_in_progress"


def resolve_stop_flag(con, group, hostname):
    """
    Resolve the correct stop flag from Consul KV store.

    Group resolution is delegated to resolve_group_name:
    1. Use explicit group if provided.
    2. Use hostname-based group from config.
    3. Fallback to default key.

    Returns:
        Full key path as string.
    """
    group_name = resolve_group_name(con, group, hostname)
    if group_name:
        return f"service/rebootmgr/{group_name}_stop"
    return "service/rebootmgr/stop"


def resolve_lock(con, group, hostname):
    """
    Resolve the correct lock key from Consul KV store.

    Group resolution is delegated to resolve_group_name:
    1. Use explicit group if provided.
    2. Use hostname-based group from config.
    3. Fallback to default key.

    Returns:
        Full key path as string.
    """
    group_name = resolve_group_name(con, group, hostname)
    if group_name:
        return f"service/rebootmgr/{group_name}_lock"
    return "service/rebootmgr/lock"


@retry(wait_fixed=2000, stop_max_delay=20000)
def check_reboot_in_progress(con, group, hostname):
    """
    Check the reboot state of the host.

    Returns:
        Decoded value of the resolved key if found, else empty string.
    """
    def get_decoded_value(key):
        _, value = con.kv.get(key)
        if value and value.get("Value"):
            return value["Value"].decode()
        return ""

    group_key = resolve_group_key(con, group, hostname)
    LOG.info("Looking up group from: %s", group_key)
    return get_decoded_value(group_key)


@retry(wait_fixed=2000, stop_max_delay=20000)
def check_stop_flag(con, group, hostname) -> Tuple[bool, str]:
    """
    Check the Global stop flag first and then the group one. Present is True, absent is False.
    """
    LOG.info("Looking up Global stop flag from: service/rebootmgr/stop")
    k, v = con.kv.get("service/rebootmgr/stop")
    if v:
        return True, "service/rebootmgr/stop"
    else:
        stop_flag = resolve_stop_flag(con, group, hostname)
        LOG.info("Looking up stop flag from: /%s", stop_flag)
        k, v = con.kv.get(stop_flag)
        if v:
            return True, stop_flag
    return False, "Null"


@retry(wait_fixed=2000, stop_max_delay=20000)
def is_reboot_required(con, nodename) -> bool:
    """
    Check the node's reboot_required flags. Present is True, absent is False.
    """
    k, v = con.kv.get("service/rebootmgr/nodes/%s/reboot_required" % nodename)
    if v:
        LOG.debug("Found key %s. Reboot required" % nodename)
        return True
    if os.path.isfile("/var/run/reboot-required"):
        LOG.debug("Found file /var/run/reboot-required. Reboot required")
        return True
    LOG.info("No reboot necessary")
    return False


def uptime() -> float:
    with open('/proc/uptime', 'r') as f:
        uptime = float(f.readline().split()[0])
        return uptime


def get_all_node_groups(con):
    index, items = con.kv.get("service/rebootmgr/nodes/", recurse=True)

    groups = {}

    if not items:
        return groups  # pragma: no cover

    for item in items:
        key = item.get("Key", "")
        if not key.endswith("/config"):
            continue

        try:
            node_name = key.split("/")[3]
        except IndexError:  # pragma: no cover
            continue  # pragma: no cover

        try:
            value = item.get("Value")
            if value:
                config = json.loads(value.decode("utf-8"))
                groups[node_name] = config.get("group")
        except Exception:  # pragma: no cover
            continue  # pragma: no cover

    return groups


def members_in_group(con, hostname):
    node_groups = get_all_node_groups(con)

    local_group = node_groups.get(hostname)

    if not local_group:
        return con.agent.members()

    matching_members = []

    for member in con.agent.members():
        node_name = member.get("Name")
        group = node_groups.get(node_name)

        if group == local_group:
            matching_members.append(member)

    return matching_members


def check_consul_cluster(con, hostname, ignore_failed_checks: bool) -> None:
    whitelist = get_whitelist(con)
    if whitelist:
        LOG.warning("Status of the following hosts will be ignored, " +
                    "because service/rebootmgr/ignore_failed_checks is set: {}".format(", ".join(whitelist)))
    if ignore_failed_checks:
        LOG.warning("All consul cluster checks are ignored.")
    else:
        for member in members_in_group(con, hostname):
            # Consul member status 1 = Alive, 3 = Left
            if "Status" in member.keys() and member["Status"] not in [1, 3] and member["Name"] not in whitelist:
                LOG.error("Consul cluster not healthy: Node %s failed. Exit" % member["Name"])
                sys.exit(EXIT_CONSUL_NODE_FAILED)


@retry(wait_fixed=2000, stop_max_delay=20000)
def is_node_disabled(con, hostname) -> bool:
    data = get_config(con, hostname)
    return not data.get('enabled', False)


def post_reboot_state(con, consul_lock, hostname, flags, wait_until_healthy, task_timeout, group):
    group_key = resolve_group_key(con, group, hostname)
    LOG.info("Looking up group from: %s", group_key)
    LOG.info("Found my hostname in %s" % group_key)

    # Uptime greater 2 hours
    if flags.get("check_uptime") and uptime() > 2 * 60 * 60:
        LOG.error("We are in post reboot state but uptime is higher then 2 hours. Exit")
        sys.exit(EXIT_DID_NOT_REALLY_REBOOT)

    LOG.info("Entering post reboot state")

    check_consul_services(con, hostname, flags.get("ignore_failed_checks"), ["rebootmgr", "rebootmgr_postboot"], wait_until_healthy)
    run_tasks("post_boot", con, hostname, flags.get("dryrun"), task_timeout, group)
    check_consul_services(con, hostname, flags.get("ignore_failed_checks"), ["rebootmgr", "rebootmgr_postboot"], wait_until_healthy)

    # Disable consul (and Zabbix) maintenance
    con.agent.maintenance(False)

    LOG.info("Remove consul key service/rebootmgr/nodes/%s/reboot_required" % hostname)
    con.kv.delete("service/rebootmgr/nodes/%s/reboot_required" % hostname)
    LOG.info("Remove consul key %s" % group_key)
    con.kv.delete(group_key)

    consul_lock.release()


def _check_and_handle_stop_flag(con, group, hostname, flags):
    """Check if stop flag is set and handle it appropriately."""
    must_stop, stop_flag = check_stop_flag(con, group, hostname)
    if must_stop and not flags.get("ignore_stop_flag"):
        LOG.info("Stop flag is set: exit (%s)" % stop_flag)
        sys.exit(EXIT_STOP_FLAG_SET)


def pre_reboot_state(con, consul_lock, hostname, flags, task_timeout, group):
    group_key = resolve_group_key(con, group, hostname)
    today = datetime.date.today()
    if flags.get("check_holidays") and today in holidays.DE():
        LOG.info("Refuse to run on holiday")
        sys.exit(EXIT_HOLIDAY)

    _check_and_handle_stop_flag(con, group, hostname, flags)

    if is_node_disabled(con, hostname) and not flags.get("ignore_node_disabled"):
        LOG.info("Rebootmgr is disabled in consul config for this node. Exit")
        sys.exit(EXIT_NODE_DISABLED)

    if flags.get("check_triggers") and not is_reboot_required(con, hostname):
        sys.exit(0)

    LOG.info("Entering pre reboot state")

    check_consul_services(con, hostname, flags.get("ignore_failed_checks"), ["rebootmgr", "rebootmgr_preboot"])

    LOG.info("Executing pre reboot tasks")
    run_tasks("pre_boot", con, hostname, flags.get("dryrun"), task_timeout, group)

    if not flags.get("lazy_consul_checks"):
        LOG.info("Sleep for 2 minutes. Waiting for consul checks.")
        time.sleep((60 * 2) + 10)

    check_consul_cluster(con, hostname, flags.get("ignore_failed_checks"))
    check_consul_services(con, hostname, flags.get("ignore_failed_checks"), ["rebootmgr", "rebootmgr_preboot"])

    if not consul_lock.acquired:
        LOG.error("Lost consul lock. Exit")
        sys.exit(EXIT_CONSUL_LOST_LOCK)

    _check_and_handle_stop_flag(con, group, hostname, flags)

    if flags.get("check_triggers") and not is_reboot_required(con, hostname):
        sys.exit(0)

    if not flags.get("skip_reboot_in_progress_key"):
        if not flags.get("dryrun"):
            LOG.debug("Write %s in key %s" % (hostname, group_key))
            con.kv.put(group_key, hostname)
        else:
            LOG.debug("Would write %s in %s" % (hostname, group_key))

    consul_lock.release()


def get_config(con, hostname) -> dict:
    """
    Get the node's config data. It should be a JSON dictionary.

    If the config is absent, the rebootmgr should consider itself disabled.
    """
    idx, data = con.kv.get("service/rebootmgr/nodes/%s/config" % hostname)

    try:
        if data and "Value" in data.keys() and data["Value"]:
            config = json.loads(data["Value"].decode())
            if isinstance(config, dict):
                maybe_migrate_config(con, hostname, config)
                return config
    except Exception:
        pass

    LOG.error("Configuration data missing or malformed.")
    return {}


def maybe_migrate_config(con, hostname, config):
    if 'disabled' in config and 'enabled' not in config:
        config['enabled'] = not config['disabled']
        del config['disabled']
        put_config(con, hostname, config)


def put_config(con, hostname, config):
    con.kv.put("service/rebootmgr/nodes/%s/config" % hostname, json.dumps(config))


def config_is_present_and_valid(con, hostname) -> bool:
    """
    Checks if there is configuration for this node and does minimal validation.

    If the config is absent or not valid,
    the rebootmgr should consider itself disabled.
    """
    config = get_config(con, hostname)
    if 'enabled' not in config:
        return False

    return True


def ensure_configuration(con, hostname, dryrun) -> bool:
    """
    Make sure there is a configuration set up for this node.

    If there already is one that looks valid, don't change it.
    """
    if not config_is_present_and_valid(con, hostname):
        config = {
            "enabled": True,  # maybe default should be False?
            "message": "Default config created",
        }
        if not dryrun:
            put_config(con, hostname, config)
        return True
    return False


def getuser():
    user = os.environ.get('SUDO_USER')
    return user or getpass.getuser()


def do_set_global_stop_flag(con, dc, hostname, stop_reason):
    reason = f"Set by {getuser()}, {datetime.datetime.now()}, stop reason: {stop_reason}"
    con.kv.put("service/rebootmgr/stop", reason, dc=dc)
    chat_reaseon = f"Set global stop flag, {reason} in dc: {dc}"
    fire_chat_escalation(con, hostname, chat_reaseon, resolve_group_name(con, None, hostname))
    LOG.warning("Set %s global stop flag: %s", dc, reason)


def do_unset_global_stop_flag(con, dc):
    con.kv.delete("service/rebootmgr/stop", dc=dc)
    chat_reaseon = f"Unset global stop flag in dc: {dc}"
    fire_chat_escalation(con, None, chat_reaseon)
    LOG.warning("Remove %s global stop flag", dc)


def do_set_local_stop_flag(con, hostname, stop_reason):
    reason = f"Node disabled by {getuser()}, {datetime.datetime.now()}, stop reason: {stop_reason}"
    config = get_config(con, hostname)
    config["enabled"] = False
    config["message"] = reason
    put_config(con, hostname, config)
    chat_reaseon = f"Set local stop flag, {reason}"
    fire_chat_escalation(con, hostname, chat_reaseon, resolve_group_name(con, None, hostname))
    LOG.warning("Set %s local stop flag: %s", hostname, reason)


def do_unset_local_stop_flag(con, hostname):
    config = get_config(con, hostname)
    config["enabled"] = True
    config["message"] = ""
    put_config(con, hostname, config)
    chat_reaseon = "Unset local stop flag."
    fire_chat_escalation(con, hostname, chat_reaseon, resolve_group_name(con, None, hostname))
    LOG.warning("Unset %s local stop flag", hostname)


def do_set_group_stop_flag(con, group, hostname, stop_reason):
    group_name = resolve_group_name(con, group, hostname)
    if not group_name:
        LOG.error("No group configured. Cannot set group stop flag.")
        sys.exit(EXIT_STOP_FLAG_FAILED)
    stop_flag_key = f"service/rebootmgr/{group_name}_stop"
    reason = f"Set by {getuser()}, {datetime.datetime.now()}, stop reason: {stop_reason}"
    con.kv.put(stop_flag_key, reason)
    chat_reaseon = f"Set group stop flag, {reason} in consul key: {stop_flag_key}"
    fire_chat_escalation(con, hostname, chat_reaseon, group_name)
    LOG.warning("Set group '%s' stop flag: %s", group_name, reason)


def do_unset_group_stop_flag(con, group, hostname):
    group_name = resolve_group_name(con, group, hostname)
    if not group_name:
        LOG.error("No group configured. Cannot unset group stop flag.")
        sys.exit(EXIT_STOP_FLAG_FAILED)
    stop_flag_key = f"service/rebootmgr/{group_name}_stop"
    con.kv.delete(stop_flag_key)
    chat_reaseon = f"Unset group stop flag for consul key: {stop_flag_key}"
    fire_chat_escalation(con, hostname, chat_reaseon, group_name)
    LOG.warning("Remove group '%s' stop flag", group_name)


@click.command()
@click.option("-v", "--verbose", count=True, help="Once for INFO logging, twice for DEBUG")
@click.option("--check-triggers", help="Only reboot if a reboot is necessary", is_flag=True)
@click.option("-n", "--dryrun", help="Run tasks and check services but don't reboot", is_flag=True)
@click.option("-u", "--check-uptime", help="Make sure, that the uptime is less than 2 hours.", is_flag=True)
@click.option("-s", "--ignore-stop-flag", help="ignore the related stop flag (example service/rebootmgr/ceph_stop).", is_flag=True)
@click.option("--check-holidays", help="Don't reboot on holidays", is_flag=True)
@click.option("--post-reboot-wait-until-healthy", help="Wait until healthy in post reboot, instead of exit", is_flag=True)
@click.option("--lazy-consul-checks", help="Don't repeat consul checks after two minutes", is_flag=True)
@click.option("-l", "--ignore-node-disabled", help="ignore the node specific stop flag (service/rebootmgr/hostname/config)", is_flag=True)
@click.option("--ignore-failed-checks", help="Reboot even if consul checks fail", is_flag=True)
@click.option("--maintenance-reason", help="""Reason for the downtime in consul. If the text starts with "reboot", """ +
              "a 15 minute maintenance period is scheduled in zabbix\nDefault: reboot by rebootmgr",
              default="reboot by rebootmgr")
@click.option("--consul", metavar="CONSUL_IP_ADDR", help="Address of Consul. Default env REBOOTMGR_CONSUL_ADDR or 127.0.0.1.",
              default=os.environ.get("REBOOTMGR_CONSUL_ADDR", "127.0.0.1"))
@click.option("--consul-port", help="Port of Consul. Default env REBOOTMGR_CONSUL_PORT or 8500",
              default=os.environ.get("REBOOTMGR_CONSUL_PORT", 8500))
@click.option("--ensure-config", help="If there is no valid configuration in consul, create a default one.", is_flag=True)
@click.option("--set-global-stop-flag", metavar="CLUSTER", help="Stop the rebootmgr cluster-wide in the specified cluster")
@click.option("--unset-global-stop-flag", metavar="CLUSTER", help="Remove the cluster-wide stop flag in the specified cluster")
@click.option("--set-group-stop-flag", help="Stop the rebootmgr for this group (requires --group or group in node config)", is_flag=True)
@click.option("--unset-group-stop-flag", help="Remove the group stop flag (requires --group or group in node config)", is_flag=True)
@click.option("--set-local-stop-flag", help="Stop the rebootmgr on this node", is_flag=True)
@click.option("--unset-local-stop-flag", help="Remove the stop flag on this node", is_flag=True)
@click.option("--stop-reason", help="Reason to set the stop flag", default="stopped by rebootmgr")
@click.option("--skip-reboot-in-progress-key", help="Don't set the reboot_in_progress consul key before rebooting", is_flag=True)
@click.option("--task-timeout", help="Minutes that rebootmgr waits for each task to finish. Default are 120 minutes", default=120, type=int)
@click.option("--group", help="Group name this host belongs to in our infrastructure", default="", type=str)
@click.version_option()
def cli(verbose, consul, consul_port, check_triggers, check_uptime, dryrun, maintenance_reason, ignore_stop_flag,
        ignore_node_disabled, ignore_failed_checks, check_holidays, post_reboot_wait_until_healthy, lazy_consul_checks,
        ensure_config, set_global_stop_flag, unset_global_stop_flag, set_group_stop_flag, unset_group_stop_flag,
        set_local_stop_flag, unset_local_stop_flag, stop_reason,
        skip_reboot_in_progress_key, task_timeout, group):
    """Reboot Manager

    Default values of parameteres are environment variables (if set)
    """
    logsetup(verbose)

    con = Consul(host=consul, port=int(consul_port))
    hostname = socket.gethostname().split(".")[0]

    if ensure_config:
        if ensure_configuration(con, hostname, dryrun):
            LOG.warning("Created default configuration, "
                        "since it was missing or invalid. Exit.")
        else:
            LOG.debug("Did not create default configuration, "
                      "since there already was one. Exit.")
        sys.exit(0)

    # Map flags to their corresponding functions and arguments
    stop_flag_actions = {
        'set_global_stop_flag': (do_set_global_stop_flag, (con, set_global_stop_flag, hostname, stop_reason)),
        'unset_global_stop_flag': (do_unset_global_stop_flag, (con, unset_global_stop_flag)),
        'set_group_stop_flag': (do_set_group_stop_flag, (con, group, hostname, stop_reason)),
        'unset_group_stop_flag': (do_unset_group_stop_flag, (con, group, hostname)),
        'set_local_stop_flag': (do_set_local_stop_flag, (con, hostname, stop_reason)),
        'unset_local_stop_flag': (do_unset_local_stop_flag, (con, hostname)),
    }

    # Execute the first matching action
    for flag_name, (func, args) in stop_flag_actions.items():
        if locals()[flag_name]:
            func(*args)
            sys.exit(0)

    if not config_is_present_and_valid(con, hostname):
        LOG.error("The configuration of this node (%s) seems to be missing. "
                  "Exit." % hostname)
        sys.exit(EXIT_CONFIGURATION_IS_MISSING)

    flags = {"check_triggers": check_triggers,
             "check_uptime": check_uptime,
             "dryrun": dryrun,
             "maintenance_reason": maintenance_reason,
             "ignore_stop_flag": ignore_stop_flag,
             "ignore_node_disabled": ignore_node_disabled,
             "ignore_failed_checks": ignore_failed_checks,
             "check_holidays": check_holidays,
             "lazy_consul_checks": lazy_consul_checks,
             "skip_reboot_in_progress_key": skip_reboot_in_progress_key,
             "group": group}

    check_consul_cluster(con, hostname, ignore_failed_checks)

    lock_key = resolve_lock(con, group, hostname)
    # Explicitly disable all health checks on the session. Some scripts may
    # cause a short network outage and we don't want a short failing serfHealth
    # to invalidate our lock for that.  We rely on the TTL to invalidate the
    # session in case of disasters.
    session = con.session.create(ttl=600, checks=[])
    consul_lock = Lock(con, lock_key, session=session)

    LOG.debug("Starting session_renewer.")
    consul_lock.session_renewer = SessionRenewer(session, con)
    consul_lock.session_renewer.start()

    try:
        # Try to get Lock without waiting
        if not consul_lock.acquire(blocking=False):
            LOG.error("Could not get consul lock. Exit.")
            sys.exit(EXIT_CONSUL_LOCK_FAILED)

        reboot_in_progress = check_reboot_in_progress(con, group, hostname)

        if reboot_in_progress:
            if reboot_in_progress.startswith(hostname):
                # We are in post_reboot state
                post_reboot_state(con, consul_lock, hostname, flags, post_reboot_wait_until_healthy, task_timeout, group)
                sys.exit(0)
            # Another node has the lock
            else:
                LOG.info("Another Node %s is rebooting. Exit." % reboot_in_progress)
                sys.exit(EXIT_CONSUL_LOCK_FAILED)
        # consul-key reboot_in_progress does not exist
        # we are free to reboot
        else:
            # We are in pre_reboot state
            pre_reboot_state(con, consul_lock, hostname, flags, task_timeout, group)
            group_key = resolve_group_key(con, group, hostname)
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
                    LOG.error("Remove consul key %s" % group_key)
                    con.kv.delete(group_key)
                    raise e
    finally:
        consul_lock.release()


if __name__ == "__main__":
    cli()  # pragma: no cover
