"""Migrations must not silence the application's loggers.

``fileConfig`` defaults to ``disable_existing_loggers=True``, which disables
every logger that already existed -- and module-level loggers are created at
import time, long before a migration runs.  The failure is silent: the service
keeps working and simply stops logging.
"""

import importlib
import logging

MODULES = (
    "agent_memory.api.middleware",
    "agent_memory.application.explicit_memory",
    "agent_memory.application.event_ingestion",
    "agent_memory.application.extraction_worker",
    "agent_memory.workers.extraction",
)

LOGGER_NAMES = (
    "agent_memory.api",
    "agent_memory.application.memory",
    "agent_memory.application.events",
    "agent_memory.application.extraction_worker",
    "agent_memory.workers.extraction",
)


def test_application_loggers_survive_alembic_upgrade(app_database_url: str) -> None:
    assert app_database_url  # the fixture is what runs `alembic upgrade head`
    for module in MODULES:  # the loggers exist only once their module is imported
        importlib.import_module(module)

    disabled = [name for name in LOGGER_NAMES if logging.getLogger(name).disabled]
    assert disabled == []
