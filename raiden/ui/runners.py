import signal
from typing import Any, Dict, List, Optional

import gevent
import gevent.monkey
import structlog
from click import Context
from gevent.event import AsyncResult

from raiden import constants, settings
from raiden.api.python import RaidenAPI
from raiden.log_config import configure_logging
from raiden.tasks import check_gas_reserve, check_network_id, check_rdn_deposits, check_version
from raiden.ui.app import run_app
from raiden.ui.config import dump_cmd_options, dump_module
from raiden.utils.gevent import spawn_named
from raiden.utils.system import get_system_spec

log = structlog.get_logger(__name__)


class NodeRunner:
    def __init__(self, options: Dict[str, Any], ctx: Context) -> None:
        self._options = options
        self._ctx = ctx
        self.raiden_api: Optional[RaidenAPI] = None

    @property
    def welcome_string(self) -> str:
        return f"Welcome to Raiden, version {get_system_spec()['raiden']}!"

    def run(self) -> None:
        configure_logging(
            self._options["log_config"],
            log_json=self._options["log_json"],
            log_file=self._options["log_file"],
            disable_debug_logfile=self._options["disable_debug_logfile"],
            debug_log_file_path=self._options["debug_logfile_path"],
        )

        log.info("Starting Raiden", **get_system_spec())

        if self._options["config_file"]:
            log.debug("Using config file", config_file=self._options["config_file"])

        self._start_services()

    def _start_services(self) -> None:
        if self._options["showconfig"]:
            print("Configuration Dump:")
            dump_cmd_options(self._options)
            dump_module("settings", settings)
            dump_module("constants", constants)

        app = run_app(**self._options)

        gevent_tasks: List[gevent.Greenlet] = list()

        if self._options["console"]:
            from raiden.ui.console import Console

            console = Console(app)
            console.start()

            gevent_tasks.append(console)

        gevent_tasks.append(
            spawn_named("check_version", check_version, get_system_spec()["raiden"])
        )
        gevent_tasks.append(spawn_named("check_gas_reserve", check_gas_reserve, app.raiden))
        gevent_tasks.append(
            spawn_named(
                "check_network_id",
                check_network_id,
                app.raiden.rpc_client.chain_id,
                app.raiden.rpc_client.web3,
            )
        )

        spawn_user_deposit_task = app.user_deposit and (
            self._options["pathfinding_service_address"] or self._options["enable_monitoring"]
        )
        if spawn_user_deposit_task:
            gevent_tasks.append(
                spawn_named("check_rdn_deposits", check_rdn_deposits, app.raiden, app.user_deposit)
            )

        stop_event: AsyncResult[Optional[signal.Signals]]  # pylint: disable=no-member
        stop_event = AsyncResult()

        def sig_set(sig: int, _frame: Any = None) -> None:
            stop_event.set(signal.Signals(sig))  # pylint: disable=no-member

        gevent.signal.signal(signal.SIGQUIT, sig_set)  # pylint: disable=no-member
        gevent.signal.signal(signal.SIGTERM, sig_set)  # pylint: disable=no-member
        gevent.signal.signal(signal.SIGINT, sig_set)  # pylint: disable=no-member
        gevent.signal.signal(signal.SIGPIPE, sig_set)  # pylint: disable=no-member

        # quit if any task exits, successfully or not
        app.raiden.greenlet.link(stop_event)
        for task in gevent_tasks:
            task.link(stop_event)

        try:
            signal_received = stop_event.get()
            if signal_received:
                print("\r", end="")  # Reset cursor to overwrite a possibly printed "^C"
                log.info(f"Signal received. Shutting down.", signal=signal_received)
        finally:
            for task in gevent_tasks:
                task.kill()

            app.raiden.stop()

            gevent.joinall(
                set(gevent_tasks + [app.raiden]), app.config.shutdown_timeout, raise_error=True
            )

            app.stop()
