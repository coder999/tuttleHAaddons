from __future__ import annotations

from flask import Flask, render_template

from app.event_log import EventLog


def create_app(event_log: EventLog) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            events=event_log.recent_events(),
            state=event_log.current_state(),
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
