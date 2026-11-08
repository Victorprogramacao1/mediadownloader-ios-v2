#!/usr/bin/env python3
"""Verificações estáticas de consistência da distribuição. Não substitui Xcode."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Verificacao(unittest.TestCase):
    def test_arquivos(self):
        for path in [
            'MediaDownloaderIOS/MediaDownloaderApp.swift',
            'MediaDownloaderIOS/DownloadStore.swift',
            'MediaDownloaderIOS/ContentView.swift',
            'project.yml',
            '.github/workflows/gerar-ipa.yml',
            'scripts/package-ipa.sh',
        ]:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_youtube_local(self):
        s = (ROOT / 'MediaDownloaderIOS/DownloadStore.swift').read_text()
        self.assertIn('YouTube(url: link, methods: [.local])', s)
        self.assertNotIn('methods: [.remote]', s)
        self.assertNotIn('methods: [.local, .remote]', s)
        self.assertIn('streams(withExactResolution: 1080)', s)
        self.assertIn('filterAudioOnly()', s)
        self.assertIn('AVAssetExportPreset1920x1080', s)

    def test_queue_and_export(self):
        s = (ROOT / 'MediaDownloaderIOS/DownloadStore.swift').read_text()
        view = (ROOT / 'MediaDownloaderIOS/ContentView.swift').read_text()
        self.assertIn('1...100', s)
        self.assertIn('for index in entries.indices', s)
        self.assertIn('zipItem(at: folder', s)
        self.assertIn('ShareLink(item: archive)', view)
        self.assertIn('Salvar todos', view)

    def test_github_build_and_dependencies(self):
        p = (ROOT / 'project.yml').read_text()
        workflow = (ROOT / '.github/workflows/gerar-ipa.yml').read_text()
        self.assertIn('alexeichhorn/YouTubeKit.git', p)
        self.assertIn('exactVersion: 0.4.9', p)
        self.assertIn('ZIPFoundation', p)
        self.assertIn('CODE_SIGNING_ALLOWED=NO', workflow)
        self.assertIn('package-ipa.sh', workflow)

if __name__ == '__main__':
    unittest.main(verbosity=2)
