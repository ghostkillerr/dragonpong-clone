# Doğrulama sınırı — 29 Ekim 2026

v2.1: yan duvara fazla sekmeye neden olan vuruş aktarımı ve iki yönün float32
derinlik farkı düzeltildi. [Karşılaştırma raporu](PHYSICS_COMPARISON.md):
39 test, 7.108 fonksiyon karşılaştırması ve 25.687 uçuş adımı. Üç uzun rallide
vuruş ve sekme sayıları özgün kodla eşleşti.

Bu sürümün tamamına **birebir klon** etiketi verilmez. Önceki v1 kaynak motoru
özgün davranış yerine basitleştirilmiş kurallar içeriyordu. v2 bu farkların
ölçülmüş bölümünü düzeltir. Otomatik testlerin geçmesi bütün oyunun eşdeğerliği değildir.

## Özgün makine koduyla karşılaştırılan bölüm

`verify_native.py`, SHA-256 değeri
`937ac8bb55b8265e9359e3db479d9334e5314dab981507fbc06313576fac1341`
olan özgün EXE'nin x86 talimatlarını Unicorn içinde çalıştırır. EXE'yi masaüstünde
başlatmaz. Ses, ağ, rastgele sayı ve saat çağrıları kontrollü sınırlarla değiştirilir;
fizik aritmetiği ve dalları özgün talimatlardır. Sonuç: `native_verification.json`.

| Davranış | Özgün adres | Karşılaştırma |
|---|---|---|
| Top hareketi, duvar yönü, kalkan dönüşü | 0x402541 | 5.000 durum, float32 sonuçları tam eşit |
| Vuruş penceresi, yön, hız artışı, güç kazanma dalları | 0x404bfa ve 0x402281 | 2.020 durum, sınır değerler dahil |
| Servis, adım/sınırlar, kalkan süresi, gol sayımı | 0x404bfa, 0x404988, 0x404a10, 0x402f8d, 0x402541 | 88 ek durum |

Toplam 7.108 karşılaştırma, sıfır fark. Hareket kontrolleri iki tarafta da alıcının
yerel koordinatlarını kullanır. Bunlara eklenen BE alıcı bloğu ve uzun ralli
kontrolleri PHYSICS_COMPARISON.md'dedir. Bütün eski ağ paketlerinin veya gerçek
zamanlamanın eşdeğerliği iddia edilmez.

Doğrulanan kurallar: lateral konum 1..19, bir tuşta bir adım; vuruş için top yaklaşırken
derinlik <6 ve mesafe <3; servis adımları 0,05 ve 0,01; her vuruşta bağımsız 0..5 /100
hız artışı; kalkan 30 saniye boyunca tekrar kullanılabilir; sessiz top vuruş veya golde
sona erer, duvar sesi kalır. Kalkan 1/11, sessiz top 1/21; bot ve insan aynı fonksiyonu
kullanır. Ultra her iki yönde topun mevcut konumunu izler, en az 63 ms arayla adım atar.

## Sesler

143 WAV yerel `reference_sounds/Sounds` altında, özgün adları ve baytları korunarak
kopyalandı. Manifestte SHA-256, süre, örnekleme hızı, kanal ve olay açıklaması var.
143 dosyanın hash'i ve PCM çözümü test edilir. `reference_sounds/SESLER.md` değiştirme
rehberidir. Bu dosyalar yeni kaynak kodun MIT lisansına dahil değildir.

Bağlanan sesler: top döngüsü, duvar, hareket/sınır, vuruş/servis, gol, kalkan
açılma/döngü/vuruş/kapanma, sessiz top başlama/bitme, kazanma/kaybetme, menü ve
karakter seçimi müziği, karakter adı, maç başlangıcı, gol varyantları, gol/yenilen
gol karakter replikleri, skor ve maç sonucu anonsları. Menü müziği 0,4 katsayıyla
çalınır, maçtan önce durur. HRTF istenen yeni 3B işleme olduğundan özgün stereo
dalga biçiminin birebir kopyası değildir; stereo kayıtlar konumlama için monoya iner.

## Henüz eşdeğer olmayan veya doğrulanmayan noktalar

- Gol replikleri 3'er saniye arayla, skor anonsu ardından çalınır; servis 7,3 saniye
  bekler. Bu sıra decompile edilmiş yerel gol dalına dayanır; bütün maç akışında
  özgün seslerin başlama/bitiş zamanıyla canlı karşılaştırma yapılmadı. Sonuç
  repliğinin gecikmesi ve HRTF seviyeleri yeni uygulamanın seçimleridir.
- Özgün sayı kayıtları 21'de biter. 30 ve üstü hedefler çalışır, skor metni güncellenir;
  eksik sayı dosyaları yerine SAPI ile konuşma eklenmez.
- Özgün açılış/menü geçişlerinin bütün ses sırası ve grafik arayüzü kopyalanmadı.
- Native döngünün gerçek Windows zamanlaması ölçülmedi. Kaynak motor 17 ms sabit
  adım kullanır; talimat başına eşitlik gerçek süre eşitliğini kanıtlamaz.
- Rastgele sayı üretecinin tam dizisi aynı değildir. Olasılık dalları aynı girişlerle doğrulanır.
- Yeni TCP oda protokolü eski EXE protokolünden ayrıdır. İki oyuncu aynı v2 kaynak
  klonunu kullanmalıdır. Eski v1 kaynak istemcileri açık sürüm hatasıyla reddedilir.
- NVDA'nın gerçek ses çıktısı otomatik olarak dinlenip doğrulanmadı. Gerçek Tk
  düğmeleri, durum metinleri, klavye girişleri ve profil kalıcılığı test edildi;
  SAPI ile ek seslendirme yapılmıyor.

## Tekrar çalıştırma

`python -m unittest discover -s tests -v`

Yerel özgün EXE mevcutken: `python -m pip install --target .testdeps unicorn==2.1.4 capstone==5.0.9 pefile`
ardından `python verify_native.py`. Test EXE'yi veya kullanıcı profilini değiştirmez.
Modüller arası test kapsamı: `REGRESSION.md`.
