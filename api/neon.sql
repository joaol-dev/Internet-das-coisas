CREATE TABLE IF NOT EXISTS raiz_sessoes_web (
    id uuid PRIMARY KEY,
    umidade smallint NOT NULL DEFAULT 42 CHECK (umidade BETWEEN 0 AND 100),
    luz smallint NOT NULL DEFAULT 68 CHECK (luz BETWEEN 0 AND 100),
    modo text NOT NULL DEFAULT 'AUTO' CHECK (modo IN ('AUTO', 'PAUSE')),
    inicio_ciclo timestamptz,
    sequencia bigint NOT NULL DEFAULT 0,
    ultima_gravacao bigint
);

CREATE TABLE IF NOT EXISTS raiz_leituras_web (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sessao uuid NOT NULL REFERENCES raiz_sessoes_web(id) ON DELETE CASCADE,
    instante timestamptz NOT NULL,
    umidade smallint NOT NULL CHECK (umidade BETWEEN 0 AND 100),
    luz smallint NOT NULL CHECK (luz BETWEEN 0 AND 100),
    bomba boolean NOT NULL,
    modo text NOT NULL CHECK (modo IN ('AUTO', 'PAUSE')),
    fonte text NOT NULL DEFAULT 'simulacao' CHECK (fonte = 'simulacao')
);

CREATE INDEX IF NOT EXISTS raiz_leituras_web_sessao_instante
    ON raiz_leituras_web (sessao, instante DESC, id DESC);
