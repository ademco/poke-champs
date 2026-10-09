"""Flask app: a one-page UI plus a small JSON API (the MVP).

Spring Boot analogy: `create_app` is the application context, each route is a
controller method, and the dependencies (DB connection, embedder, LLM) are
injected through `app.config` so tests can swap in fakes.

  GET  /             the page (team box + question box)
  GET  /health       is the database reachable, which regulation, is the LLM on
  POST /api/analyze  {"team": "...", "game_type": "doubles"|"singles"}  (no LLM)
  POST /api/ask      {"question": "..."}  (needs ANTHROPIC_API_KEY)

Usage: make web  (then open http://localhost:5000)
"""

import os
from pathlib import Path

from flask import Flask, jsonify, request

from pokechamp.analyze import analyze_team, render
from pokechamp.answer.llm import ClaudeLLM, LLMError
from pokechamp.answer.pipeline import MAX_QUESTION_CHARS, ask
from pokechamp.db import connect
from pokechamp.regulations import current_regulation
from pokechamp.tools.repo import DbFacts
from pokechamp.tools.team_parser import TeamParseError

PAGE = Path(__file__).with_name("index.html")
MAX_TEAM_CHARS = 20_000


def _default_llm():
    try:
        return ClaudeLLM()
    except LLMError:
        return None  # no key: /api/ask explains, everything else still works


def create_app(connect_fn=connect, embedder=None, llm="auto") -> Flask:
    app = Flask(__name__)
    app.config["CONNECT"] = connect_fn
    app.config["EMBEDDER"] = embedder  # loaded on first question (~1 s, ~150 MB)
    app.config["LLM"] = _default_llm() if llm == "auto" else llm

    def embedder_():
        if app.config["EMBEDDER"] is None:
            from pokechamp.rag.embeddings import get_embedder

            app.config["EMBEDDER"] = get_embedder()
        return app.config["EMBEDDER"]

    @app.get("/")
    def index():
        return PAGE.read_text(encoding="utf-8")

    @app.get("/health")
    def health():
        try:
            with app.config["CONNECT"]() as conn:
                conn.execute("SELECT 1")
            db = True
        except Exception:
            db = False
        body = {
            "status": "ok" if db else "degraded",
            "database": db,
            "regulation": current_regulation().code,
            "questions_enabled": app.config["LLM"] is not None,
        }
        return jsonify(body), 200 if db else 503

    @app.post("/api/analyze")
    def analyze():
        data = request.get_json(silent=True) or {}
        team = data.get("team", "")
        game_type = data.get("game_type", "doubles")
        if not isinstance(team, str) or not team.strip() or len(team) > MAX_TEAM_CHARS:
            return jsonify(error=f"'team' must be 1-{MAX_TEAM_CHARS} characters"), 400
        if game_type not in ("doubles", "singles"):
            return jsonify(error="'game_type' must be 'doubles' or 'singles'"), 400
        try:
            with app.config["CONNECT"]() as conn:
                report = analyze_team(DbFacts(conn), team, game_type)
        except TeamParseError as exc:
            return jsonify(error=f"could not read the team: {exc}"), 400
        return jsonify(report.to_json() | {"text": render(report)})

    @app.post("/api/ask")
    def ask_():
        if app.config["LLM"] is None:
            return jsonify(
                error="Questions need a Claude API key: set ANTHROPIC_API_KEY in .env"
                " and restart. Team analysis works without it."
            ), 503
        data = request.get_json(silent=True) or {}
        question = data.get("question", "")
        if not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION_CHARS:
            return jsonify(error=f"'question' must be 1-{MAX_QUESTION_CHARS} characters"), 400
        with app.config["CONNECT"]() as conn:
            result = ask(question, conn, embedder_(), app.config["LLM"])
        if result.answer is None:
            return jsonify(error="the model did not return a usable answer"), 502
        a = result.answer
        return jsonify(
            status=a.status,
            answer=a.answer,
            regulation=a.regulation,
            claims=[c.model_dump() for c in a.claims],
            sources=[
                {
                    "id": e.id,
                    "title": e.title,
                    "source": e.source,
                    "license": e.license,
                    "ref": e.ref,
                    "text": e.text,
                }
                for e in result.cited()
            ],  # fmt: skip
            warnings=result.problems,
            model=result.model,
        )

    return app


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    create_app().run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
