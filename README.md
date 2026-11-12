# MediaDownloader V1.8 — GitHub + Render

Versão atualizada com dependências fixadas para uso privado na nuvem. Processa **mídias próprias ou autorizadas**.

## Publicar

1. Crie um repositório **privado** no GitHub e envie **o conteúdo desta pasta** na raiz (não envie o ZIP sem extrair).
2. No [Render Dashboard](https://dashboard.render.com), clique **New > Blueprint**.
3. Conecte o repositório ao Render e selecione o arquivo `render.yaml`.
4. Configure `APP_PASSWORD` com **no mínimo 12 caracteres**, sem colocá-la no código ou GitHub. Caso a tela do Blueprint não solicite, configure em **Environment** no serviço antes do próximo deploy.
5. Aplique o Blueprint e aguarde a compilação do Dockerfile.
6. Abra o endereço `https://...onrender.com`. O navegador pedirá usuário `admin` e a senha `APP_PASSWORD`.
7. Faça um teste curto com um vídeo **seu/autorizado**, escolha MP4 1080p, inicie a fila, e clique em **Salvar todos** para baixar o ZIP antes de deixar o serviço inativo.

### Limites do serviço gratuito

- O plano gratuito usa recursos modestos (atualmente 512 MB RAM e 0,1 CPU), e pode ser muito lento para recodificar 1080p.
- A Render suspende serviços gratuitos após **15 minutos sem tráfego HTTP/WebSocket** e o próximo acesso pode levar aproximadamente um minuto para iniciar.
- **Armazenamento é temporário:** arquivos e fila são perdidos em reinícios, redeploys ou suspensão. Nunca trate Render Free como armazenamento de longo prazo.
- Por padrão: 20 links por lote, arquivos individuais de até 300 MB, limite suave de 900 MB em arquivos temporários e limite de 550 MB por ZIP.
- O usuário precisa salvar o ZIP ao final. Não é recomendado para uso público intensivo.
- A taxa de transferência e disponibilidade de formatos dependem da fonte; vídeos podem falhar por bloqueio do provedor ou falta de recursos.
- A senha protege acesso, mas não equivale a um sistema de contas com cotas por usuário. Não compartilhe a senha.
- Downloads são sequenciais, com quatro fragmentos em paralelo *dentro* de cada vídeo quando a origem permite.

### Segurança

- `APP_PASSWORD` é obrigatória quando `MEDIA_CLOUD=1` e autentica o site, APIs, ZIP e arquivos com HTTP Basic sobre HTTPS.
- A rota `/api/health` fica pública para o monitoramento da Render.
- Somente URLs HTTPS reconhecidas do YouTube são aceitas. Baixe apenas mídias com autorização.
- A base de código e o projeto original não devem conter cookies, credenciais, chaves de APIs ou downloads anteriores.

### Local (Windows)

A execução local continua disponível com `INICIAR_WINDOWS.bat`, sem exigir `APP_PASSWORD` na configuração padrão. Nunca rode a versão local escutando em `0.0.0.0` sem configurar autenticação.

## Arquivos

- `server.py`: API FastAPI, fila e processamento de mídia
- `web/`: interface
- `requirements.txt`: dependências Python
- `Dockerfile`: instala FFmpeg e prepara o container
- `render.yaml`: Blueprint gratuito da Render
- `.gitignore` e `.dockerignore`: excluem arquivos privados e temporários
- `tests/`: testes locais

## Checklist de diagnóstico

- `/api/health`: deve indicar `yt_dlp: true` e `ffmpeg: true`.
- O navegador deve pedir a senha antes de acessar a interface.
- Após a conclusão da fila, baixe o ZIP **antes** da suspensão ou reinício do serviço.
- Para falhas, consulte **Logs** no dashboard da Render. Não publique logs contendo links privados ou dados pessoais.

Documentação oficial: https://render.com/docs/free e https://render.com/docs/blueprint-spec


## Atualização V1.8

Veja `ATUALIZACAO_V1_8.md` para atualizar as dependências e conferir o motor.
