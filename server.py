#!/usr/bin/env python3
"""Serviço do cardápio da Sabor de Casa.

API REST (JSON) para Categoria e Prato + entrega da interface em /.
Só usa a biblioteca padrão do Python 3 (http.server + sqlite3).

  python3 server.py --seed      # primeira vez, com dados de exemplo
  python3 server.py             # depois
  abra http://localhost:8000
"""
import argparse, json, math, os, re, sqlite3, unicodedata, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
DB = Path(os.environ.get("DB_PATH", BASE / "cardapio.db"))  # DB_PATH: ex. disco persistente
PUBLIC = BASE / "public"
MAX_BODY = 64 * 1024  # bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS categoria(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  nome_norm TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS prato(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  categoria_id INTEGER NOT NULL REFERENCES categoria(id) ON DELETE RESTRICT,
  nome TEXT NOT NULL,
  descricao TEXT NOT NULL DEFAULT '',
  preco_centavos INTEGER NOT NULL CHECK(preco_centavos > 0),
  disponivel INTEGER NOT NULL DEFAULT 1
);
"""


class ApiError(Exception):
    def __init__(self, status, erro, campos=None):
        self.status, self.erro, self.campos = status, erro, campos or {}


def conectar():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def norm(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


# ---------- Categoria ----------
SQL_CAT = ("SELECT c.id, c.nome, (SELECT COUNT(*) FROM prato p WHERE p.categoria_id = c.id) "
           "AS total_pratos FROM categoria c")


def validar_categoria(body, conn, atual_id=None):
    nome = body.get("nome")
    nome = " ".join(nome.split()) if isinstance(nome, str) else ""
    msg = None
    if not nome:
        msg = "Informe o nome da categoria."
    elif len(nome) > 60:
        msg = "O nome pode ter no máximo 60 caracteres."
    elif conn.execute("SELECT 1 FROM categoria WHERE nome_norm = ? AND id IS NOT ?",
                      (norm(nome), atual_id)).fetchone():
        msg = "Já existe uma categoria com esse nome."
    if msg:
        raise ApiError(422, msg, {"nome": msg})
    return nome


def categoria_por_id(conn, id_):
    r = conn.execute(SQL_CAT + " WHERE c.id = ?", (id_,)).fetchone()
    if not r:
        raise ApiError(404, "Categoria não encontrada.")
    return dict(r)


def cat_listar(conn, **_):
    return 200, [dict(r) for r in conn.execute(SQL_CAT + " ORDER BY c.nome COLLATE NOCASE")]


def cat_obter(conn, id_, **_):
    return 200, categoria_por_id(conn, id_)


def cat_criar(conn, body, **_):
    nome = validar_categoria(body, conn)
    cur = conn.execute("INSERT INTO categoria(nome, nome_norm) VALUES (?, ?)", (nome, norm(nome)))
    return 201, categoria_por_id(conn, cur.lastrowid)


def cat_atualizar(conn, id_, body, **_):
    categoria_por_id(conn, id_)
    nome = validar_categoria(body, conn, id_)
    conn.execute("UPDATE categoria SET nome = ?, nome_norm = ? WHERE id = ?", (nome, norm(nome), id_))
    return 200, categoria_por_id(conn, id_)


def cat_excluir(conn, id_, **_):
    c = categoria_por_id(conn, id_)
    n = c["total_pratos"]
    if n:
        raise ApiError(409, f"Não dá para excluir “{c['nome']}”: ela ainda tem {n} "
                            f"{'prato' if n == 1 else 'pratos'}. Exclua ou mude os pratos de categoria primeiro.")
    conn.execute("DELETE FROM categoria WHERE id = ?", (id_,))
    return 204, None


# ---------- Prato ----------
SQL_PRATO = ("SELECT id, categoria_id, nome, descricao, preco_centavos / 100.0 AS preco, "
             "disponivel FROM prato")


def prato_out(r):
    d = dict(r)
    d["disponivel"] = bool(d["disponivel"])
    return d


def prato_por_id(conn, id_):
    r = conn.execute(SQL_PRATO + " WHERE id = ?", (id_,)).fetchone()
    if not r:
        raise ApiError(404, "Prato não encontrado.")
    return prato_out(r)


def validar_prato(body, conn, base=None):
    dados = {**(base or {"disponivel": True, "descricao": ""}), **body}
    erros = {}
    nome = dados.get("nome")
    nome = " ".join(nome.split()) if isinstance(nome, str) else ""
    if not nome:
        erros["nome"] = "Informe o nome do prato."
    elif len(nome) > 80:
        erros["nome"] = "O nome pode ter no máximo 80 caracteres."
    preco = dados.get("preco")
    if isinstance(preco, bool) or not isinstance(preco, (int, float)) or not math.isfinite(preco):
        erros["preco"] = "Informe o preço."
    elif preco <= 0:
        erros["preco"] = "O preço deve ser maior que zero."
    elif abs(preco * 100 - round(preco * 100)) > 1e-6:
        erros["preco"] = "Use no máximo duas casas decimais (por exemplo, 22,50)."
    elif preco > 9999.99:
        erros["preco"] = "O preço deve ser no máximo R$ 9.999,99."
    cat_id = dados.get("categoria_id")
    if isinstance(cat_id, bool) or not isinstance(cat_id, int) or not conn.execute(
            "SELECT 1 FROM categoria WHERE id = ?", (cat_id,)).fetchone():
        erros["categoria_id"] = "Escolha a categoria do prato."
    desc = dados.get("descricao")
    desc = " ".join(desc.split()) if isinstance(desc, str) else ""
    if len(desc) > 200:
        erros["descricao"] = "A descrição pode ter no máximo 200 caracteres."
    if not isinstance(dados.get("disponivel"), bool):
        erros["disponivel"] = "Use true ou false."
    if erros:
        raise ApiError(422, "Corrija os campos indicados.", erros)
    return nome, desc, round(preco * 100), cat_id, int(dados["disponivel"])


def prato_listar(conn, query, **_):
    sql, args = SQL_PRATO, []
    if "categoria_id" in query:
        if not query["categoria_id"][0].isdigit():
            raise ApiError(400, "O filtro categoria_id deve ser um número.")
        sql += " WHERE categoria_id = ?"
        args.append(int(query["categoria_id"][0]))
    return 200, [prato_out(r) for r in conn.execute(sql + " ORDER BY nome COLLATE NOCASE", args)]


def prato_obter(conn, id_, **_):
    return 200, prato_por_id(conn, id_)


def prato_criar(conn, body, **_):
    v = validar_prato(body, conn)
    cur = conn.execute("INSERT INTO prato(nome, descricao, preco_centavos, categoria_id, disponivel) "
                       "VALUES (?,?,?,?,?)", v)
    return 201, prato_por_id(conn, cur.lastrowid)


def prato_atualizar(conn, id_, body, **_):
    atual = prato_por_id(conn, id_)
    v = validar_prato(body, conn, atual)
    conn.execute("UPDATE prato SET nome=?, descricao=?, preco_centavos=?, categoria_id=?, disponivel=? "
                 "WHERE id = ?", (*v, id_))
    return 200, prato_por_id(conn, id_)


def prato_excluir(conn, id_, **_):
    prato_por_id(conn, id_)
    conn.execute("DELETE FROM prato WHERE id = ?", (id_,))
    return 204, None


ROTAS = {
    "categorias": {"GET": (cat_listar, cat_obter), "POST": cat_criar,
                   "PUT": cat_atualizar, "DELETE": cat_excluir},
    "pratos": {"GET": (prato_listar, prato_obter), "POST": prato_criar,
               "PUT": prato_atualizar, "DELETE": prato_excluir},
}


class Handler(BaseHTTPRequestHandler):
    def responder(self, status, corpo=None, tipo="application/json; charset=utf-8"):
        dados = b"" if corpo is None else (corpo if isinstance(corpo, bytes)
                                           else json.dumps(corpo, ensure_ascii=False).encode())
        self.send_response(status)
        if dados:
            self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)

    def ler_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0:
            raise ApiError(400, "Requisição inválida: tamanho do corpo incorreto.")
        if n > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, "Os dados enviados são grandes demais.")
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ApiError(400, "O corpo da requisição não é um JSON válido.")
        if not isinstance(body, dict):
            raise ApiError(400, "O corpo da requisição deve ser um objeto JSON.")
        return body

    def api(self, metodo, partes, query):
        if len(partes) not in (2, 3) or partes[1] not in ROTAS or metodo not in ROTAS[partes[1]]:
            raise ApiError(404, "Rota não encontrada.")
        acao = ROTAS[partes[1]][metodo]
        id_ = None
        if len(partes) == 3:
            if not partes[2].isdigit():
                raise ApiError(404, "Recurso não encontrado.")
            id_ = int(partes[2])
        if metodo == "GET":
            acao = acao[1] if id_ is not None else acao[0]
        elif (metodo == "POST") == (id_ is not None):
            raise ApiError(405, "Método não permitido para esta rota.")
        body = self.ler_json() if metodo in ("POST", "PUT") else {}
        conn = conectar()
        try:
            with conn:
                return acao(conn=conn, id_=id_, body=body, query=query)
        except sqlite3.IntegrityError:
            raise ApiError(409, "Não foi possível salvar: outra alteração entrou em conflito com esta. "
                                "Atualize a página e tente de novo.")
        finally:
            conn.close()

    def despachar(self):
        url = urlparse(self.path)
        partes = [p for p in url.path.split("/") if p]
        if partes[:1] == ["api"]:
            try:
                status, corpo = self.api(self.command, partes, parse_qs(url.query))
                self.responder(status, corpo)
            except ApiError as e:
                self.responder(e.status, {"erro": e.erro, "campos": e.campos})
            except Exception as e:  # erro inesperado: não vaza detalhes
                print("Erro:", repr(e))
                self.responder(500, {"erro": "Erro interno do servidor.", "campos": {}})
            return
        if self.command != "GET":
            return self.responder(405, {"erro": "Método não permitido.", "campos": {}})
        arq = (PUBLIC / (url.path.lstrip("/") or "index.html")).resolve()
        if PUBLIC.resolve() not in arq.parents or not arq.is_file():
            return self.responder(404, {"erro": "Página não encontrada.", "campos": {}})
        tipo = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
        self.responder(200, arq.read_bytes(), tipo + "; charset=utf-8" if tipo.startswith("text/") else tipo)

    do_GET = do_POST = do_PUT = do_DELETE = despachar


def semear():
    conn = conectar()
    with conn:
        if conn.execute("SELECT 1 FROM categoria").fetchone():
            return
        for nome in ("Marmitas do dia", "Fit", "Bebidas", "Sobremesas", "Combos"):
            conn.execute("INSERT INTO categoria(nome, nome_norm) VALUES (?,?)", (nome, norm(nome)))
        pratos = [(1, "Bife acebolado", "Arroz, feijão, farofa e salada", 22, 1),
                  (1, "Frango assado", "Arroz, feijão tropeiro e purê", 20, 1),
                  (1, "Feijoada", "Só às quartas e sábados", 26, 0),
                  (2, "Tilápia grelhada", "Arroz integral e legumes", 24, 1),
                  (3, "Suco de caju 500 ml", "", 7, 1),
                  (3, "Refrigerante lata", "", 6, 1),
                  (4, "Pudim de leite", "Porção individual", 8, 0)]
        for c, n, d, p, a in pratos:
            conn.execute("INSERT INTO prato(categoria_id, nome, descricao, preco_centavos, disponivel) "
                         "VALUES (?,?,?,?,?)", (c, n, d, p * 100, a))
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"),
                    help="127.0.0.1 = só este computador; 0.0.0.0 = acessível pela rede")
    ap.add_argument("--seed", action="store_true", help="cria dados de exemplo se o banco estiver vazio")
    args = ap.parse_args()
    with conectar() as c:
        c.executescript(SCHEMA)
    if args.seed:
        semear()
    print(f"Sabor de Casa rodando em http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
