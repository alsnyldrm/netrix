# Lumelle gezinme hareketleri

13 Kasım 2026'da canlı [Lumelle Customers / People](https://demo.codeandchill.store/lumelle/#/customers/people)
sayfası Chromium'da açılarak menü ve sayfa geçişleri incelendi. Canlı uygulamanın
`index-D6Q9wC1k.js` ve `kit-BLRx7j0_.js` dosyalarındaki hareket parametreleri,
çalışan GSAP zaman çizelgesindeki değerlerle karşılaştırıldı. Yerel template
klasörü değiştirilmedi.

| Hareket | Süre | Başlangıç / sıra | Eğri |
| --- | --- | --- | --- |
| Eski sayfanın çıkışı | 180 ms | 16 px yatay | power2.in |
| Başlık ve sekmelerin çıkışı | 144 ms | 6 px yukarı | power1.in |
| Yeni sayfanın gelişi | 700 ms | 26 px yatay, yönlü | expo.out |
| Başlık harfleri | 850 ms | %115 aşağı, 6° dönüş, harf başına 22 ms | power4.out |
| Kartlar | 800 ms | 26 px aşağı, .985 ölçek, sıra başına 60 ms | expo.out |
| İlk görünür tablo satırları | 550 ms | 12 px aşağı, 250 ms bekleme, 25 ms sıra | power3.out |
| Alt menü açılışı | 450 ms | Üstten aşağı kırpma | power3.out |
| Alt menü yazıları | 400 ms | 8 px soldan, 80 ms bekleme, 40 ms sıra | power3.out |
| Seçili menü zemini | 360 / 550 ms | Öndeki ve arkadaki kenar ayrı ilerler | power3.out / power3.inOut |
| Sidebar daralma | 600 ms | 60 ms bekleme, ardından ikonlar yerleşir | power4.inOut |
| Sidebar genişleme | 620 ms | Yazılar 160 ms sonra, 12 ms sıra | expo.out |
| Sidebar ikon yerleşimi | 550 ms | 12 ms sıra | expo.out |
| İlk sidebar açılışı | 800 ms | 40 px soldan | expo.out |
| İlk menü yazıları | 500 ms | 120 ms bekleme, 22 ms sıra | power3.out |

`frontend/src/lumelle-motion.tsx` bu hareketleri tarayıcının Web Animations API'si
ile uygular. Eğriler 101 örnekli CSS `linear()` ile temsil edilir. Ek çalışma
zamanı bağımlılığı veya template kaynak kodu kopyası eklenmedi.

Eski uygulama sayfanın tek ekran görüntüsünü View Transition ile taşıyordu.
Bu, metin ve kartların bağımsız hareketlerini göstermiyordu. Yeni gezinme,
180 ms çıkıştan sonra React sayfasını bir kez değiştirir. Başlık, kartlar ve
menü ayrı hareket eder. Tema değiştirme kendi View Transition davranışını korur.

Tablo verisi gecikirse ilk görünür satır grubu bir kez canlandırılır. Daha sonraki
filtreleme, yenileme ve canlı veri güncellemeleri giriş animasyonunu tekrarlamaz.
Art arda seçimlerde son istek geçerlidir. İşletim sistemi veya hesap ayarındaki
azaltılmış hareket seçeneği etkinse hareketler atlanır; sürmekte olanlar bitirilir.

## Doğrulama

İzole `scripts.user_workspace_fixture` ile `scripts/lumelle_navigation_browser_check.py`
çalıştırılır. Gerçek ağ cihazlarına bağlanmaz. `NETRIX_BROWSER_URL`,
`NETRIX_CHROMIUM` ve isteğe bağlı `NETRIX_MOTION_ARTIFACTS` ortam değişkenlerini alır.

Kontroller süreleri, harf/satır sırasını, tek sayfa girişini, veri yenilemeyi,
hızlı gezinmeyi, geri/ileri geçmişini, sidebar daralıp genişlerken pencere
boyutunun değişmesini, masaüstü/mobil/yatay görünümü ve iki azaltılmış hareket
ayarını kapsar. View Transition API'si bulunmadığında da aynı gezinme çalışır.
`lumelle_template_browser_check.py` üst menü, profil, mobil çekmece ve tema
geçişlerini ayrıca doğrular.
