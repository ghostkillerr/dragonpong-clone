# Çevrimiçi vuruş ve bağlantı doğrulaması

1 Kasım 2026 — yerel geliştirme. Başlangıç kaynak commit'i `7362a0c`.
Bu çalışma henüz yayımlanmış EXE veya canlı sunucu sürümü değildir.

## Yeniden üretilen sorunlar

1. Oyuncu geçerli vuruş alanındaki topa bastığı hâlde komut ulaşana kadar
   sunucu golü kesinleştirebiliyordu. İki oyuncu yönünde de test önce başarısız oldu.
2. İstemci yan duvarda geometrik yansıtma kullanıyordu; motor 17 ms adımda
   float32 taşma ve yön değiştirme uygular. Örnekte tahmin x=8,59,
   motor x=8,729999542236328 idi. Temasın tarafı ve raket mesafesi değişebiliyordu.
3. Görsel tahmin her çizimde ilerlerken hareketli ses yalnızca gelen durum
   paketinde güncelleniyordu. Basış anındaki hesap oyuncunun son duyduğu
   konumla aynı olmayabiliyordu.
4. Sunucu bir takılmadan sonra geçen sürenin yalnızca 50 ms'sini ilerletiyordu.
   Komutun maç döngüsünden önce işlenmesi de ileri tahmin edilmiş geçerli
   teması reddedebiliyordu.
5. Eski yüksek ping ölçümü topu fazla öne taşıdığında, geçerli görünen erken
   vuruş reddediliyordu. Bunun ayrı testi de düzeltmeden önce başarısız oldu.

## Uygulanan davranış

- Yeni istemci/sunucu `strike_ref_v1` özelliğinde anlaşır. Vuruş, oyuncuya
  gerçekten gönderilmiş kare numarasını ve son sunulan ses/görüntü tahminini
  taşır. Sunucu aynı uçuşu, kare yaşını, yönü ve kendi raket konumunu denetler.
  İstemcinin gönderdiği top veya skor koordinatlarına güvenilmez.
- Tahmin motorla aynı float32 uçuş adımlarını, yan duvar davranışını,
  fizik adımı fazını ve kalkan bitişini kullanır. Yeni protokolde yaklaşık
  mevcut konum için yarım RTT kullanılır; tahmin 200 ms ile sınırlıdır.
- Ses ve çizim aynı hesaplanan konumu kullanır. Ağ paketi gelmese de
  ses konumu çizimlerde güncellenir. Basış son sunulan kareye bağlanır.
- Hızlı topun tahmini bütün temas alanını atlarsa son geçerli motor adımı
  kısa süre sunulur. Bekleyen gol paketi geldiğinde aynı uçuşa ait, gerçekten
  gönderilmiş son hareketli kare korunabilir. Basış o özgün kareyi kullanır;
  sunucudaki 250 ms sınırı uzatılmaz. İzleyici ve eski protokolde bu tutma yoktur.
- Protokol 3 pong/kare paketlerinde sunucunun monoton saat bilgisi bulunur.
  Eşleşen pong, sunucunun en az hangi zamana ulaştığını kanıtlar. İstemci
  saat başlangıçlarını veya gidiş/dönüş gecikmelerini eşit varsaymadan eski
  paketleri ayırt edebilir. Yeni protokolde 250 ms güncellenmemiş veya bu
  alt sınıra göre kesin eskimiş veride ses ve yeni oyun komutları kesilir.
  Eski protokolde önceki bir saniyelik sınır korunur.
- Temas, aynı uçuşta en fazla 250 ms geriden doğrulanabilir. Gol bu kısa
  pencere boyunca geçici bekler; geçerli vuruş gelirse gol yayımlanmadan
  oyun devam eder. Kesinleşmiş skor ve bitmiş maç geri alınmaz.
- Kaynağı 500 ms'den eski, başka uçuşa ait, gönderilmemiş, gol bekleme
  ekranına ait veya raketin dışında kalan referanslar reddedilir.
- Eski yüksek ping nedeniyle görüntü sunucunun önündeyse basış kısa süre
  tamponlanır; vuruş ancak normal motorun temas alanında uygulanır.
  Tampon başka uçuşa veya sonraki servise taşınmaz.
- Vuruş sırası yinelenen komutların iki kez uygulanmasını önler. Reddedilen
  vuruş için oyuncuya gecikme, yön, mesafe veya servis beklemesi açıklanır.
- Sunucu, 250 ms'ye kadarki kısa duraklamayı fizik adımlarıyla tamamlar.
  Komut işleme ve maç döngüsü aynı saati kullanır; zaman iki kez ilerlemez.
- Son gol/kazanma paketi yavaş istemci için sıradan kare gibi atlanmaz.
  Son gönderimi boşaltma süresi sınırlıdır. Gol beklerken oyuncu ayrılırsa
  oda kapanır ve geçici gol skora dönüşmez.

`engine.py` değiştirilmedi. Gol bekletme ve kareye bağlı temas, çevrimiçi
sunucunun davranışıdır; özgün oyunun tüm ağ davranışlarıyla eşdeğerlik iddiası yoktur.

## Test sonuçları

| Kontrol | Sonuç |
| --- | --- |
| unittest paketi | 163 test: 161 başarılı, 2 özgün ses testi atlandı; hata yok |
| Son test süresi | 11,178 saniye |
| Motorla tahmin karşılaştırması | 5.000 tohumlu uçuşta konumlar tam eşit |
| Sanal ağ matrisi | Her sunum seçeneğinde 2.928 senaryo; yeni sunumda 1.200.092 adım |
| Modelde gönderilen vuruş | 2.568 |
| Kabul edilen vuruş | 1.712: 758 normal, 948 gecikme telafisi, 6 ileri görüntü tamponu |
| Süre/kare sınırı dışında reddedilen | 856 |
| Kullanılabilir vuruş penceresi oluşmayan | 360; tamamı 650 ms kesinti profili |
| Modelin tanımlı beklenen davranışından sapma | 0 |

Anlık temas kontrolü karşılaştırmasına göre 950 basış kurtarıldı. Bu sayı,
aynı basışta yalnızca güncel sunucu konumunu kontrol eden alternatifle
karşılaştırmadır; yayımlanmış eski EXE üzerinde yapılmış canlı A/B ölçümü değildir.

Önceki sunumu aynı kaynaklarda `--presentation original` ile çalıştırınca
1.548 vuruş kabul edildi; yeni sunumda 1.712 oldu. 164 ek kabul: mobil
160 ms profilde 24, TCP 180 ms beklemesinde 96, yüksek 300 ms profilde 44.
Önceden kabul edilmiş vuruşlardan kayıp yok. Önceki sunumda eski veriden
üretilip reddedilen 216 basış yeni sunumda üretilmedi; kalan 360 kesinti
senaryosu başarılı oynanış sayılmadı. Özet `netplay_validation_summary.json` içindedir.

Yeni sunumda ilave giriş beklemesi olmayan ve 650 ms kesinti profiline ait
olmayan bütün senaryolarda vuruş kabul edildi: 888 alt senaryo. Reddedilen
856 basışın 840'ında 350 ms, 16'sında 80 ms ek giriş beklemesi vardı.

Yerel, normal, mobil ve iki asimetrik hat profilinde; ilk vuruş penceresini
kullanan ve ilave arayüz beklemesi eklenmeyen 348 alt senaryonun tamamında
vuruş kabul edildi. Bu alt grup eski/eksik ping tahmini varyantlarını da içerir.

Matris iki oyuncuyu; 3/15/40/80/120 hızlarını; orta, sağ ve sol duvar
yollarını; 10/60/160/165/300 ms temel RTT profillerini; dalgalanmayı;
180 ms TCP yeniden iletim beklemesini ve 650 ms kesintiyi içerir.
İlk veya son vuruş alanında basma, 0/80/350 ms ilave giriş beklemesi ve
farklı rastgele tohumlar denenir. TCP sırası korunur; UDP gibi bağımsız
paket düşürme simüle edilmez.

Ayrı testler: 20–240 ms sunucu duraklaması ve iki görev işleme sırası,
600 ms donma, tam 1/3/10/30 skorlu maç/servis döngüleri, kalkan ve sessiz
top, temas açısı, katı saha sınırları, yinelenen basış, eski uçuş,
izleyici, gönderim kuyruğu, son skor ve bekleyen gol sırasında kopma.

Gerçek yerel soket testinde iki iş parçacıklı istemci, gidişe 90 ms ve
dönüşe 30 ms bekleme ekleyen TCP vekilinden geçirildi. Her iki oyuncunun
geç ulaşan vuruşu `compensated` yanıtı aldı, skor 0–0 kaldı. Bu vekil
testi bilinen 120 ms yolu kullanır; ping kestirimi ayrı soket testlerinde sınanır.

Ek gerçek soket testi, farklı sunucu saat kökeniyle tek akışta gelen
hareketli/bekleyen-gol karelerini sınadı: yakın temas korundu, 650 ms eski
paket yeni gelmesine rağmen eski sayıldı ve temas sesi olarak sunulmadı.
Matrisin saat alt sınırı, maç öncesinde kurulmuş bir pong ölçümünü modeller;
henüz eşleşmiş pong yoksa kesin sunucu yaşı bilinmez, yerel yaş sınırı uygulanır.

## Tekrar çalıştırma

Depo klasöründe PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe simulate_netplay.py --output netplay_simulation.json
.\.venv\Scripts\python.exe simulate_netplay.py --presentation original --output netplay_simulation_original.json
```

`simulate_netplay.py` her senaryoyu ve çalıştırıldığı kaynakların SHA-256
imzalarını rapora yazar. Ayrıntılı JSON çıktıları yerel olarak üretilir ve
PR'a eklenmez. Depodaki `netplay_validation_summary.json`, kayıtlı sonuçları,
son kaynak imzalarını ve matrisin yeniden kullanım kapsamını içerir.
Son arayüz değişikliklerinde motor, server, client, netplay ve simülasyon
kaynakları aynı kaldı; yalnızca arayüz odağı/bildirim temizliği değişti.

## Yerel paket ve erişilebilirlik kontrolü

Tkinter kaldırıldı; wxPython 4.3.2 gerçek Windows denetimleri kullanılıyor.
Windows'ta NVDA ile karakter seçimi listesinin/onay düğmesinin ad ve türleri
ve paketli uygulamanın F6 ping/dalgalanma konuşması elle doğrulandı.
Diğer dinamik bildirimler erişilebilir ağaçta denetlendi; tüm ekran okuyucu
konuşması için kabul verilmiş sayılmıyor.

Kaynakların son hâliyle oluşturulan yerel EXE açılış kontrolünü geçti:
ses hatası yok, 56 callback, hedef skor 30, hareketli top, frozen=true,
callback_errors boş. Özgün ses sayısı 0; kodla üretilen sesler kullanılıyor.
EXE imzası ve bu kontrolün sonuçları doğrulama özetindedir. EXE yayımlanmadı.

Aynı EXE ile iki gerçek GUI istemcisi 90 ms gidiş/30 ms dönüş vekilinden
geçirildi. Oda/karakter/ayar/başlatma, servis ve hareket çalıştı. İki yönde
hazırlanmış geç temas `compensated` oldu, skor 0–0 kaldı. Düzenek gerçek
EXE basışı gelince motora 100 ms ekler; sıradan internet maçı değildir.

Durum akışı dururken heartbeat sürdü. Eski veride sağ ok ve vuruş sunucuya
gönderilmedi: hareket sayısı 1, vuruş sayısı 3 kaldı. Akış açılınca toparlanma
bildirimi görüldü; sonraki tek sağ ok hareket sayısını 2 ve onayı [0,2] yaptı.
Eş kapanınca oda 0–0 skorla silindi; kalan oyuncu açıklamalı menüye döndü.
Elle yeniden bağlanınca yeni oda açıldı ve eski kapanış bildirimi temizlendi.

Arka planda açılan maçta tıklamadan klavye girişi, Tab/Shift+Tab ile oyun
alanından çıkış/dönüş ve pencere değişiminden sonra seçili düğmenin korunması
aynı EXE'de doğrulandı. İki EXE normal kapandı. Ham GUI kayıtları ve geçici
oyuncu profilleri yerelde tutuldu; depoda doğrulama özeti bulunuyor.

Yeni kurulumda Windows/PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m dragonpong.server --host 127.0.0.1 --port 8870
```

Başka iki terminalde `.\.venv\Scripts\python.exe run_offline.py` açılabilir.
Paketli uygulama için `build_exe.bat` ve ardından `dist/DragonPongClone.exe`
kullanılır. EXE varsayılan olarak `127.0.0.1:8870` adresine bağlanır;
`DRAGONPONG_CLONE_HOST` ve `DRAGONPONG_CLONE_PORT` ile değiştirilebilir.
Açılış kontrolü: `dist/DragonPongClone.exe --verify-package package_check.json`.

## Kabul sınırı ve dağıtım

Bu, olası bütün ağ koşullarının kanıtı değildir. 856 reddetme ve 360 pencere
oluşmaması özellikle görünür tutuldu: uzun donma ve çok geç basış her koşulda
telafi edilemez. Matris bu durumları
beklenen sınır olarak sınıflar; hepsini başarılı oynanış saymaz.

Gerçek internet, farklı bilgisayarlar, fiziksel kulaklık gecikmesi ve bütün
ekran/bildirimlerin NVDA konuşma kabulü henüz tamamlanmadı. Durum akışı
durdurma denemesi tam TCP kopması değildir; ping çalışmaya devam eder.
Özgün 143 WAV bulunmadığından iki test atlandı; özgün EXE karşılaştırması
yeniden çalıştırılmadı. Otomatik maça yeniden bağlanma eklenmedi.

Geçiş sırası sunucu, ardından istemcidir. Özellik eski istemci için açılmaz;
yeni istemci de destek bildirmeyen sunucuda eski vuruş yolunu kullanır.
Dolayısıyla yeni telafi için iki tarafın da güncellenmesi gerekir.
Bu PR kaynak kodu, testler ve doğrulama özetini içerir; release, otomatik
güncelleme manifesti veya canlı sunucu dağıtımı içermez.
