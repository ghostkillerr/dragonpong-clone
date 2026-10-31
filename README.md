# DragonPong kaynak klon

Bu klasör, DragonPong fikrinden esinlenen **yeni ve kaynak kodlu** bir oyundur.
Eski EXE, decompile edilmiş kod, özgün WAV dosyaları ve eski oyun protokolü bu
klonun çalışması için gerekli değildir. v2 yerel referans ses paketini kullanır;
bu paket bulunmazsa kodla üretilen efektlere döner.

## Çalıştırma

Windows'ta Python 3.12 veya üstüyle:

```powershell
cd clone
python -m pip install -r requirements.txt
python run_offline.py
```

`start_clone.bat` internet odalarını mevcut VPS'deki 8870 portuna bağlar.
Arkadaşlara verilen Windows paketinde aynı dosya `update_launcher.ps1` üzerinden
GitHub'daki `update.json` dosyasını kontrol eder. Yeni sürümün ZIP dosyasını
indirir, SHA-256 ile doğrular, oyun açılmadan EXE'yi değiştirir ve eski EXE'yi
`.previous` adıyla saklar. Çevrimdışıysa kurulu sürüm açılır. Bu mekanizma
ancak paketi `start_clone.bat` ile başlatan oyunculara işler.

Yeni istemci sürümünü yayımlama sırası:

1. `build_exe.bat` ile EXE oluştur ve oyun testlerini çalıştır.
2. `python build_client_update.py 2.5.0` ile `dist_update` içindeki güncelleme
   ZIP'ini, ilk kurulum ZIP'ini ve manifesti üret.
3. İki ZIP'i aynı sürüm etiketiyle (`v2.5.0`) GitHub Release'e yükle.
4. ZIP'in indirildiğini doğrula; ardından üretilen `update.json` dosyasını
   deponun `main` dalındaki dosyayla değiştir. Manifest son yayımlanır.
5. Arkadaşların ilk kurulum ZIP'ini bir kez indirmesi
   gerekir. Sonraki EXE sürümleri açılışta alınır.

Kamuya açık güncelleme ZIP'i yalnızca yeni EXE'yi içerir. Yerel referans ses
dosyalarını GitHub Release'e yükleme. Turnuva için istemci sürüm zorlaması
gerekiyorsa ayrıca sunucu sürüm denetimi eklenmelidir.
Yerel geliştirme için `python -m dragonpong.server --host 127.0.0.1 --port 8870`
ve ardından `python run_offline.py` çalıştırın; Python komutunda varsayılan
sunucu adresi `127.0.0.1`. Başka bir sunucu için `DRAGONPONG_CLONE_HOST`
ortam değişkenini ayarlayın.

Yeni istemci oda listesinden sunucu sürümünü öğrenir. Güncel sunucuda küçük
durum paketleri kullanır; eski v2 sunucuda eski protokolle çalışmaya devam eder.
Oyuncu güncellemeleri 60 Hz, izleyici güncellemeleri 20 Hz'dir. Bağlantı
gecikmesi maç sırasında skorun yanında gösterilir ve topun gösterilen konumu
bu ölçüme göre öngörülür. Maçın fizik ve skor kararı sunucudadır.

Sunucu oda listesinde `step_ack` özelliğini bildirirse istemci her hareket
komutuna artan bir `seq` ekler. Sunucu komutu bir kez uygular ve işlediği son
numarayı tam durumda `step_ack`, küçük karede `a` alanıyla bildirir. İstemci
yalnızca kendi raketini onay gelene kadar yerel olarak gösterir; vuruş, sınır ve
skor hesabı sunucuda kalır. Özelliği bildirmeyen eski sunucuda hareketlerin
gösterimi önceki gibi doğrudan sunucu konumunu izler. Geçiş sırası: önce sunucu,
sonra istemci; sunucu geri alınırsa yeniden bağlanan istemci eski davranışa döner.

## Oynanış

- Ana menüde adını yaz; çevrimdışı veya çevrimiçi odaya gir.
- İki oyuncu karakterlerini seçtikten sonra oda sahibi hedef skor, kalkan ve
  rastgele sessiz top ayarlarını yapıp **Başla** seçer.
- Çevrimdışında karakter seçiminden sonra aynı ayarlar ve bot zorluğu görünür.
- Maçta sol/sağ ok veya A/D ile bir adım at; yukarı ok veya boşlukla servis/vuruş yap.
- İzleyici sol/sağ okla iki oyuncunun ses perspektifi arasında geçer.
- Escape ana menüye döner. Ad ve ayarlar `%LOCALAPPDATA%/DragonPongClone` altında saklanır.

## Ses

Her ses olayı sahada bir konuma sahiptir. Kulaklık çıktısı MIT Media Lab'in
ölçülmüş KEMAR HRTF verisiyle iki kulak için ayrı ayrı evrişim uygular. Böylece
sağ/sol, ön/arka ve yükseklik ipuçları sesin içine işlenir. Hareketli top da
aynı ölçümlere göre konumlanır. Veri kümesinin kaynağı ve atfı
`THIRD_PARTY_NOTICES.md` içindedir. Ağ üzerinden PCM taşınmaz; sunucu konumları
iletir, her istemci sesi yerel olarak üretir. Kulaklık önerilir. KEMAR genel bir
baş ölçümüdür; kişiden kişiye ön/arka algısı değişebilir.

## Durum

v2.2'de release_v7 özellik denetiminde bulunan klavye, profil, fare/kontrolcü
ve izleyici giriş eksikleri giderildi. [Özellik karşılaştırması](V7_COMPARISON.md).

v2.1'de fazla yan duvar sekmesine neden olan vuruş sonrası konum ve derinlik
hesabı düzeltildi. [Fizik karşılaştırması](PHYSICS_COMPARISON.md) özgün EXE ile
ölçülen farkı, düzeltmeyi ve yeni uzun ralli testlerini açıklar.

Motorun karşılaştırılan 7.108 durumunda özgün x86 koduyla aynı sonuç alındı.
Bütün oyunun birebirliği henüz kanıtlanmadı: kapsam ve açık farklar [PARITY.md](PARITY.md),
bağımlı modül kontrolleri [REGRESSION.md](REGRESSION.md) içinde.
Kaynak klon sunucusu VPS'de eski oyundan ayrı 8870 portunda çalışır.
Oyuncular v2 kaynak istemcisini kullanmalıdır; eski kaynak v1 protokolü reddedilir.

Yerel sesler `reference_sounds/Sounds` altında. [Ses rehberi](reference_sounds/SESLER.md)
dosyaları ve karşılıklarını listeler. Aynı isimli WAV dosyasını değiştirip oyunu
yeniden başlatabilirsin. 143 özgün dosya yerel pakettedir, MIT kaynak ZIP'ine dahil değildir.
Yeni ses kökü için `DRAGONPONG_SOUND_DIR` ortam değişkenini kullanabilirsin.

Test: `python -m unittest discover -s tests -v`.
