# Modül regresyon kaydı

## 29 Ekim 2026 — yan sekme düzeltmesi

Denetim tabanı: `cc7764a`. engine → server/audio/run_offline bağımlılığı devam ediyor.
Değişen motor davranışı: BE vuruş aktarımının başlangıç konumu ve alıcı derinliği.
Yeni test noktaları: temas konumunun rakete sıfırlanması, art arda ortalanmış
vuruşlar, iki alıcı yönünde float32 eşitliği; `verify_rallies.py` gerçek native
alıcı dalını ve uzun rallileri kapsar. Önceki test kapsamındaki açık bu raporda korunur.

Kabul: `python -m unittest discover -s tests -v` (39 test, çıkış 0),
`python verify_native.py` (7.108 karşılaştırma, çıkış 0), `python verify_rallies.py`
(25.687 uçuş adımı ve üç uzun ralli, çıkış 0). Kullanıcının yerel referansı aynı
SHA-256 ile doğrulandı. Yerel emülasyon, Tk ve geçici TCP testleri kullanıldı;
ayrıntılar PHYSICS_COMPARISON.md'de. Tarihsel aşağıdaki kayıtlar v2'ye aittir.

Dağıtım: v2.1 EXE derlendi; paketli gerçek ses/Tk kontrolünde 143 varlık, 30 skor
ve çalışan top doğrulandı. VPS hizmeti güncellendi; `verify_public.py` iki oda,
dört oyuncu ve bir izleyiciyle çıkış 0 verdi. Dağıtım öncesi yedek:
`/opt/dragonpong/clone-backup-1793284594377977482`.

Başlangıç: DragonPongClone_source_v1.zip yerel arşivi; Git deposu yok.
v1'de 9 test vardı; bunlar özgün davranış eşdeğerliğini kanıtlamıyordu.
Değişiklikler: engine, audio, soundbank (yeni), client, server, run_offline,
yerel varlık hazırlama, native karşılaştırma, testler ve paketleme.

Bağımlılık kanıtı: `rg -n '^(from|import) ' dragonpong run_offline.py`.
engine → server, audio, run_offline; soundbank → audio → run_offline;
client → run_offline. Ağ sözleşmesi server ↔ client/run_offline.

| Modül | Tüketenler | Kabul komutu |
|---|---|---|
| engine | server, audio, arayüz | `python -m unittest discover -s tests -p test_rules_regression.py -v` ve `python verify_native.py` |
| soundbank/audio | arayüz | `python -m unittest discover -s tests -p test_soundbank.py -v` ve `test_engine.py` |
| server/client | arayüz/izleyici | `python -m unittest discover -s tests -p test_server.py -v` |
| run_offline | EXE paketi | `python -m unittest discover -s tests -p test_ui.py -v` |

Davranış değişince ilgili modül ve bütün tüketenlerin kontrolleri çalıştırılır.
Bu değişiklik için toplu kabul: `python -m unittest discover -s tests -v`.
Yerel Windows/Python, geçici test profili, yerel geçici TCP portları; native test
EXE'yi emüle eder, ağ ve gerçek ses çıkışı kullanmaz. Kullanıcının test yetkisi kapsamındadır.

Son ölçüm: 36 test başarılı (çıkış 0), native 7.108 karşılaştırma başarılı (çıkış 0).
İlk çalıştırmada eski iki testin 10 ms varsayımı 17 ms fizik adımıyla uyuşmadı;
testler bir fizik adımı kullanacak şekilde düzeltildi. Sonraki motor, ses, arayüz
ve ağ kontrolleri birlikte başarılı. Bütün oyun eşdeğerliği kararı PARITY.md'deki
eksikler nedeniyle açık tutulur; modül testlerinin geçişi bu eksikleri kapatmaz.

Ek kabul kanıtları (28 Ekim 2026):

- `verify_public.py`: VPS üzerinde iki oda, dört oyuncu, bir izleyici; ayarlar,
  servis, aynalanan kontroller, oda izolasyonu ve perspektif; çıkış 0.
- `soak_verification.json`: dört zorlukta dörder farklı tohumla 16 tam maç,
  toplam 126.730 simülasyon adımı, takılma/sonsuz değer yok. Hedef skor 3;
  30 skorlu bitiş ayrıca motor ve sunucu testlerinde doğrulandı.
- `audio_verification.json`: 2.000 adet 512 örnekli blok; hareketli top ve iki
  kalkan döngüsünde p99 0,521 ms, blok bütçesi 10,667 ms. Bu CPU ölçümüdür,
  fiziksel kulaklık gecikmesi ölçümü değildir.
- PyInstaller derlemesi çıkış 0. Paketli EXE `--verify-package` kontrolü
  `package_verification.json` dosyasında: gerçek Tk/ses aygıtı, 143 varlık ve
  30 skor ayarı. Kullanıcının kayıtlı profili yerine geçici profil kullanılır.
- `dragonpong-clone.service` aktif. Son geri dönüş yedeği:
  `/opt/dragonpong/clone-backup-1793206487833608014`. Eski v7 rölesi değiştirilmedi.
