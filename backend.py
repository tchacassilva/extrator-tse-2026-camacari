from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path
import requests
import io
import zipfile
import json
import csv
import time

app = FastAPI(title="Extrator TSE 2026", version="1.0")

TSE_BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna"
USER_AGENT = {
    "User-Agent": "Mozilla/5.0 Extrator-TSE-2026/1.0",
    "Accept": "application/json,text/plain,*/*",
}

INDEX = Path(__file__).with_name("index.html")

# ------------------------------------------------------------
# Comunicação com o TSE
# ------------------------------------------------------------

def tse_get(url: str, timeout: int = 90):
    """GET no TSE com tratamento de rede e HTTP."""
    try:
        r = requests.get(
            url,
            headers=USER_AGENT,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Falha de comunicação com o TSE: {exc}",
        )

    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"TSE respondeu HTTP {r.status_code}",
        )

    return r


def pleito_base(pleito: str) -> str:
    p = str(pleito).zfill(6)
    return f"{TSE_BASE}/{int(p)}"


def ea16_url(uf: str, pleito: str) -> str:
    uf = uf.lower()
    p = str(pleito).zfill(6)
    return f"{pleito_base(p)}/config/{uf}/{uf}-p{p}-cs.json"


def ea18_url(uf: str, municipio: str, zona: str, secao: str, pleito: str) -> str:
    uf = uf.lower()
    mun = municipio.zfill(5)
    z = zona.zfill(4)
    s = secao.zfill(4)
    p = str(pleito).zfill(6)

    nome = f"p{p}-{uf}-m{mun}-z{z}-s{s}-aux.json"
    return f"{pleito_base(p)}/dados/{uf}/{mun}/{z}/{s}/{nome}"


def localizar_bu(ea18: dict):
    """
    O EA18 lista os arquivos recebidos.
    Procura o BU no último hash disponível.
    """
    hashes = ea18.get("hashes") or []

    for h in reversed(hashes):
        arquivos = h.get("arq") or []

        for arq in arquivos:
            tipo = str(arq.get("tp", "")).strip().upper()
            nome = str(arq.get("nm", "")).strip()

            if tipo == "BU" or nome.upper().endswith(".BU"):
                return {
                    "hash": str(h.get("hash", "")).strip(),
                    "nome": nome,
                    "tipo": tipo,
                }

    return None


def bu_url(uf, municipio, zona, secao, pleito, hash_bu, nome):
    return (
        f"{pleito_base(pleito)}/dados/"
        f"{uf.lower()}/{municipio.zfill(5)}/{zona.zfill(4)}/"
        f"{secao.zfill(4)}/{hash_bu}/{nome}"
    )


# ------------------------------------------------------------
# Seções
# ------------------------------------------------------------

def descobrir_secoes(data, uf, municipio, zonas):
    uf = uf.lower()
    municipio = municipio.zfill(5)

    desejadas = {
        str(z).strip().zfill(4)
        for z in str(zonas).split(",")
        if str(z).strip()
    }

    encontrados = {}

    for abrangencia in data.get("abr", []):
        if str(abrangencia.get("cd", "")).lower() != uf:
            continue

        for mun in abrangencia.get("mu", []):
            if str(mun.get("cd", "")).zfill(5) != municipio:
                continue

            for zona_obj in mun.get("zon", []):
                zona = str(zona_obj.get("cd", "")).zfill(4)

                if zona not in desejadas:
                    continue

                for sec in zona_obj.get("sec", []):
                    secao = str(sec.get("ns", "")).zfill(4)

                    registro = {
                        "zona": zona,
                        "secao": secao,
                        "agregada": bool(sec.get("nsp")),
                        "data_ea18": sec.get("da"),
                        "hora_ea18": sec.get("ha"),
                    }

                    encontrados[(zona, secao)] = registro

    return sorted(
        encontrados.values(),
        key=lambda x: (x["zona"], x["secao"]),
    )


# ------------------------------------------------------------
# Interface
# ------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home():
    if not INDEX.exists():
        return HTMLResponse(
            "<h1>Extrator TSE 2026</h1>"
            "<p>Backend funcionando. Coloque index.html na mesma pasta.</p>"
        )

    return HTMLResponse(INDEX.read_text(encoding="utf-8"))


@app.get("/health")
def health():
    """
    Não retorna OK apenas porque o FastAPI está vivo.
    Consulta efetivamente o arquivo EA16 do TSE.
    """
    uf = "ba"
    pleito = "003220"

    url = ea16_url(uf, pleito)
    r = tse_get(url, timeout=30)

    return {
        "ok": True,
        "backend": "online",
        "tse_http": r.status_code,
        "fonte": "TSE",
        "pleito": 3220,
    }


# ------------------------------------------------------------
# EA16
# ------------------------------------------------------------

@app.get("/api/sections/{uf}/{municipio}")
def api_sections(
    uf: str,
    municipio: str,
    zones: str = "0170,0171",
    pleito: str = "003220",
):
    p = str(pleito).zfill(6)

    r = tse_get(
        ea16_url(uf, p),
        timeout=60,
    )

    try:
        data = r.json()
    except ValueError:
        raise HTTPException(
            502,
            "O TSE respondeu, mas o EA16 não está em JSON válido.",
        )

    secoes = descobrir_secoes(
        data,
        uf,
        municipio,
        zones,
    )

    return {
        "ok": True,
        "fonte": "TSE",
        "uf": uf.lower(),
        "municipio": municipio.zfill(5),
        "pleito": int(p),
        "zonas": zones,
        "total": len(secoes),
        "sections": secoes,
    }


# ------------------------------------------------------------
# EA18
# ------------------------------------------------------------

@app.get("/api/ea18/{uf}/{municipio}/{zona}/{secao}")
def api_ea18(
    uf: str,
    municipio: str,
    zona: str,
    secao: str,
    pleito: str = "003220",
):
    url = ea18_url(
        uf,
        municipio,
        zona,
        secao,
        pleito,
    )

    r = tse_get(url, timeout=60)

    try:
        data = r.json()
    except ValueError:
        raise HTTPException(
            502,
            "O TSE respondeu, mas o EA18 não está em JSON válido.",
        )

    bu = localizar_bu(data)

    return {
        "ok": True,
        "fonte": "TSE",
        "zona": zona.zfill(4),
        "secao": secao.zfill(4),
        "bu": bu,
        "ea18": data,
    }


# ------------------------------------------------------------
# Download individual
# ------------------------------------------------------------

@app.get("/api/download/{uf}/{municipio}/{zona}/{secao}")
def api_download(
    uf: str,
    municipio: str,
    zona: str,
    secao: str,
    pleito: str = "003220",
):
    eurl = ea18_url(
        uf,
        municipio,
        zona,
        secao,
        pleito,
    )

    ea18 = tse_get(eurl, timeout=60).json()
    bu = localizar_bu(ea18)

    if not bu:
        raise HTTPException(
            404,
            "BU não localizado no EA18 dessa seção.",
        )

    url = bu_url(
        uf,
        municipio,
        zona,
        secao,
        pleito,
        bu["hash"],
        bu["nome"],
    )

    r = tse_get(url, timeout=90)

    return StreamingResponse(
        io.BytesIO(r.content),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition":
                f'attachment; filename="{bu["nome"]}"'
        },
    )


# ------------------------------------------------------------
# DOWNLOAD EM LOTE
# ------------------------------------------------------------

@app.get("/api/download-batch/{uf}/{municipio}")
def api_download_batch(
    uf: str,
    municipio: str,
    zones: str = "0170,0171",
    pleito: str = "003220",
):
    """
    Faz:
        EA16
         ↓
        seções
         ↓
        EA18 de cada seção
         ↓
        hash do BU
         ↓
        BU
         ↓
        UM ZIP
    """

    inicio = time.time()
    p = str(pleito).zfill(6)

    # 1 — Descobre as seções
    r = tse_get(
        ea16_url(uf, p),
        timeout=60,
    )

    data = r.json()

    secoes = descobrir_secoes(
        data,
        uf,
        municipio,
        zones,
    )

    memoria = io.BytesIO()

    controle = []

    with zipfile.ZipFile(
        memoria,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zipf:

        for i, sec in enumerate(secoes, start=1):
            zona = sec["zona"]
            secao = sec["secao"]

            # Seção agregada não possui BU próprio.
            if sec["agregada"]:
                controle.append({
                    "zona": zona,
                    "secao": secao,
                    "status": "AGREGADA",
                    "arquivo": "",
                    "hash": "",
                    "bytes": 0,
                })
                continue

            try:
                # 2 — EA18
                eurl = ea18_url(
                    uf,
                    municipio,
                    zona,
                    secao,
                    p,
                )

                ea18 = tse_get(
                    eurl,
                    timeout=60,
                ).json()

                # 3 — localizar BU
                bu = localizar_bu(ea18)

                if not bu:
                    controle.append({
                        "zona": zona,
                        "secao": secao,
                        "status": "BU_NAO_LOCALIZADO",
                        "arquivo": "",
                        "hash": "",
                        "bytes": 0,
                    })
                    continue

                # 4 — BU
                url = bu_url(
                    uf,
                    municipio,
                    zona,
                    secao,
                    p,
                    bu["hash"],
                    bu["nome"],
                )

                arquivo = tse_get(
                    url,
                    timeout=90,
                ).content

                # 5 — grava BU
                zipf.writestr(
                    f"{zona}/{secao}/{bu['nome']}",
                    arquivo,
                )

                # 6 — grava EA18 para auditoria
                zipf.writestr(
                    f"{zona}/{secao}/EA18.json",
                    json.dumps(
                        ea18,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                controle.append({
                    "zona": zona,
                    "secao": secao,
                    "status": "OK",
                    "arquivo": bu["nome"],
                    "hash": bu["hash"],
                    "bytes": len(arquivo),
                })

            except HTTPException as exc:
                controle.append({
                    "zona": zona,
                    "secao": secao,
                    "status": f"TSE_HTTP_{exc.status_code}",
                    "arquivo": "",
                    "hash": "",
                    "bytes": 0,
                })

            except Exception as exc:
                controle.append({
                    "zona": zona,
                    "secao": secao,
                    "status": f"ERRO: {exc}",
                    "arquivo": "",
                    "hash": "",
                    "bytes": 0,
                })

        # 7 — Controle CSV
        csv_mem = io.StringIO()

        writer = csv.DictWriter(
            csv_mem,
            fieldnames=[
                "zona",
                "secao",
                "status",
                "arquivo",
                "hash",
                "bytes",
            ],
        )

        writer.writeheader()
        writer.writerows(controle)

        zipf.writestr(
            "controle_download.csv",
            csv_mem.getvalue(),
        )

        # 8 — Resumo
        resumo = {
            "fonte": "TSE",
            "uf": uf.lower(),
            "municipio": municipio.zfill(5),
            "pleito": int(p),
            "zonas": zones,
            "total_secoes": len(secoes),
            "downloads_ok": sum(
                x["status"] == "OK"
                for x in controle
            ),
            "agregadas": sum(
                x["status"] == "AGREGADA"
                for x in controle
            ),
            "pendencias": sum(
                x["status"] != "OK"
                and x["status"] != "AGREGADA"
                for x in controle
            ),
            "tempo_segundos": round(
                time.time() - inicio,
                1,
            ),
        }

        zipf.writestr(
            "resumo.json",
            json.dumps(
                resumo,
                ensure_ascii=False,
                indent=2,
            ),
        )

    memoria.seek(0)

    return StreamingResponse(
        memoria,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                'attachment; filename="BUs_Camacari_2026.zip"',
            "Content-Length":
                str(len(memoria.getbuffer())),
        },
    )
