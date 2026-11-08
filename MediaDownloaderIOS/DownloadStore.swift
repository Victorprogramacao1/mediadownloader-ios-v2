import Foundation
import AVFoundation
import AudioToolbox
import CoreMedia
import ZIPFoundation
import YouTubeKit

// O processamento ocorre no aparelho. O extrator YouTubeKit usa exclusivamente
// `.local`: nenhum fallback de extração em servidor é ativado.

enum VideoQuality: String, CaseIterable, Identifiable {
    case fullHD = "MP4 1080p"
    case original = "Original"
    var id: String { rawValue }
}

enum DownloadFailure: LocalizedError {
    case message(String)
    var errorDescription: String? {
        if case let .message(text) = self { return text }
        return nil
    }
}

enum MediaLink {
    case youtube(URL)
    case direct(URL)

    static func classify(_ url: URL) -> MediaLink {
        let host = (url.host ?? "").lowercased()
        let youtubeHosts = ["youtube.com", "youtu.be", "youtube-nocookie.com"]
        if youtubeHosts.contains(where: { host == $0 || host.hasSuffix("." + $0) }) {
            return .youtube(url)
        }
        return .direct(url)
    }
}

struct DownloadEntry: Identifiable {
    let id = UUID()
    let source: URL
    let number: Int
    var stage = "Na fila"
    var progress: Double = 0
    var result: URL?
    var error: String?

    var title: String {
        if let result { return result.lastPathComponent }
        switch MediaLink.classify(source) {
        case .youtube:
            let components = URLComponents(url: source, resolvingAgainstBaseURL: false)
            let identifier = components?.queryItems?.first(where: { $0.name == "v" })?.value
                ?? source.lastPathComponent
            return String(format: "%03d · YouTube %@", number, identifier)
        case .direct:
            return String(format: "%03d · %@", number, source.lastPathComponent)
        }
    }
}

@MainActor
final class DownloadStore: ObservableObject {
    @Published var entries: [DownloadEntry] = []
    @Published var running = false
    @Published var zipping = false
    @Published var archiveURL: URL?
    @Published var message = ""
    @Published var folderURL: URL?

    private var batchTask: Task<Void, Never>?
    private var activeExport: AVAssetExportSession?
    private var abortRequested = false

    var finished: Int { entries.filter { $0.result != nil || $0.error != nil }.count }
    var succeeded: Int { entries.filter { $0.result != nil }.count }
    var failed: Int { entries.filter { $0.error != nil }.count }

    func start(urlText: String, quality: VideoQuality) {
        guard !running, !zipping else { return }
        let pieces = urlText.components(separatedBy: CharacterSet.whitespacesAndNewlines.union(CharacterSet(charactersIn: ",;")))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard (1...100).contains(pieces.count) else {
            message = "Cole entre 1 e 100 URLs, separadas por linha."
            return
        }
        let urls = pieces.compactMap(URL.init(string:))
        guard urls.count == pieces.count,
              urls.allSatisfy({ $0.scheme?.lowercased() == "https" && $0.host != nil && $0.user == nil && $0.password == nil }) else {
            message = "Todos os endereços precisam ser URLs HTTPS válidas."
            return
        }

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MediaDownloader", isDirectory: true)
        let unique = UUID().uuidString.prefix(6)
        let folder = root.appendingPathComponent("Lote_\(formatter.string(from: Date()))_\(unique)", isDirectory: true)
        do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
        catch { message = "Não foi possível criar a pasta: \(error.localizedDescription)"; return }

        abortRequested = false
        archiveURL = nil
        folderURL = folder
        entries = urls.enumerated().map { DownloadEntry(source: $0.element, number: $0.offset + 1) }
        running = true
        message = "Iniciando fila no próprio iPhone…"
        batchTask = Task {
            for index in entries.indices {
                if Task.isCancelled || abortRequested { break }
                await process(index: index, quality: quality, folder: folder)
            }
            running = false
            batchTask = nil
            if abortRequested { message = "Fila interrompida. \(succeeded) arquivo(s) concluído(s)." }
            else { message = "Fila finalizada: \(succeeded) concluído(s), \(failed) falha(s)." }
            // O ZIP é gerado automaticamente; a interface oferece UM botão Salvar todos.
            if succeeded > 0 { await buildZIP(folder: folder) }
        }
    }

    func stop() {
        guard running else { return }
        abortRequested = true
        activeExport?.cancelExport()
        batchTask?.cancel()
        message = "Interrompendo a tarefa atual…"
    }

    private func process(index: Int, quality: VideoQuality, folder: URL) async {
        let source = entries[index].source
        let prefix = String(format: "%03d", index + 1)
        let output = folder.appendingPathComponent(prefix + (quality == .fullHD ? "_video_1080p.mp4" : "_video_original.mp4"))
        var leftovers: [URL] = []
        defer { for url in leftovers { try? FileManager.default.removeItem(at: url) } }
        do {
            try Task.checkCancellation()
            switch MediaLink.classify(source) {
            case .youtube(let link):
                entries[index].stage = "Consultando formatos no iPhone"
                let youtube = YouTube(url: link, methods: [.local])
                let streams: [YouTubeKit.Stream]
                do { streams = try await youtube.streams }
                catch {
                    throw DownloadFailure.message("Não foi possível obter os formatos deste vídeo. Ele pode estar indisponível ou exigir autenticação. \(error.localizedDescription)")
                }
                try Task.checkCancellation()
                let chosen: YouTubeKit.Stream
                if quality == .fullHD {
                    let exact = streams.streams(withExactResolution: 1080)
                        .filter { $0.fileExtension == .mp4 && $0.isNativelyPlayable }
                    if let full = exact.filterVideoAndAudio().first { chosen = full }
                    else if let video = exact.filterVideoOnly().first { chosen = video }
                    else { throw DownloadFailure.message("MP4 Full HD 1080p não disponível neste vídeo. Não será substituído por 720p.") }
                } else {
                    let playable = streams.filter { $0.fileExtension == .mp4 && $0.isNativelyPlayable }
                    let videoCandidates = playable.filterVideoAndAudio() + playable.filterVideoOnly()
                    guard let best = videoCandidates.highestResolutionStream() else {
                        throw DownloadFailure.message("Nenhum fluxo MP4 compatível foi encontrado.")
                    }
                    chosen = best
                }
                try await chosen.waitUntilAvailable()
                try Task.checkCancellation()
                let videoURL = folder.appendingPathComponent(prefix + "_temp_video.mp4")
                leftovers.append(videoURL)
                entries[index].stage = "Baixando vídeo"
                try await transfer(chosen.url, to: videoURL, index: index, from: 0, to: 0.60)
                try Task.checkCancellation()

                let sourceAsset = AVURLAsset(url: videoURL)
                let audioTracks = try await sourceAsset.loadTracks(withMediaType: .audio)
                if !audioTracks.isEmpty {
                    if quality == .fullHD {
                        try await make1080(input: videoURL, output: output, index: index, range: 0.6...0.99)
                    } else {
                        try FileManager.default.moveItem(at: videoURL, to: output)
                    }
                } else {
                    // 1080p do YouTube frequentemente tem vídeo e áudio separados.
                    guard let audio = streams.filterAudioOnly()
                        .filter({ $0.fileExtension == .m4a && $0.isNativelyPlayable })
                        .highestAudioBitrateStream() else {
                        throw DownloadFailure.message("Vídeo localizado, porém não há faixa de áudio M4A/AAC compatível.")
                    }
                    try await audio.waitUntilAvailable()
                    entries[index].stage = "Baixando áudio AAC"
                    let audioURL = folder.appendingPathComponent(prefix + "_temp_audio.m4a")
                    leftovers.append(audioURL)
                    try await transfer(audio.url, to: audioURL, index: index, from: 0.60, to: 0.82)
                    try Task.checkCancellation()
                    entries[index].stage = "Juntando vídeo + áudio em MP4"
                    try await merge(video: videoURL, audio: audioURL, output: output, index: index,
                                    quality: quality)
                    // O áudio AAC é incorporado localmente ao MP4.
                }
            case .direct(let link):
                let ext = link.pathExtension.lowercased()
                let known: Set<String> = ["mp4", "mov", "m4v"]
                let original = folder.appendingPathComponent(prefix + "_temp_original." + (known.contains(ext) ? ext : "mp4"))
                leftovers.append(original)
                entries[index].stage = "Baixando arquivo de mídia"
                try await transfer(link, to: original, index: index, from: 0, to: 0.73)
                try Task.checkCancellation()
                if quality == .fullHD {
                    try await make1080(input: original, output: output, index: index, range: 0.73...0.99)
                } else {
                    let originalOutput = folder.appendingPathComponent(prefix + "_video." + (known.contains(ext) ? ext : "mp4"))
                    try FileManager.default.moveItem(at: original, to: originalOutput)
                    entries[index].result = originalOutput
                }
            }

            if entries[index].result == nil { entries[index].result = output }
            entries[index].stage = "Concluído"
            entries[index].progress = 1
        } catch {
            try? FileManager.default.removeItem(at: output)
            entries[index].error = (abortRequested || error is CancellationError)
                ? "Interrompido pelo usuário." : error.localizedDescription
            entries[index].stage = "Falhou"
        }
    }

    private func transfer(_ url: URL, to path: URL, index: Int, from start: Double, to end: Double) async throws {
        guard url.scheme?.lowercased() == "https" else {
            throw DownloadFailure.message("O arquivo não possui um endereço HTTPS válido.")
        }
        let delegate = TransferProgress { [weak self] progress in
            Task { @MainActor in
                guard let self, index < self.entries.count else { return }
                self.entries[index].progress = start + progress * (end - start)
            }
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 100
        let (temporary, response) = try await URLSession.shared.download(for: request, delegate: delegate)
        defer { try? FileManager.default.removeItem(at: temporary) }
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw DownloadFailure.message("O servidor recusou o arquivo. Verifique se o link ainda está disponível.")
        }
        let mediaType = (response.mimeType ?? "").lowercased()
        guard mediaType.hasPrefix("video/") || mediaType.hasPrefix("audio/")
                || mediaType == "application/octet-stream" || mediaType == "application/mp4" else {
            throw DownloadFailure.message("A URL retornou uma página, não um arquivo de mídia. Use um link direto ou um vídeo público e autorizado.")
        }
        try FileManager.default.moveItem(at: temporary, to: path)
        let bytes = (try FileManager.default.attributesOfItem(atPath: path.path)[.size] as? NSNumber)?.int64Value ?? 0
        guard bytes > 0 else { throw DownloadFailure.message("O arquivo recebido está vazio.") }
    }

    private func make1080(input: URL, output: URL, index: Int, range: ClosedRange<Double>) async throws {
        let asset = AVURLAsset(url: input)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard let videoTrack = tracks.first else { throw DownloadFailure.message("Arquivo recebido não contém vídeo válido.") }
        let size = try await videoTrack.load(.naturalSize)
        let transform = try await videoTrack.load(.preferredTransform)
        let dimensions = size.applying(transform)
        let width = abs(dimensions.width)
        let height = abs(dimensions.height)
        guard (width >= 1918 && height >= 1078) || (width >= 1078 && height >= 1918) else {
            throw DownloadFailure.message("A fonte não contém resolução Full HD. Nada será ampliado artificialmente.")
        }
        entries[index].stage = "Finalizando MP4 1080p H.264/AAC"
        // Não recodifica quando um arquivo MP4 Full HD já possui H.264 e AAC.
        let videoDescriptions = try await videoTrack.load(.formatDescriptions)
        let videoIsH264 = videoDescriptions.contains { CMFormatDescriptionGetMediaSubType($0) == kCMVideoCodecType_H264 }
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        let audioIsAAC = try await hasAACAudio(audioTracks)
        if input.pathExtension.lowercased() == "mp4" && videoIsH264 && audioIsAAC
            && abs(width - 1920) < 2 && abs(height - 1080) < 2 {
            try FileManager.default.moveItem(at: input, to: output)
            entries[index].progress = range.upperBound
            return
        }
        try await export(asset: asset, preset: AVAssetExportPreset1920x1080,
                         output: output, index: index, range: range)
    }

    private func hasAACAudio(_ tracks: [AVAssetTrack]) async throws -> Bool {
        guard let track = tracks.first else { return false }
        let descriptions = try await track.load(.formatDescriptions)
        return descriptions.contains { CMFormatDescriptionGetMediaSubType($0) == kAudioFormatMPEG4AAC }
    }

    private func merge(video: URL, audio: URL, output: URL, index: Int,
                       quality: VideoQuality) async throws {
        let videoAsset = AVURLAsset(url: video)
        let audioAsset = AVURLAsset(url: audio)
        let videoTracks = try await videoAsset.loadTracks(withMediaType: .video)
        let audioTracks = try await audioAsset.loadTracks(withMediaType: .audio)
        guard let vt = videoTracks.first, let at = audioTracks.first else {
            throw DownloadFailure.message("Não foi possível identificar vídeo e áudio para a junção.")
        }
        let duration = try await videoAsset.load(.duration)
        let audioDuration = try await audioAsset.load(.duration)
        guard duration.isNumeric && audioDuration.isNumeric else {
            throw DownloadFailure.message("Duração inválida do vídeo ou áudio.")
        }
        let composition = AVMutableComposition()
        guard let cv = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
              let ca = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else {
            throw DownloadFailure.message("Não foi possível criar faixas de áudio e vídeo.")
        }
        try cv.insertTimeRange(CMTimeRange(start: .zero, duration: duration), of: vt, at: .zero)
        cv.preferredTransform = try await vt.load(.preferredTransform)
        try ca.insertTimeRange(CMTimeRange(start: .zero, duration: CMTimeMinimum(duration, audioDuration)), of: at, at: .zero)

        // Se vídeo H.264 e áudio AAC já estiverem compatíveis, apenas remultiplexa.
        // Assim a etapa de junção costuma ser muito mais rápida que recodificar.
        let vFormats = try await vt.load(.formatDescriptions)
        let aFormats = try await at.load(.formatDescriptions)
        let isH264 = vFormats.contains { CMFormatDescriptionGetMediaSubType($0) == kCMVideoCodecType_H264 }
        let isAAC = aFormats.contains { CMFormatDescriptionGetMediaSubType($0) == kAudioFormatMPEG4AAC }
        let canCopy = (quality == .original || (isH264 && isAAC))
        if canCopy {
            do {
                try await export(asset: composition, preset: AVAssetExportPresetPassthrough,
                                 output: output, index: index, range: 0.82...0.99)
                return
            } catch {
                if Task.isCancelled || abortRequested { throw error }
                try? FileManager.default.removeItem(at: output)
            }
        }
        let preset = quality == .fullHD ? AVAssetExportPreset1920x1080 : AVAssetExportPresetHighestQuality
        try await export(asset: composition, preset: preset,
                         output: output, index: index, range: 0.82...0.99)
    }

    private func export(asset: AVAsset, preset: String, output: URL, index: Int,
                        range: ClosedRange<Double>) async throws {
        guard let session = AVAssetExportSession(asset: asset, presetName: preset) else {
            throw DownloadFailure.message("Este formato não pode ser convertido no dispositivo.")
        }
        guard session.supportedFileTypes.contains(.mp4) else {
            throw DownloadFailure.message("O iOS não permitiu exportar a mídia para MP4.")
        }
        activeExport = session
        session.outputURL = output
        session.outputFileType = .mp4
        session.shouldOptimizeForNetworkUse = true
        let watcher = Task { @MainActor in
            while !Task.isCancelled && session.status != .completed && session.status != .failed && session.status != .cancelled {
                entries[index].progress = range.lowerBound + Double(session.progress) * (range.upperBound - range.lowerBound)
                try? await Task.sleep(nanoseconds: 450_000_000)
            }
        }
        defer { watcher.cancel(); activeExport = nil }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                session.exportAsynchronously {
                    if session.status == .completed {
                        continuation.resume()
                    } else {
                        continuation.resume(throwing: session.error ?? DownloadFailure.message("Conversão interrompida ou incompatível."))
                    }
                }
            }
        } onCancel: {
            session.cancelExport()
        }
        try Task.checkCancellation()
        let finalBytes = (try FileManager.default.attributesOfItem(atPath: output.path)[.size] as? NSNumber)?.int64Value ?? 0
        guard finalBytes > 0 else { throw DownloadFailure.message("A conversão produziu um MP4 vazio.") }
    }

    private func buildZIP(folder: URL) async {
        guard !zipping else { return }
        zipping = true
        message = "Preparando ZIP com os vídeos concluídos…"
        let target = folder.deletingLastPathComponent().appendingPathComponent(folder.lastPathComponent + ".zip")
        do {
            // Só saídas concluídas são mantidas na pasta: vídeos temporários são apagados em defer.
            let expected = entries.compactMap(\.result)
            for file in expected {
                guard FileManager.default.fileExists(atPath: file.path) else {
                    throw DownloadFailure.message("O arquivo \(file.lastPathComponent) não foi encontrado.")
                }
            }
            // Arquivo ZIP sem duplicação prévia de toda a mídia para outra pasta.
            let newURL = try await Task.detached(priority: .utility) { () throws -> URL in
                let fm = FileManager.default
                if fm.fileExists(atPath: target.path) { try fm.removeItem(at: target) }
                try fm.zipItem(at: folder, to: target, shouldKeepParent: false, compressionMethod: .none)
                return target
            }.value
            archiveURL = newURL
            message = "Tudo pronto. Toque em Salvar todos para exportar \(succeeded) arquivo(s)."
        } catch {
            message = "Não foi possível montar o ZIP: \(error.localizedDescription). Os vídeos continuam na pasta do aplicativo."
        }
        zipping = false
    }
}

final class TransferProgress: NSObject, URLSessionDownloadDelegate {
    let callback: @Sendable (Double) -> Void
    init(callback: @escaping @Sendable (Double) -> Void) { self.callback = callback }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        if totalBytesExpectedToWrite > 0 {
            callback(min(1, Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)))
        }
    }
}
