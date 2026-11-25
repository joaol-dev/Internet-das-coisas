import argparse
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psycopg
import serial
from psycopg.rows import dict_row

WEB = Path(__file__).resolve().parent / "web"
DSN = os.getenv("DATABASE_URL", "postgresql://irrigacao:irrigacao_local@127.0.0.1:5432/irrigacao")
LOG = logging.getLogger(__name__)
DRY_THRESHOLD = 40
WATER_SECONDS = 3
REST_SECONDS = 5
HISTORY_INTERVAL_SECONDS = 60


def initialize_database():
    with psycopg.connect(DSN) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS leituras (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                instante timestamptz NOT NULL DEFAULT clock_timestamp(),
                umidade smallint NOT NULL CHECK (umidade BETWEEN 0 AND 100),
                luz smallint NOT NULL CHECK (luz BETWEEN 0 AND 100),
                bomba boolean NOT NULL,
                modo text NOT NULL CHECK (modo IN ('AUTO', 'PAUSE')),
                fonte text NOT NULL CHECK (fonte IN ('arduino', 'simulacao'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS leituras_fonte_instante ON leituras (fonte, instante DESC, id DESC)")


class Device:
    def __init__(self, port):
        self.port = port
        self.source = "arduino" if port else "simulacao"
        self.lock = threading.Lock()
        self.connection = None
        self.latest = None
        self.received = 0
        self.sequence = 0
        self.saved_id = None
        self.saved_sample = None
        self.saved_at = 0
        self.moisture = 42
        self.light = 68
        self.mode = "AUTO"
        self.dry_since = None

    def status(self):
        with self.lock:
            online = self.latest is not None and time.monotonic() - self.received < 5
            return {
                "fonte": self.source, "online": online, "leitura": self.latest,
                "ultima_gravacao": self.saved_id,
            }

    def change_mode(self, mode):
        with self.lock:
            if not self.port:
                self.mode = mode
                if mode == "PAUSE":
                    self.dry_since = None
            else:
                if self.connection is None or time.monotonic() - self.received >= 5:
                    raise ConnectionError("Arduino sem comunicação")
                self.connection.write((mode + "\n").encode("ascii"))
            return self.sequence

    def set_inputs(self, moisture, light):
        if self.port:
            raise ValueError("Disponível apenas na simulação")
        with self.lock:
            self.moisture, self.light = moisture, light
            if moisture >= DRY_THRESHOLD:
                self.dry_since = None

    def record(self, moisture, light, pump, mode):
        now = time.monotonic()
        timestamp = datetime.now(timezone.utc)
        sample = (moisture, light, pump, mode)
        with self.lock:
            self.sequence += 1
            self.latest = {
                "sequencia": self.sequence, "instante": timestamp, "umidade": moisture,
                "luz": light, "bomba": pump, "modo": mode, "fonte": self.source,
            }
            self.received = now
        if sample == self.saved_sample and now - self.saved_at < HISTORY_INTERVAL_SECONDS:
            return
        try:
            with psycopg.connect(DSN) as db:
                (saved_id,) = db.execute("""
                    INSERT INTO leituras (instante, umidade, luz, bomba, modo, fonte)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """, (timestamp, *sample, self.source)).fetchone()
        except psycopg.Error:
            LOG.warning("Não foi possível gravar a leitura no histórico", exc_info=True)
            return
        with self.lock:
            self.saved_id = saved_id
            self.saved_sample = sample
            self.saved_at = now

    def simulate(self):
        while True:
            with self.lock:
                now = time.monotonic()
                dry = self.mode == "AUTO" and self.moisture < DRY_THRESHOLD
                if dry and self.dry_since is None:
                    self.dry_since = now
                pump = dry and (now - self.dry_since) % (WATER_SECONDS + REST_SECONDS) < WATER_SECONDS
                sample = self.moisture, self.light, pump, self.mode
            self.record(*sample)
            time.sleep(1)

    def read_serial(self):
        try:
            with serial.Serial(self.port, 9600, timeout=1, write_timeout=1) as connection:
                with self.lock:
                    self.connection = connection
                while True:
                    line = connection.read_until(b"\n", 128)
                    if not line.endswith(b"\n"):
                        continue
                    try:
                        tag, moisture, light, pump, mode = line.decode("ascii").strip().split(",")
                        moisture, light = int(moisture), int(light)
                        if (tag != "DATA" or not 0 <= moisture <= 100 or not 0 <= light <= 100
                                or pump not in ("0", "1") or mode not in ("AUTO", "PAUSE")):
                            continue
                    except (ValueError, UnicodeError):
                        continue
                    self.record(moisture, light, pump == "1", mode)
        finally:
            with self.lock:
                self.connection = None
                self.received = 0

    def run(self):
        while True:
            try:
                if self.port:
                    self.read_serial()
                else:
                    self.simulate()
            except (serial.SerialException, OSError, psycopg.Error) as error:
                LOG.warning("Falha na aquisição: %s", error)
                time.sleep(2)


def history(source, query):
    clauses, args = ["fonte = %s"], [source]
    for key, operator in (("inicio", ">="), ("fim", "<")):
        if key in query:
            value = datetime.fromisoformat(query[key][0])
            if value.tzinfo is None:
                raise ValueError("Informe uma data com fuso horário")
            clauses.append(f"instante {operator} %s")
            args.append(value)
    for key, column, operator in (
        ("umidade_max", "umidade", "<="), ("umidade_min", "umidade", ">="),
        ("luz_min", "luz", ">="), ("luz_max", "luz", "<="),
    ):
        if key in query:
            value = int(query[key][0])
            if not 0 <= value <= 100:
                raise ValueError("Use uma porcentagem entre 0 e 100")
            clauses.append(f"{column} {operator} %s")
            args.append(value)
    if "bomba" in query:
        if query["bomba"][0] not in ("on", "off"):
            raise ValueError("Estado de bomba inválido")
        clauses.append("bomba = %s")
        args.append(query["bomba"][0] == "on")
    limit = int(query.get("limite", ["20"])[0])
    if not 1 <= limit <= 100:
        raise ValueError("Limite inválido")
    if "cursor" in query:
        instant, row_id = query["cursor"][0].split("|")
        timestamp = datetime.fromisoformat(instant)
        if timestamp.tzinfo is None:
            raise ValueError("Cursor inválido")
        clauses.append("(instante, id) < (%s, %s)")
        args.extend([timestamp, int(row_id)])
    where = " AND ".join(clauses)
    with psycopg.connect(DSN, row_factory=dict_row) as db:
        rows = db.execute(f"""
            SELECT * FROM leituras WHERE {where}
            ORDER BY instante DESC, id DESC LIMIT %s
        """, [*args, limit + 1]).fetchall()
    next_cursor = None
    if len(rows) > limit:
        rows.pop()
        next_cursor = f"{rows[-1]['instante'].isoformat()}|{rows[-1]['id']}"
    return {"leituras": rows, "proximo": next_cursor}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def reply(self, status, data):
        body = json.dumps(data, default=datetime.isoformat, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/status":
            self.reply(200, self.server.device.status())
        elif url.path == "/api/leituras":
            try:
                self.reply(200, history(self.server.device.source, parse_qs(url.query)))
            except (ValueError, OverflowError) as error:
                self.reply(400, {"erro": str(error)})
            except psycopg.Error:
                LOG.exception("Falha ao consultar histórico")
                self.reply(503, {"erro": "Banco de dados indisponível"})
        else:
            super().do_GET()

    def do_POST(self):
        if self.headers.get_content_type() != "application/json":
            self.reply(415, {"erro": "Envie JSON"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 1024:
                raise ValueError("Tamanho da requisição inválido")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Dados inválidos")
            if self.path == "/api/modo":
                mode = body.get("modo")
                if mode not in ("AUTO", "PAUSE"):
                    raise ValueError("Modo inválido")
                last_id = self.server.device.change_mode(mode)
                self.reply(202, {"enviado": True, "ultima_leitura": last_id})
                return
            elif self.path == "/api/simulacao":
                moisture, light = body.get("umidade"), body.get("luz")
                if any(type(value) is not int or not 0 <= value <= 100 for value in (moisture, light)):
                    raise ValueError("Use valores inteiros entre 0 e 100")
                self.server.device.set_inputs(moisture, light)
            else:
                self.reply(404, {"erro": "Rota desconhecida"})
                return
            self.reply(202, {"enviado": True})
        except (ValueError, UnicodeError) as error:
            self.reply(400, {"erro": str(error)})
        except (ConnectionError, serial.SerialException):
            self.reply(503, {"erro": "Arduino sem comunicação"})


def main():
    parser = argparse.ArgumentParser(description="Painel local de irrigação")
    parser.add_argument("--serial", help="Porta do Arduino, por exemplo /dev/ttyACM0 ou COM3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    initialize_database()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.device = Device(args.serial)
        threading.Thread(target=server.device.run, daemon=True).start()
        LOG.info("Painel em http://%s:%s (%s)", args.host, args.port, server.device.source)
        server.serve_forever()


if __name__ == "__main__":
    main()
