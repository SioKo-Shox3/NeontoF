import os
import signal

import pytest
import uvicorn

import neontof.main as main_module


def test_main_passes_single_worker_and_silent_logging_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(application: object, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("NEONTOF_HOST", "127.0.0.1")
    monkeypatch.setenv("NEONTOF_PORT", "8765")
    monkeypatch.setenv("NEONTOF_WORKERS", "1")

    main_module.main(["--host", "localhost", "--port", "9000", "--workers", "1"])

    assert callable(captured["application"])
    assert captured["host"] == "localhost"
    assert captured["port"] == 9000
    assert captured["workers"] == 1
    assert captured["access_log"] is False
    assert captured["log_config"] is None
    assert captured["log_level"] == "critical"


def test_main_rejects_wrong_worker_count_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uvicorn_called = False

    def fake_run(application: object, **kwargs: object) -> None:
        nonlocal uvicorn_called
        del application, kwargs
        uvicorn_called = True

    monkeypatch.setattr(uvicorn, "run", fake_run)

    with pytest.raises(SystemExit) as error:
        main_module.main(["--workers", "2"])

    assert error.value.code == 2
    assert uvicorn_called is False


def test_main_rejects_invalid_environment_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(application: object, **kwargs: object) -> None:
        del application, kwargs
        raise AssertionError("uvicorn must not start for invalid options")

    monkeypatch.setattr(uvicorn, "run", fail_run)
    monkeypatch.setenv("NEONTOF_PORT", "65536")

    with pytest.raises(SystemExit) as error:
        main_module.main([])

    assert error.value.code == 2


def test_main_reads_only_the_three_server_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_keys: list[str] = []
    original_environ = os.environ

    class TrackingEnvironment(dict[str, str]):
        def __contains__(self, key: object) -> bool:
            if isinstance(key, str):
                read_keys.append(key)
            return super().__contains__(key)

        def __getitem__(self, key: str) -> str:
            read_keys.append(key)
            return super().__getitem__(key)

    tracking_environment = TrackingEnvironment(original_environ)
    monkeypatch.setattr(os, "environ", tracking_environment)

    def ignore_run(application: object, **kwargs: object) -> None:
        del application, kwargs

    monkeypatch.setattr(uvicorn, "run", ignore_run)

    main_module.main([])

    terminal_layout_keys = {"COLUMNS", "LINES"}
    assert set(read_keys) - terminal_layout_keys <= {
        "NEONTOF_HOST",
        "NEONTOF_PORT",
        "NEONTOF_WORKERS",
    }


def test_main_maps_windows_ctrl_break_to_uvicorn_sigint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl_break = getattr(signal, "SIGBREAK", None)
    if ctrl_break is None:
        pytest.skip("SIGBREAK is Windows-specific")

    registered_signals: list[object] = []
    registered_handlers: list[object] = []
    raised_signals: list[object] = []

    def fake_signal(signum: object, handler: object) -> object:
        registered_signals.append(signum)
        registered_handlers.append(handler)
        return signal.SIG_DFL

    def fake_raise(signum: object) -> None:
        raised_signals.append(signum)

    def ignore_run(application: object, **kwargs: object) -> None:
        del application, kwargs

    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr(signal, "raise_signal", fake_raise)
    monkeypatch.setattr(uvicorn, "run", ignore_run)

    main_module.main([])

    assert registered_signals == [ctrl_break]
    registered_handler = registered_handlers[0]
    assert callable(registered_handler)
    registered_handler(ctrl_break, None)
    assert raised_signals == [signal.SIGINT]
