# MediaDownloader iPhone V2 — processamento local (beta)

Projeto SwiftUI iOS 17+ adaptado para iPhone 15 Pro Max, a partir da V1 que já foi instalada por Sideloadly. **Este ZIP contém o código-fonte**, não um IPA pronto. O workflow gera um `MediaDownloader_iPhone_UNSIGNED.ipa` para assinatura no Windows.

## Principais mudanças

- Reconhece `youtube.com/watch`, `youtu.be`, `youtube.com/shorts` e URLs HTTPS diretas de vídeo MP4/MOV.
- Inclui o extrator local **YouTubeKit 0.4.9** (MIT). Especifica **`methods: [.local]`**, sem fallback remoto e sem Render.
- Para **MP4 1080p**, solicita um fluxo MP4 Full HD disponível. Quando o fluxo não inclui áudio, obtém M4A/AAC em separado e junta no iPhone com AVFoundation.
- Não troca 1080p por 720p silenciosamente; falha de um item não impede os próximos.
- Fila sequencial de 1 a 100 URLs; status/progresso individual e botão **Interromper fila**.
- ZIP automático de arquivos concluídos, com um único botão **Salvar todos**, que abre a folha de compartilhamento do iOS (escolha **Salvar em Arquivos**).
- Evita conversão extra quando o MP4 já é 1920×1080 H.264/AAC.
- Todos os arquivos gerados são armazenados na pasta `MediaDownloader/Lote_...` do app em Arquivos (compartilhamento de arquivos do iOS habilitado).

## Restrições reais

1. A biblioteca YouTubeKit **não é uma API oficial do YouTube** e pode parar de funcionar após mudanças da plataforma. Vídeos privados, protegidos, que exijam login, com restrição geográfica ou indisponíveis podem falhar. Não implementei autenticação por cookies, nem bypass de verificações. Use somente conteúdo próprio ou autorizado e respeite os termos aplicáveis.
2. **1080p não é garantido para todos os vídeos.** O app informa erro se não encontrar um fluxo MP4 Full HD nativo, sem reduzir para 720p. Não melhora vídeos de resolução inferior artificialmente.
3. A exportação com AVFoundation consome processamento e armazenamento. Para evitar interrupções, mantenha o aplicativo aberto e o aparelho com espaço suficiente.
4. O app ainda **não oferece MP3**. A opção Original preserva vídeo MP4/MOV de origem quando possível.
5. O pacote foi validado com parser Swift e testes estáticos neste ambiente Linux. **Ainda não foi compilado em Xcode nem testado com download real no iPhone**. A primeira execução no GitHub Actions verificará a integração.

## Atualizar seu repositório existente

1. No Windows, extraia este ZIP.
2. Abra seu repositório `Victorprogramacao1/mediadownloader-ios`, aba **Code**.
3. Substitua na branch `main` os arquivos `project.yml`, `MediaDownloaderIOS/ContentView.swift` e `MediaDownloaderIOS/DownloadStore.swift` pelos arquivos da V2. **Preserve exatamente as pastas.** O `MediaDownloaderApp.swift` e os arquivos de automação foram incluídos para facilitar uma atualização completa.
4. No **Actions**, execute `Gerar IPA para iPhone (nao assinado)` → **Run workflow**.
5. Se a execução terminar verde, abra a execução, seção **Artifacts**, baixe `MediaDownloader-iPhone-IPA-NAO-ASSINADO` e extraia `MediaDownloader_iPhone_UNSIGNED.ipa`.
6. No **Sideloadly** do Windows, escolha esse IPA, o seu iPhone e a mesma Conta Apple que usou antes. Use **Start**. Com conta gratuita, a assinatura precisa normalmente ser renovada a cada 7 dias.
7. Abra o MediaDownloader e teste primeiro **um vídeo seu ou autorizado com 1080p** e depois uma fila de dois itens.

**Atenção:** atualizar somente o workflow `gerar-ipa.yml` não altera o aplicativo. É indispensável enviar os **arquivos Swift e `project.yml`**.

## Estrutura

```
MediaDownloaderIOS/
  ContentView.swift
  DownloadStore.swift
  MediaDownloaderApp.swift
.github/workflows/
  gerar-ipa.yml
scripts/
  package-ipa.sh
  verificar_projeto.py
project.yml
README.md
```

## Verificações locais (Linux ou Windows com Python 3)

```
python scripts/verificar_projeto.py
```

No macOS, `xcodegen generate` e `xcodebuild` confirmam a compilação completa. O GitHub Actions executa esses passos em um runner macOS.

## Bibliotecas de terceiros

- [YouTubeKit](https://github.com/alexeichhorn/YouTubeKit) (licença MIT, 0.4.9) — extração local de streams.
- [ZIPFoundation](https://github.com/weichsel/ZIPFoundation) — criação de ZIP no iOS.
- [AVFoundation](https://developer.apple.com/documentation/avfoundation) — exportação e composição MP4 H.264/AAC.

O app não solicita credenciais do YouTube nem se conecta ao backend da Render. Downloads e arquivos ficam no dispositivo, exceto as conexões HTTPS necessárias para acessar a fonte e as próprias dependências do app.
