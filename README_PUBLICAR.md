# Extrator TSE 2026 — Camaçari

Servidor web para consulta dos arquivos oficiais do TSE para Camaçari/BA, município 34134, zonas 0170 e 0171, pleito 3220.

## Publicação no Render
1. Crie uma conta no Render.
2. Crie um Web Service a partir deste diretório/repositório.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn backend:app --host 0.0.0.0 --port $PORT`
5. Após publicar, abra a URL HTTPS gerada no celular.

O `render.yaml` já contém essa configuração.

## Teste
Abra `/health`. A resposta deve ser JSON e indicar `backend: online` e `tse_http: 200`.

## Importante
O servidor precisa estar hospedado em um ambiente com acesso HTTPS de saída ao domínio oficial `resultados.tse.jus.br`. O ambiente de desenvolvimento desta conversa não consegue expor uma URL pública permanente nem garantir DNS externo.
