import json
import logging
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app import DRY_THRESHOLD, HISTORY_INTERVAL_SECONDS, REST_SECONDS, WATER_SECONDS, history

LOG = logging.getLogger(__name__)


def status(db, session):
    db.execute(
        "INSERT INTO raiz_sessoes_web (id) VALUES (%s) ON CONFLICT DO NOTHING",
        (session,),
    )
    state = db.execute(
        "SELECT * FROM raiz_sessoes_web WHERE id = %s FOR UPDATE", (session,)
    ).fetchone()
    now = db.execute("SELECT clock_timestamp() AS instante").fetchone()["instante"]
    start = state["inicio_ciclo"]
    dry = state["modo"] == "AUTO" and state["umidade"] < DRY_THRESHOLD
    if dry and start is None:
        start = now
    pump = dry and (now - start).total_seconds() % (WATER_SECONDS + REST_SECONDS) < WATER_SECONDS
    sequence = state["sequencia"] + 1
    reading = {
        "sequencia": sequence, "instante": now, "umidade": state["umidade"],
        "luz": state["luz"], "bomba": pump, "modo": state["modo"], "fonte": "simulacao",
    }
    previous = db.execute("""
        SELECT instante, umidade, luz, bomba, modo
        FROM raiz_leituras_web WHERE id = %s
    """, (state["ultima_gravacao"],)).fetchone()
    saved_id = state["ultima_gravacao"]
    fields = ("umidade", "luz", "bomba", "modo")
    if (previous is None or (now - previous["instante"]).total_seconds() >= HISTORY_INTERVAL_SECONDS
            or any(previous[field] != reading[field] for field in fields)):
        saved_id = db.execute("""
            INSERT INTO raiz_leituras_web (sessao, instante, umidade, luz, bomba, modo)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (session, now, *(reading[field] for field in fields))).fetchone()["id"]
    db.execute("""
        UPDATE raiz_sessoes_web SET sequencia = %s, inicio_ciclo = %s, ultima_gravacao = %s
        WHERE id = %s
    """, (sequence, start if dry else None, saved_id, session))
    return {
        "fonte": "simulacao", "hospedado": True, "online": True, "leitura": reading,
        "ultima_gravacao": saved_id,
    }


class handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data, default=datetime.isoformat, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        action = query.get("acao", [url.path.rsplit("/", 1)[-1]])[0]
        try:
            session = UUID(self.headers.get("X-Raiz-Sessao", ""))
        except ValueError:
            self.reply(400, {"erro": "Sessão de simulação inválida"})
            return
        if not os.getenv("DATABASE_URL"):
            self.reply(503, {"erro": "Configure DATABASE_URL na Vercel"})
            return

        try:
            if self.command == "GET" and action == "leituras":
                self.reply(200, history("simulacao", query, session=session))
            elif self.command == "GET" and action == "status":
                with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
                    result = status(db, session)
                self.reply(200, result)
            elif self.command == "POST" and action in ("modo", "simulacao"):
                self.update_session(action, session)
            else:
                self.reply(404, {"erro": "Rota desconhecida"})
        except (ValueError, OverflowError) as error:
            self.reply(400, {"erro": str(error)})
        except psycopg.errors.UndefinedTable:
            self.reply(503, {"erro": "Execute api/neon.sql no banco configurado"})
        except psycopg.Error:
            LOG.exception("Falha na conexão com o PostgreSQL")
            self.reply(503, {"erro": "Banco de dados indisponível"})

    do_GET = do_POST = dispatch

    def update_session(self, action, session):
        if self.headers.get_content_type() != "application/json":
            self.reply(415, {"erro": "Envie JSON"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 1 <= length <= 1024:
            raise ValueError("Tamanho da requisição inválido")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("Dados inválidos")
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
            if action == "modo":
                mode = body.get("modo")
                if mode not in ("AUTO", "PAUSE"):
                    raise ValueError("Modo inválido")
                row = db.execute("""
                    UPDATE raiz_sessoes_web
                    SET modo = %s, inicio_ciclo = CASE WHEN %s = 'PAUSE' THEN NULL ELSE inicio_ciclo END
                    WHERE id = %s RETURNING sequencia
                """, (mode, mode, session)).fetchone()
            else:
                moisture, light = body.get("umidade"), body.get("luz")
                if any(type(value) is not int or not 0 <= value <= 100 for value in (moisture, light)):
                    raise ValueError("Use valores inteiros entre 0 e 100")
                row = db.execute("""
                    UPDATE raiz_sessoes_web SET umidade = %s, luz = %s,
                        inicio_ciclo = CASE WHEN %s >= %s THEN NULL ELSE inicio_ciclo END
                    WHERE id = %s RETURNING sequencia
                """, (moisture, light, moisture, DRY_THRESHOLD, session)).fetchone()
        if row is None:
            self.reply(409, {"erro": "Aguarde a primeira leitura da simulação"})
        else:
            self.reply(202, {"enviado": True, "ultima_leitura": row["sequencia"]})
