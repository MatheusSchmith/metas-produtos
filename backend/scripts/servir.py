"""
servir.py — Abre o site na sua máquina, montado como no GitHub Pages, sem copiar nada.

Uso (na pasta backend/):
    python scripts/servir.py            # http://localhost:8000
    python scripts/servir.py --porta 8080

Serve frontend/ na raiz e api/ em /api, lendo direto das pastas do projeto: depois de rodar o
gerar.py, basta recarregar a página. Sem cache, para o navegador sempre pegar a versão nova.

POST /atualizar roda "gerar.py --forcar" (busca no Datasphere com o backend/.env) e devolve o resultado
em JSON. É o botão "Atualizar dados" das páginas; no GitHub Pages esse endereço não existe e o botão só
relê os arquivos publicados.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
FRONT = RAIZ / "frontend"
API = RAIZ / "api"
GERAR = RAIZ / "backend" / "scripts" / "gerar.py"
_gerando = threading.Lock()


class Manipulador(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        caminho = super().translate_path(path)   # já resolvido dentro de FRONT
        relativo = Path(caminho).relative_to(FRONT)
        if relativo.parts[:1] == ("api",):
            return str(API.joinpath(*relativo.parts[1:]))
        return caminho

    def do_POST(self) -> None:
        if self.path != "/atualizar":
            self.send_error(404)
            return
        if not _gerando.acquire(blocking=False):
            return self._json(409, {"ok": False, "mensagem": "Já existe uma atualização em andamento."})
        try:
            proc = subprocess.run([sys.executable, str(GERAR), "--forcar"], cwd=GERAR.parent.parent,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=900)
            linhas = (proc.stdout + proc.stderr).strip().splitlines()
            self._json(200 if proc.returncode == 0 else 500,
                       {"ok": proc.returncode == 0, "codigo": proc.returncode, "log": linhas[-15:]})
        except subprocess.TimeoutExpired:
            self._json(504, {"ok": False, "mensagem": "O gerar.py passou de 15 minutos."})
        finally:
            _gerando.release()

    def _json(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args) -> None:   # silencioso: só erros aparecem
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8000)
    args = ap.parse_args()
    servidor = ThreadingHTTPServer(("localhost", args.porta), functools.partial(Manipulador, directory=str(FRONT)))
    print(f"Site em http://localhost:{args.porta}  (status: http://localhost:{args.porta}/status.html)")
    print("Ctrl+C para parar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
