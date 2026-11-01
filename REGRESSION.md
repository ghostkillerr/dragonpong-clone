# Modül regresyon kaydı

## 1 Kasım 2026 — çevrimiçi temas ve yerel Windows denetimleri

`engine.py` değiştirilmeden kareye bağlı vuruş, 250 ms gol/temas toleransı,
motorla aynı uçuş tahmini, eski veri koruması ve sınırlı TCP gönderimi eklendi.
Tkinter yerine wxPython denetimleri, erişilebilir bildirimler, Tab/Shift+Tab,
pencereye dönüşte odak ve ekranlar arasında bildirim temizliği uygulandı.

163 test: 161 başarılı, özgün sesler bulunmadığı için 2 atlandı. İki sunumda
2.928'er senaryo: 1.548 → 1.712 kabul, 164 ek kabul, önceki kabullerden kayıp 0.
Son GUI düzenlemeleri sırasında matrisin ağ/motor kaynakları değişmedi;
arayüzün son hâli toplu test ve paketli GUI ile doğrulandı.

Aynı yerel EXE ile iki oyuncuda hazırlanmış geç temas, eski giriş engeli,
toparlanma, tek hareket onayı, Tab odağı, oda kapanışı ve elle yeniden bağlantı
kontrolleri geçti. NVDA ile karakter seçimi/onay denetimleri ve F6 konuşması
elle doğrulandı. Gerçek internet, farklı PC ve bütün NVDA kabulü açık.
Yöntem ve tekrar komutları NETPLAY_DOGRULAMA.md; makinece okunabilir özet
netplay_validation_summary.json içinde. EXE ve ham test/profil kayıtları eklenmedi.


## V7 özellik denetimi — v2.2, 29 Ekim 2026

Değişen modüller: run_offline (odak, tuşlar, kalıcı profil, fare), controls (yeni
SDL giriş modülü), audio (müzik katsayısı), server (izleyiciye ilk durum).
Bağımlılık: controls/audio/client/engine → run_offline; server → çevrimiçi UI.
Karşılaştırma kapsamı V7_COMPARISON.md'de. Kabul komutu
`python -m unittest discover -s tests -v`: 48 test, çıkış 0. Yeni regresyonlar
anında kayıt, geçersiz profil, oda Enter/yeni oda, iki yönde izleyici döngüsü,
izleyicinin ayar ekranı, fare, kontrolcü kenar/tekrar/odak ve bitmiş maç durumudur.
Fizik dosyası bu denetimde değiştirilmedi. GitHub işlemi yapılmaz.

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

Ek yerel doğrulama (31 Ekim 2026): hareket sıra numarası ve istemci raket
tahmini için 82 test geçti. Gecikmiş/eski onay, yinelenen ve ters yönlü komut,
iki oyuncu koordinatı, saha sınırı, bağlantı hatası, bitiş ve eski sunucuya
dönüş senaryoları kapsandı. Yerel TCP testinde onay küçük durum paketine ulaştı.
Özgün x86 karşılaştırmasında 7.108 hareket/vuruş durumu sıfır fark, 1.080 vuruş
açısı en çok 7,2e-15 derece fark ve 25.687 uzun ralli uçuş adımı önceki
sonuçlarla eşleşti. `engine.py` değiştirilmedi; yerel raket tahmini skor veya
vuruş kararı üretmez. Dağıtım öncesi canlı sunucu `step_ack` özelliğini
bildirmiyordu; istemcinin eski davranışa dönüşü gerçek bağlantıyla doğrulandı.
