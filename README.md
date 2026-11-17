# cappus: skill CapCut untuk Claude

Skill agar Claude (Opus, dsb.) bisa **mengedit video dan menyerahkan hasilnya sebagai draft CapCut
yang tetap bisa diedit**. Hasilnya bukan MP4 jadi, melainkan proyek CapCut biasa. Potongan klip, teks,
transisi, efek, filter, animasi, keyframe, dan caption semuanya muncul di timeline CapCut dan bisa
diubah sesukanya.

Semua efek yang dipakai adalah resource asli CapCut: sekitar 6.000 transisi, efek, filter, animasi, dan
font, lengkap dengan ID internalnya. Dari jumlah itu sekitar 1.100 gratis. Builder menolak nama yang
tidak ada di katalog, dan secara default juga menolak item **Pro**, supaya draft bisa diekspor tanpa
langganan.

## Isi repo

```
skills/capcut-editor/
  SKILL.md                    instruksi utama untuk Claude
  references/
    edit-spec.md              format "edit spec" (JSON) yang ditulis Claude
    editing-craft.md          panduan pacing, resep per genre, palet efek per mood
    capcut-notes.md           batasan, langkah lanjutan di CapCut, troubleshooting
  scripts/
    probe.py                  analisis media: info, contact sheet, scene, jeda bicara, beat musik
    catalog.py                cari transisi/efek/filter/animasi/font yang ada di CapCut
    build_draft.py            spec JSON -> draft CapCut (validasi + tulis)
    inspect_draft.py          baca draft yang sudah ada (termasuk hasil edit manual)
    aliases.json              ~490 alias bahasa Inggris untuk resource gratis
  requirements.txt
examples/
  demo.json                   contoh spec yang memakai hampir semua fitur
  make_test_media.py          membuat media sintetis untuk demo
.claude-plugin/               manifest agar repo bisa dipasang sebagai plugin Claude Code
```

## Kebutuhan

- CapCut desktop (versi internasional) di Windows atau macOS. Sudah dicoba menulis draft untuk CapCut 8.0.1.
- Python 3.9+ dan `ffmpeg`/`ffprobe` di PATH.
- `python -m pip install -r skills/capcut-editor/requirements.txt` (berisi `pycapcut` dan `numpy`).

Claude harus berjalan di komputer yang sama dengan CapCut (Claude Code atau Claude desktop), karena
draft ditulis langsung ke folder draft CapCut.

## Pemasangan

**Sebagai plugin Claude Code** (dari folder repo ini):

```bash
claude plugin marketplace add ./
```

```bash
claude plugin install cappus@cappus
```

**Atau salin skill-nya saja** ke `~/.claude/skills/capcut-editor` (Windows:
`%USERPROFILE%\.claude\skills\capcut-editor`).

## Cara pakai

Cukup minta Claude, misalnya:

> Edit video di folder D:\Liburan jadi reels 9:16 sekitar 20 detik, ikut beat lagu song.mp3, gaya
> sinematik, kasih judul di awal.

Claude akan:

1. menganalisis klip (melihat contact sheet, mencari beat dan jeda),
2. menyusun rencana edit dan menulis spec JSON,
3. memvalidasi spec terhadap katalog CapCut,
4. menulis draft ke folder CapCut, lalu menjelaskan hasilnya dan bagian yang perlu Anda cek.

Setelah itu buka CapCut. Draft muncul di daftar proyek (kalau CapCut sedang terbuka, kembali ke home
atau restart dulu). Untuk revisi, minta Claude lagi: Claude mengubah spec lalu membangun ulang draft.

## Mencoba manual

```bash
python examples/make_test_media.py
```

```bash
python skills/capcut-editor/scripts/build_draft.py examples/demo.json --check
```

```bash
python skills/capcut-editor/scripts/build_draft.py examples/demo.json --overwrite
```

```bash
python skills/capcut-editor/scripts/catalog.py transition glitch
```

## Batasan

Speed ramp (kurva), auto caption dari suara, hapus background, keyframe dengan easing, color wheel
atau HSL, sound effect dari library CapCut, dan ekspor otomatis tidak bisa dibuat lewat draft. Semua itu
bisa dilakukan dengan satu klik di CapCut; daftarnya ada di `references/capcut-notes.md`. Media di-*link*,
tidak disalin, jadi jangan pindahkan file sumber setelah draft dibuat.

Draft dibuat dengan library [pycapcut](https://github.com/GuanYixuan/pyCapCut), yang juga menjadi
sumber katalog resource CapCut.
