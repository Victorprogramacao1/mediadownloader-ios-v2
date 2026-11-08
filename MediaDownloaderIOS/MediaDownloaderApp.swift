import SwiftUI

@main
struct MediaDownloaderApp: App {
    @StateObject private var store = DownloadStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
