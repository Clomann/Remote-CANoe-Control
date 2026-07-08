import hmac
import os
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError
from pathlib import Path
from typing import Any, Callable

import pythoncom
import win32com.client
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


API_KEY = os.environ["CANOE_API_KEY"]
CONFIG_ROOT = Path(
    os.environ.get("CANOE_CONFIG_ROOT", r"C:\CANoeConfigs")
).resolve()

api = FastAPI(title="CANoe REST Bridge", version="1.0")


class OpenConfigurationRequest(BaseModel):
    configuration: str


class MeasurementRequest(BaseModel):
    wait_seconds: float = Field(default=30, ge=1, le=300)


class CanoeWorker:
    """
    Executes all CANoe COM operations on one dedicated COM thread.

    This avoids concurrent access to CANoe from different HTTP worker threads.
    """

    def __init__(self) -> None:
        self._commands: queue.Queue[
            tuple[Callable[[Any], Any], Future]
        ] = queue.Queue()

        self._thread = threading.Thread(
            target=self._worker_loop,
            name="canoe-com-worker",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _connect_to_canoe():
        try:
            # Attach to an already-running CANoe instance.
            return win32com.client.GetActiveObject("CANoe.Application")
        except Exception:
            # Otherwise start a new CANoe instance.
            application = win32com.client.DispatchEx("CANoe.Application")
            application.Visible = True
            return application

    def _worker_loop(self) -> None:
        pythoncom.CoInitialize()

        try:
            application = None

            while True:
                operation, future = self._commands.get()

                try:
                    if application is None:
                        application = self._connect_to_canoe()

                    result = operation(application)
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc)
        finally:
            pythoncom.CoUninitialize()

    def execute(
        self,
        operation: Callable[[Any], Any],
        timeout: float = 60,
    ) -> Any:
        future: Future = Future()
        self._commands.put((operation, future))
        return future.result(timeout=timeout)


canoe = CanoeWorker()


def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> None:
    if not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")


def validate_configuration_path(value: str) -> str:
    path = Path(value).resolve()

    try:
        inside_root = (
            os.path.commonpath([str(CONFIG_ROOT), str(path)])
            == str(CONFIG_ROOT)
        )
    except ValueError:
        inside_root = False

    if not inside_root:
        raise HTTPException(
            status_code=400,
            detail=f"Configuration must be below {CONFIG_ROOT}",
        )

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Configuration file not found",
        )

    return str(path)


def wait_for_measurement(
    application,
    expected_running: bool,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    while bool(application.Measurement.Running) != expected_running:
        pythoncom.PumpWaitingMessages()

        if time.monotonic() >= deadline:
            raise TimeoutError("CANoe measurement state change timed out")

        time.sleep(0.1)


def execute_com(operation, timeout: float = 60):
    try:
        return canoe.execute(operation, timeout=timeout)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@api.get("/health")
def health():
    return {"service": "up"}


@api.get("/canoe/status", dependencies=[Depends(require_api_key)])
def canoe_status():
    def operation(application):
        return {
            "connected": True,
            "measurement_running": bool(application.Measurement.Running),
        }

    return execute_com(operation)


@api.post("/canoe/configuration/open", dependencies=[Depends(require_api_key)])
def open_configuration(request: OpenConfigurationRequest):
    configuration = validate_configuration_path(request.configuration)

    def operation(application):
        if application.Measurement.Running:
            raise RuntimeError(
                "Stop the measurement before opening a configuration"
            )

        application.Open(configuration)

        return {
            "opened": True,
            "configuration": configuration,
        }

    return execute_com(operation, timeout=120)


@api.post("/canoe/measurement/start", dependencies=[Depends(require_api_key)])
def start_measurement(request: MeasurementRequest):
    def operation(application):
        if not application.Measurement.Running:
            application.Measurement.Start()
            wait_for_measurement(
                application,
                expected_running=True,
                timeout_seconds=request.wait_seconds,
            )

        return {"measurement_running": True}

    return execute_com(operation, timeout=request.wait_seconds + 10)


@api.post("/canoe/measurement/stop", dependencies=[Depends(require_api_key)])
def stop_measurement(request: MeasurementRequest):
    def operation(application):
        if application.Measurement.Running:
            application.Measurement.Stop()
            wait_for_measurement(
                application,
                expected_running=False,
                timeout_seconds=request.wait_seconds,
            )

        return {"measurement_running": False}

    return execute_com(operation, timeout=request.wait_seconds + 10)
