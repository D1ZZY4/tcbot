# Federasi

Apa itu TCF, asas, tujuan, ruang lingkup, riwayat TCF, dan cara mengubah aturan.

## Tentang TCF

TCF adalah kumpulan grup Telegram mandiri yang dibentuk karena minat bersama pada perangkat Transsion. Tujuannya belajar, berbagi, dan membangun komunitas yang aman serta tertib.

Setiap grup tetap mengatur dirinya sendiri. Aturan ini hanya standar minimum bersama, bukan organisasi resmi atau badan hukum.

Aturan ini menggantikan tata tertib lama yang tidak punya definisi, pembagian tugas, dan cara penegakan yang jelas.

## Istilah

- **TCF**: kumpulan grup Telegram mandiri yang sepakat memakai aturan ini. Anggotanya adalah grup, bukan orang. Bukan organisasi resmi atau badan hukum.
- **Grup Anggota**: grup Telegram yang memenuhi tiga syarat:

  1. admin menyatakan persetujuan dan dicatat di grup koordinasi admin atau kanal resmi TCF;
  2. grup tercantum dalam daftar anggota di kanal resmi TCF; dan
  3. persetujuan belum ditarik kembali.

- **Admin Federasi**: admin grup anggota yang mengurus koordinasi antargrup, daftar anggota, dan daftar blokir federasi. Tidak mengurus internal grup lain.
- **Administrator**: anggota yang ditunjuk admin grup untuk mengelola keanggotaan dan teknis grup.
- **Moderator**: anggota yang ditunjuk admin grup untuk mengawasi percakapan dan menghapus konten. Tidak bisa menjatuhkan sanksi, kecuali ditentukan lain secara tertulis.
- **Pengelola**: Administrator dan Moderator.
- **Platform Komunitas**: grup anggota, kanal resmi TCF, dan grup koordinasi admin. Aturan ini tidak berlaku di tempat lain.
- **Anggota**: orang yang bergabung di minimal satu grup anggota. Keanggotaan melekat pada grup, bukan pada TCF.
- **Pengembang**: anggota yang membuat, mengembangkan, merawat, atau merilis Karya.
- **Karya**: perangkat lunak, ROM, kernel, modul, aplikasi, tema, dokumentasi, panduan, tulisan, karya visual, atau hasil pengembangan lain.
- **Pelanggaran**: perbuatan yang memenuhi unsur larangan dan dibuktikan sesuai cara penegakan. Kritik atau beda pendapat bukan pelanggaran, kecuali caranya melanggar.
- **Tindakan Moderasi Segera**: pengamanan sementara berupa hapus konten, pembisuan dengan batas waktu tertentu, atau pembatasan tautan. Bukan sanksi.
- **Sanksi**: tindakan setelah pemeriksaan, berupa teguran, peringatan, pembisuan, pengeluaran, blokir federasi, atau pencabutan kewenangan.
- **Keputusan Moderasi**: keputusan tertulis berisi identitas, aturan yang dilanggar, bukti, tingkat pelanggaran, sanksi, dan cara keberatan.
- **Keberatan**: permintaan pemeriksaan ulang oleh pihak yang kena sanksi kepada organ yang berbeda.
- **Konflik Kepentingan**: Pengelola yang memeriksa perkara adalah pelapor, pihak dirugikan, pihak diperiksa, atau punya hubungan pribadi yang meragukan.
- **Hari**: hari kalender.
- **Bukti**: pesan, tangkapan layar, tautan, berkas, log, keterangan saksi, atau dokumen yang bisa diperiksa ulang.

## Asas penegakan

1. Tertulis: larangan dan sanksi harus tertulis lebih dulu.
2. Sama: semua anggota dan pengelola diperlakukan sama.
3. Proporsional: sanksi sesuai tingkat pelanggaran dan dampaknya.
4. Akuntabel: keputusan berbasis bukti tertulis.
5. Tidak berpihak: pemeriksa bebas konflik kepentingan.
6. Privasi: data pribadi hanya dipakai seperlunya untuk moderasi federasi. Tata kelola data bot dijelaskan di aturan Doxing dan Privasi.
7. Bebas berpendapat: kritik dan pertanyaan boleh, selama tidak melanggar.
8. Otonomi grup: tiap grup tetap mandiri; aturan ini hanya standar minimum.

## Tujuan

1. Kepastian tentang larangan dan akibatnya.
2. Lindungi anggota dari konten ilegal, pelanggaran privasi, penipuan, dan penyalahgunaan wewenang.
3. Penegakan yang adil dan bisa diuji ulang.
4. Jaga grup sebagai ruang belajar yang aman.

## Ruang lingkup

1. Berlaku di grup anggota, kanal resmi, dan grup koordinasi admin.
2. Berlaku juga di luar grup jika memakai nama atau logo TCF tanpa hak, membocorkan Informasi Pribadi atau Materi Pengujian, atau menjadi kelanjutan langsung dari perbuatan di grup.
3. Percakapan pribadi biasa tidak diatur.
4. Aturan tambahan grup hanya berlaku jika tertulis, diumumkan, tidak bertentangan, tidak membuat sanksi baru, dan bisa diakses anggota.
5. Jika bertentangan, yang berlaku aturan ini.
6. Admin grup bisa menarik grupnya kapan saja lewat pernyataan di grup koordinasi. Berlaku sejak dicatat, tidak surut, dan tidak menghentikan perkara yang berjalan.
7. Ban dan mute yang dijatuhkan staf federasi berlaku lintas grup: keduanya dicatat satu kali dan diterapkan ke semua grup terhubung. Kick dan warn berlaku di grup tempat perintah dijalankan. Warn yang mencapai batas memicu ban federasi otomatis; warn lintas grup juga bisa memicu ban federasi bila batas federasi diaktifkan. Tidak ada "ban grup" terpisah dari ban federasi.

## Aturan penting

1. Tidak ada sanksi tanpa aturan tertulis. Arahan lisan atau kebiasaan tidak bisa jadi dasar.
2. Jika ragu, pilih penafsiran yang menguntungkan pihak yang diperiksa.
3. Satu perbuatan hanya kena satu aturan, yaitu yang paling khusus. Tidak boleh dihukum dua kali.

## Penegakan lewat bot

Bot federasi menjalankan empat tindakan dengan jangkauan yang berbeda:

- **Ban federasi** (`/tcban`, `/tcunban`): satu keputusan berlaku di semua grup terhubung dan grup utama, dengan bukti wajib dan dapat diajukan banding.
- **Mute federasi** (`/tcmute`, `/tcunmute`): pembatasan pesan berlaku di semua grup terhubung dan grup utama, bisa tetap atau berjangka.
- **Kick** (`/tckick`): mengeluarkan target hanya dari grup tempat perintah dijalankan. Tidak mencabut ban atau mute federasi.
- **Warn** (`/tcwarn`): peringatan dicatat per grup. Bila jumlahnya mencapai batas grup, bot menjatuhkan ban federasi otomatis dan warn di grup itu dihapus.

Tindakan yang gagal dikirim ke sebuah grup tetap dicatat sebagai pekerjaan berulang sampai berhasil atau batas percobaan habis. Satu grup yang gagal tidak membatalkan tindakan di grup lain.

## Daftar yang dipelihara Admin Federasi

- Daftar grup anggota, daftar pengelola, dan daftar blokir federasi, disimpan di kanal resmi TCF dan grup koordinasi admin.
- Daftar grup anggota juga memuat keterangan ruang transaksi resmi.
- Setiap perubahan dicatat dengan tanggal dan nama grup.
- Hasil polling di grup koordinasi hanya bahan evaluasi, belum mengubah aturan.

## Perubahan aturan

1. Usulan beserta teks lengkap diumumkan di grup koordinasi dan kanal resmi.
2. Tiap grup anggota punya 1 suara, disampaikan admin grup atau orang yang ditunjuk.
3. Pemungutan suara dibuka minimal 7 hari.
4. Disetujui jika lebih dari separuh suara yang masuk setuju, dan jumlah yang bersuara minimal separuh dari seluruh grup anggota.
5. Hasil dicatat dan diumumkan di kanal resmi.
6. Grup yang tidak setuju boleh keluar dari TCF tanpa dianggap melanggar.
7. Perubahan yang menambah larangan atau memperberat sanksi berlaku paling cepat 7 hari setelah diumumkan dan tidak berlaku surut. Perubahan yang meringankan berlaku untuk perkara yang belum tetap.

## Mulai berlaku

1. Berlaku sejak grup tercantum dalam daftar dan aturan diumumkan di kanal resmi serta tersedia di grup.
2. Sanksi hanya untuk perbuatan setelah lewat 7 hari sejak pengumuman di grup itu.
3. Tindakan Moderasi Segera tetap bisa dilakukan sejak hari pengumuman.
4. Berlaku tanpa batas waktu sampai diubah atau dicabut.
5. Grup keluar dari TCF tidak menghapus sanksi yang sudah tetap dan kewajiban kerahasiaan.

## Catatan

- TCF bukan badan hukum, jadi tidak ada struktur organisasi resmi.
- Grup boleh punya aturan tambahan asal tidak bertentangan dengan aturan ini.
- Tindakan Moderasi Segera adalah pengamanan, sanksi adalah hukuman. Caranya berbeda.
