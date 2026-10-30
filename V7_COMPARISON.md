# Release v7 / kaynak klon karşılaştırması — 29 Ekim 2026

Kaynaklar: `release_v7/OYNA_TR_v7.md`, Türkçe menüler, `launcher/in_game.py`,
`launcher/offline_bot.py`, `analysis/patch_v7.py`, özgün tuş işleme analiz kaydı
`analysis/ghidra-function-0040293e.json`. Bu inceleme kaynak/varlık ve otomatik
davranış karşılaştırmasıdır; bütün ekran okuyucu/donanım kombinasyonlarının canlı testi değildir.

| Özellik | Kaynak klondaki sonuç |
|---|---|
| Oyuncu adı, tekrar açılışta hatırlama | Var; isim ve doğrulanmış ayarlar atomik kaydedilir, Başla beklenmez |
| Bekleyen oda yoksa otomatik oda açma | Var |
| Oyuncu adıyla oda listesi / yeni oda | Var; listeye Enter ile seçilen yeni oda satırı eklendi |
| İki ayrı oda, dört oyuncu | Mevcut sunucu testlerinde var |
| Karakterlerden sonra sadece oyuncu 1'in ayarları | Var; izleyiciye oyuncu ayar ekranı açılması düzeltildi |
| 30 ve üstü hedef skor, kalkan ve rastgele sessiz top | Var, pozitif 32 bit skor; açık/kapalı etiketleri ve sağ/sol oklar |
| Ad/ayarların anında kalıcılığı | Eksik kısımlar düzeltildi; geçersiz profil değerleri reddedilir |
| Oyun içinde menü ve klavye ile gezinme | Oklar/Enter, liste Enter ve tüm ekranlarda Escape eklendi; Tab da çalışır |
| İzleyici odası ve isimle ses bakışı | Var; iki yönde döngüsel seçim, bakış değiştirilince raket konumu güncellenir |
| Devam eden/bitmiş maça sonradan izleyici girişi | Anlık maç durumu gönderilerek beklemede kalma giderildi |
| Çevrimdışı Kolay/Orta/Zor/Ultra | Var, Ultra hareket sınırı 63 ms; aynı güç kazanma motoru |
| Klavye, sol fare vuruşu, tekerlek hareketi | Fare eklendi: her üç tekerlek adımı bir saha adımı |
| Kontrolcü | SDL joystick: ilk düğmeyle vuruş, çubuk/yön pediyle hareket; arka planda giriş uygulanmaz |
| Müzik azaltma ve PageUp/PageDown | Başlangıç katsayısı 0,4; maçta ses değiştirme eklendi |
| Çık ve durumların NVDA'ya bildirilmesi | Gerçek düğmeler, odak/ayar metniyle pencere başlığı ve isim değişimi Windows olayı; SAPI yok |
| Karakter adları | V7'deki dört isim eklendi; mevcut beşinci kaynak karakter korunur |

## Korunan farklar ve doğrulama sınırı

Kaynak klon kendi 8870 protokolünü kullanır; v7 istemcisiyle aynı odada çalışmaz.
V7 izleyicisi oyuncudan PCM alır; kaynak klon aynı olayları seçilen perspektiften
HRTF ile üretir. HRTF önceki kullanıcı isteğidir; ses baytlarının eşdeğerliği iddia edilmez.
Orijinal sayı sesleri 21'de biter, daha büyük skorlar metinle sunulur. Ses sırası ve
zamanlamadaki diğer sınırlar PARITY.md'de açık tutulur.

Kontrolcü eşlemesi sahte SDL aygıtıyla, arayüz gerçek Tk ile, odalar geçici yerel
TCP bağlantılarıyla test edilir. Fiziksel kontrolcü, NVDA'nın duyulan konuşması ve
tüm eski dil menülerinin çevirisi bu Türkçe sürümün doğrulanmış kapsamı değildir.

GitHub üzerinde güncelleme yapılmadı. Yerel paket v2.2 olarak hazırlanır.
