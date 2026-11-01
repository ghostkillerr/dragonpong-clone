# Doğrudan oyuncu bağlantısı planı

## Hedef ve mevcut durum

Oyuncu geçerli top konumunda bastığında kendi bilgisayarı teması hemen duyurur.
Bu ilk adım `strike_ref_v1` ile gönderilen aynı görünümü kullanır; sunucu hâlâ
vuruş, top, skor ve maç sonucunu kesinleştirir. Karşı tarafın topunu ve skoru
değiştiren doğrudan oyuncu mesajları henüz açık değildir.

## Neden doğrudan yol koşullu olmalı?

Oyuncu A → sunucu → oyuncu B yolu yerine A → B yolu yalnızca iki ağ arasında
doğrudan UDP bağlantısı kurulursa ve bu yol gerçekten daha hızlıysa avantajlıdır.
NAT, güvenlik duvarı veya paket kaybı bunu engelleyebilir. Aynı bilgisayardaki
iki istemci testi gerçek internet yolunu kanıtlamaz. Sunucu bağlantısı, oda
kurma ve geri dönüş yolu olarak kalmalıdır.

## Uygulama sırası

1. Oda içinde sürümlü ve yalnızca iki oyuncuya açık bağlantı sinyalleri
   değiş tokuş edilir. Sunucu IP ve ICE adaylarını depolamaz veya başka odaya
   iletmez. Bağlantı kurulamazsa mevcut `strike_ref_v1` maçı sürer.
2. Her iki oyuncu aynı anda doğrudan ve sunucu yolunun RTT, p50, p95, p99,
   dalgalanma ve kaybını ölçer. P95 avantajı kararlı olmayan doğrudan yol
   otomatik kullanılmaz. Ölçüm sonucu F6 ile erişilebilir olur.
3. Sadece aynı uçuşa ve gösterilen kareye bağlı, sıralı vuruş bildirimi
   doğrudan gönderilir. Yinelenen, eski veya farklı uçuşa ait bildirimler
   atılır; onay ve yeniden gönderim vardır. Karşı tarafın erken ses bildirimi
   sunucu durumuyla uzlaştırılır. Bu aşamada fizik ve skor sunucuda kalır.
4. Sunucuyu yalnızca oda/sinyal/geri dönüş katmanına indirmek için iki
   istemcinin aynı vuruş sonrası hız, yön, güç ve skor sonucunu ürettiği ayrı
   bir sürümlü maç protokolü gerekir. Kaynak motorun `strike`, `step` ve
   rastgelelik sırası korunur. Bu aşama, iki farklı ağda uzun ralli ve
   kesinti testleri bitmeden varsayılan oyun olmaz.

## Kabul ölçütleri

- Her iki oyuncu yönünde duvar sekmesi, kalkan, sessiz top, gol bekleme,
  servis ve maç sonu davranışı mevcut motorla eşleşir.
- Geciken, kaybolan, yinelenen ve yanlış sıradaki paketler skoru iki tarafta
  ayırmaz; bağlantı koparsa maç açıkça durur veya sunucu yoluna döner.
- Doğrudan yol p95 ölçümü sunucu yolundan iyi değilse etkinleştirilmez.
- NVDA ve klavye kullanımı sürer; F6 bağlantı yolunu ve bozulmayı duyurur.
- Farklı internet bağlantılarındaki iki gerçek bilgisayarda iki yönlü ölçüm
  ve uzun maç yapılır. Yerel simülasyon yalnızca geliştirme kanıtıdır.

## Dağıtım

Önce sunucu sinyal/geri dönüş desteği, sonra istemci sürümü yayımlanır.
Eski istemciler `strike_ref_v1` yolunda kalır. Doğrudan maç protokolü ayrıca
özellik anlaşmasıyla açılır; bu plan tek başına canlı sunucu değişikliği değildir.
