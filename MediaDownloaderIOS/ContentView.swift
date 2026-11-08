import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: DownloadStore
    @State private var input = ""
    @State private var quality: VideoQuality = .fullHD
    @State private var authorized = false

    private var queueProgress: Double {
        guard !store.entries.isEmpty else { return 0 }
        return store.entries.map(\.progress).reduce(0, +) / Double(store.entries.count)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("MediaDownloader", systemImage: "arrow.down.to.line.compact")
                            .font(.largeTitle.bold())
                            .minimumScaleFactor(0.75)
                            .lineLimit(1)
                        Text("V2 · Download direto no iPhone")
                            .foregroundStyle(.secondary)
                        Text("Sem Render. O processamento da mídia ocorre no próprio aparelho.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.bottom, 4)

                    VStack(alignment: .leading, spacing: 12) {
                        Text("Cole os links — um por linha").font(.headline)
                        Text("URLs de vídeos públicos/autorizados do YouTube ou links diretos MP4/MOV")
                            .font(.caption).foregroundStyle(.secondary)
                        TextEditor(text: $input)
                            .frame(minHeight: 160)
                            .scrollContentBackground(.hidden)
                            .padding(8)
                            .background(.black.opacity(0.14), in: RoundedRectangle(cornerRadius: 12))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .disabled(store.running || store.zipping)
                        Picker("Qualidade", selection: $quality) {
                            ForEach(VideoQuality.allCases) { option in Text(option.rawValue).tag(option) }
                        }
                        .pickerStyle(.segmented)
                        .disabled(store.running || store.zipping)
                        Text("1080p exige um fluxo MP4 Full HD disponível. Não reduz silenciosamente para 720p.")
                            .font(.caption2).foregroundStyle(.secondary)
                        Toggle("Tenho direitos ou autorização para baixar esses arquivos", isOn: $authorized)
                            .font(.subheadline)
                            .disabled(store.running || store.zipping)
                        if store.running {
                            Button(role: .destructive) { store.stop() } label: {
                                Label("Interromper fila", systemImage: "stop.circle")
                                    .frame(maxWidth: .infinity).padding(.vertical, 10)
                            }
                            .buttonStyle(.bordered)
                        } else {
                            Button { store.start(urlText: input, quality: quality) } label: {
                                Label("Baixar lista, um por vez", systemImage: "arrow.down.circle.fill")
                                    .frame(maxWidth: .infinity).padding(.vertical, 12)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(store.zipping || !authorized || input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                    .padding()
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 20))

                    VStack(alignment: .leading, spacing: 12) {
                        Text("Progresso da fila").font(.title3.bold())
                        Text("\(store.finished) de \(store.entries.count) finalizados · \(store.succeeded) baixados · \(store.failed) falhas")
                            .font(.footnote).foregroundStyle(.secondary)
                        ProgressView(value: queueProgress)
                        ForEach(store.entries) { entry in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(entry.title).font(.caption.bold()).lineLimit(2)
                                Text(entry.stage)
                                    .font(.caption)
                                    .foregroundStyle(entry.error == nil ? Color.secondary : Color.red)
                                if let error = entry.error {
                                    Text(error).font(.caption2).foregroundStyle(.red)
                                }
                                if entry.result == nil && entry.error == nil && entry.progress > 0 {
                                    ProgressView(value: entry.progress)
                                }
                            }
                            Divider()
                        }
                        if store.zipping {
                            HStack { ProgressView(); Text("Preparando arquivo ZIP…") }
                                .font(.footnote)
                        }
                        if let archive = store.archiveURL {
                            ShareLink(item: archive) {
                                Label("Salvar todos (\(store.succeeded) arquivo(s))", systemImage: "square.and.arrow.up")
                                    .frame(maxWidth: .infinity).padding(.vertical, 10)
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        if !store.message.isEmpty {
                            Text(store.message).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    .padding()
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 20))

                    VStack(alignment: .leading, spacing: 5) {
                        Text("Compatibilidade e privacidade").font(.headline)
                        Text("Usa extração local de formatos no iPhone, sem servidor Render. O YouTube pode mudar seus mecanismos, limitar vídeos ou exigir login; alguns links podem falhar. O app não coleta nem solicita cookies da sua conta. Mantenha o aplicativo aberto durante os downloads. O ZIP pode consumir espaço adicional temporariamente.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .padding()
            }
            .background(Color(red: 0.04, green: 0.07, blue: 0.13))
            .preferredColorScheme(.dark)
        }
    }
}
