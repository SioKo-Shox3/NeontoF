"""単一workerのUvicorn entrypointを提供する。"""

import argparse
import os
import signal
from collections.abc import Sequence
from types import FrameType

import uvicorn

from neontof.app import create_app
from neontof.config import load_server_options

_ENVIRONMENT_KEYS = ("NEONTOF_HOST", "NEONTOF_PORT", "NEONTOF_WORKERS")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NeontoF health application.")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workers", type=int)
    return parser


def _handle_ctrl_break(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    signal.raise_signal(signal.SIGINT)


def _install_ctrl_break_handler() -> None:
    ctrl_break = getattr(signal, "SIGBREAK", None)
    if ctrl_break is not None:
        signal.signal(ctrl_break, _handle_ctrl_break)


def main(argv: Sequence[str] | None = None) -> None:
    """CLI引数と許可された環境変数を検証してUvicornを起動する。"""

    parser = _build_parser()
    arguments = parser.parse_args(argv)
    environment = {key: os.environ[key] for key in _ENVIRONMENT_KEYS if key in os.environ}
    if arguments.host is not None:
        environment["NEONTOF_HOST"] = arguments.host
    if arguments.port is not None:
        environment["NEONTOF_PORT"] = str(arguments.port)
    if arguments.workers is not None:
        environment["NEONTOF_WORKERS"] = str(arguments.workers)

    try:
        options = load_server_options(environment)
    except ValueError as error:
        parser.error(str(error))

    _install_ctrl_break_handler()
    uvicorn.run(
        create_app(),
        host=options.host,
        port=options.port,
        workers=options.workers,
        log_config=None,
        access_log=False,
        log_level="critical",
    )


if __name__ == "__main__":
    main()
