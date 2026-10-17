from fastapi import FastAPI

from ...errors import Unavailable


def register(app: FastAPI, db) -> None:
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/readyz")
    def readyz() -> dict:
        if not db.ping():
            raise Unavailable("db not reachable")
        if db.module_version() != 42201:
            raise Unavailable("required database module unavailable")
        return {"ready": True}
