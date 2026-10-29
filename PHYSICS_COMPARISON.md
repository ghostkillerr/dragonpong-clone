# Fazla yan duvar sekmesi — 29 Ekim 2026

Kullanıcının `top/dragonpong/DragonPong.exe` dosyası, önceki referansla aynı SHA-256'ya
sahip: `937ac8bb55b8265e9359e3db479d9334e5314dab981507fbc06313576fac1341`.
REA/Ghidra ile hareket (0x402541), vuruş (0x404bfa), ağ mesajı işleme (0x403026)
ve bekleme (0x402253) tekrar incelendi. İnceleme dosyaları çalışma alanının
`analysis/physics-20261029-*.json` dosyalarında; özgün EXE depoya eklenmez.

## Bulgu ve düzeltme

Hız artışı formülü aynıydı. Eksik olan, vuruşun karşı tarafa aktarılmasındaki
konum sıfırlamasıydı. Özgün BE alıcı dalı (0x403cfc–0x403d51):

- Topun yan konumunu vuran oyuncunun raket konumuna koyar.
- Alıcıya göre derinliği 20'ye koyar ve topu yaklaşan olarak işaretler.
- Yön, önceki vuruş anındaki top/raket farkından hesaplanmış halde kalır.

v2 klonu kesirli temas konumunu koruyup topu oradan geri çeviriyordu. Bu, saha
boyunca kat edilen mesafeyi kısaltıyor, ortalanmış dönüşlerin yeniden yan yöne
sapmasına ve uzun rallilerde daha fazla yan duvar sekmesine yol açıyordu.
Ortak sunucu fiziği artık alıcı tarafın özgün davranışını kullanır: vuruştan sonra
top, vuran raketin konumundan ve uç çizgisinden yeni uçuşa başlar.

İkinci fark float32 derinlik aritmetiğiydi: bir yönde dünya koordinatına ekleme,
diğerinde çıkarma yapmak bazı rallilerde vuruşu bir adım kaydırıyordu. İki yönde de
alıcının kalan derinliğinden çıkarma yapılarak aynı yuvarlama uygulanır.

Hız artışı, yan yön seçimi, oyuncunun vuruş mesafesi, botun karar kuralları ve
63 ms Ultra hareket sınırı korunur. Erken vuruş artık sonraki uçuşu kısaltmaz.

## Ölçüm

`verify_rallies.py`, özgün hareket ve vuruş talimatlarına ek olarak BE alıcı
dalının makine kodunu da Unicorn'da çalıştırır. Aynı rastgele hız artışlarıyla,
topa kusursuz yetişen ve derinlik 5,5 altında vuran test oyuncuları kullanılır.
Bunlar kontrollü simülasyonlardır; insan performansı veya gerçek ağ gecikmesi ölçümü değildir.

| 60 saniyelik senaryo/tohum | Özgün duvar sekmesi | v2 klon | Düzeltilen klon |
|---|---:|---:|---:|
| 3 | 25 | 218 | 25 |
| 17 | 18 | 926 | 18 |
| 41 | 4 | 876 | 4 |

Üç senaryonun vuruş sayıları da düzeltmeden sonra eşittir (545, 569, 469).
400 ayrı uçuşta toplam 25.687 adımda yan konum, alıcı derinliği, yan yön ve
duvar olayları özgün talimatlarla tam eşleşir. Eski 7.108 tek-adım/fonksiyon
kontrolü de geçer; hareket karşılaştırması iki yönde alıcı koordinatını kullanır.
39 modül/arayüz/ağ testi başarılıdır.

Eski 7.108 kontrolün tek başına bu hatayı bulamamasının nedeni, BE konum
sıfırlamasını ve birbirine bağlı uzun rallileri kapsamamasıydı.

Komutlar: `python verify_rallies.py`, `python verify_native.py`,
`python -m unittest discover -s tests -v`. `--baseline` seçeneği karşılaştırma
için Git'teki `cc7764a` sürümünü yükler. JSON sonuçları `rally_baseline.json`
ve `rally_verification.json` dosyalarındadır.

Sınır: doğrulama gerçek ağ ayrıştırmasını, paket hızlarının metne çevrilip geri
okunmasını, Windows zamanlayıcısını ve ses aygıtı gecikmesini kapsamaz.
Rastgele üretim sınırına aynı değerler verilir; üreteç dizisinin aynılığı iddia edilmez.
