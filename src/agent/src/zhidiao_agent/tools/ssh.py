"""Shared strict, noninteractive OpenSSH options for the Zynq transports."""

import json
from pathlib import Path

from ..deployment import DeploymentConfig
from ..errors import AgentError, ErrorCode


def ssh_options(config: DeploymentConfig) -> tuple[str, ...]:
    if not config.known_hosts or not Path(config.known_hosts).is_file():
        raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configure a verified SSH known_hosts file.")
    hosts_option = "UserKnownHostsFile=" + json.dumps(Path(config.known_hosts).as_posix(), ensure_ascii=False)
    options = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", hosts_option, "-o", "ConnectTimeout=10")
    if config.allow_legacy_rsa:
        options += ("-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa")
    if config.identity_file:
        if not Path(config.identity_file).is_file():
            raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Configured SSH identity file is missing.")
        options += ("-i", config.identity_file, "-o", "IdentitiesOnly=yes")
    return options


def ssh_command(config: DeploymentConfig) -> tuple[str, ...]:
    return ("ssh", *ssh_options(config), "-p", str(config.port), config.user + "@" + config.host)
