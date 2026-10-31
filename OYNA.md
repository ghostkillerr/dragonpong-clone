# Kaynak klonunu oyna

`start_clone.bat` dosyasını aç. Paketli EXE varsa başlatıcı yeni sürümü
denetler; yeni paket indirilip SHA-256 doğrulandıktan sonra oyun açılır.
İnternet yoksa mevcut sürüm açılır. EXE dosyasını doğrudan açarsan güncelleme
denetimi yapılmaz. Oyun penceresinden adını yazıp çevrimdışı,
oyuncu veya izleyici olarak bağlan. Çevrimiçi oyuncular aynı v2 sürümünü kullanmalıdır.

Oyuncu bağlanınca bekleyen oda yoksa otomatik yeni oda açılır. Varsa adı yazan
oyuncunun odasını veya **Yeni oda oluştur** seçeneğini seç. İzleyici odalardan
birini seçer; maçta sol/sağ okla oyuncu perspektifini değiştirir.

Maçta sol/sağ ok veya A/D ile bir adım at. Yukarı ok veya boşlukla servis at ve
yaklaşan topa vur; raket topu otomatik olarak geri göndermez.
Escape ana menüye döner. Kulaklık, HRTF 3B ses için önerilir.

Menüde yukarı/aşağı ve Enter kullanılabilir. Odalar listesindeki yeni oda satırı
Enter ile seçilir. Ayarları sağ/sol okla değiştir; ad ve ayarlar Başla'dan önce de
kaydedilir. İzleyici sağ/sol oka tekrar basarak oyuncular arasında döner.
Sol fare tıklaması vuruştur; tekerleğin üç adımı bir saha adımıdır. Bağlı
kontrolcünün ilk düğmesi vuruş, çubuk/yön pedi harekettir. Maçta PageUp/PageDown
müzik sesini ayarlar.

Sunucu `ekransizoyuncular.gen.tr:8870` adresindedir. Oyun kaynakları ve
MIT KEMAR veri atfı ayrı kaynak paketinde bulunur.
Maç sırasında skorun yanında bağlantı gecikmesi görünür. Yeni istemci eski
sunucuyla da bağlanır; güncel sunucuyla daha az veri kullanan protokolü seçer.

Bu yerel referans paketi özgün sesleri içerir; sesler MIT lisansına dahil değildir.
`reference_sounds/SESLER.md` hangi WAV'ın ne işe yaradığını gösterir. Aynı yoldaki
dosyayı değiştirip oyunu yeniden açabilirsin. Özgünlüğü doğrulanan ve eksik kalan
bölümler `PARITY.md` dosyasındadır.
