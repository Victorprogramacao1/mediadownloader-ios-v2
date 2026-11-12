# MediaDownloader V1.8 — Atualização de dependências (12/11/2026)

## Alterações

- yt-dlp fixado em `2026.10.26` (estável oficial mais recente verificada em 12/11/2026).
- FastAPI atualizado para `0.162.5`, Uvicorn para `0.54.0`.
- `imageio-ffmpeg==0.8.1` mantido apenas no Windows/local; a Render usa o FFmpeg + ffprobe do sistema.
- `requirements-cloud.txt` para builds menores no Render; `Dockerfile` executa `pip check` e mostra `yt-dlp --version` nos logs da construção.
- Endpoint autenticado `/api/engine` apresenta versões realmente instaladas.
- Mensagem compreensível quando YouTube recusa solicitações automatizadas.
- Preservados: MP4 1080p, processamento sequencial, fila, ZIP e botão Salvar todos.

## Subir no GitHub e atualizar a Render

1. Faça backup do repositório atual. Baixe este ZIP e extraia.
2. No GitHub, atualize os arquivos na **raiz** de `Victorprogramacao1/mediadownloader`,
   preservando a pasta `web/`. Arquivos alterados: `requirements.txt`, `requirements-cloud.txt`,
   `Dockerfile`, `server.py`, `ATUALIZAR_MOTOR.bat`. (O guia e teste são opcionais.)
3. Commit na branch `main`. A Render deve iniciar um Auto-Deploy ou use Manual Deploy > Deploy latest commit.
4. Confira logs: `pip check` sem erros e `2026.10.26` na etapa Docker.
5. Abra `https://mediadownloader-web-gx8l.onrender.com/api/engine` e informe usuário `admin`
   e sua senha `APP_PASSWORD` para conferir versões. Não publique suas credenciais.
6. Teste uma mídia autorizada pequena antes de usar a fila.

## Limitação importante

Se a mensagem for "Sign in to confirm you're not a bot", o YouTube está negando a
solicitação do servidor da Render. Uma atualização de dependências, sozinha, não
garante a liberação. Não envie cookies do YouTube nem sua Conta Google à Render.

## Testes locais (com dependências instaladas)

`python -m unittest discover -s tests -v`
