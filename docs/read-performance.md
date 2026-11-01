# Ekran ve sorgu performansı

1 Kasım 2026 doğrulaması. Önceki arayüz: `1f28323`. Aynı yerel API ve veriyle, 800 ms ek adres listesi gecikmesi altında 100 ms arayla 35 WebSocket bildirimi gönderildi.

| Ölçüm | Önce | Sonra |
| --- | ---: | ---: |
| İlk VLAN açılışındaki API istekleri (oturum dahil) | 22 | 11 |
| 35 bildirim sırasında API istekleri | 666 | 7 |
| İlk IP satırlarının görünmesi | 5.947 ms | 1.380 ms |

Bunlar kontrollü tarayıcı ölçümleridir; gerçek kullanıcı süresi ağ, veri büyüklüğü ve sunucu yüküne bağlıdır. Test, ekranın bildirimlerin sona ermesini beklemediğini ve ilk isteğin tekrar tekrar geçersiz kılınmadığını doğrular.

## Okuma davranışı

- Aynı GET isteği devam ederken ikinci bir tüketici aynı yanıtı paylaşır. Okuma zaman aşımı 30 saniyedir.
- Canlı bildirimler 1,5 saniyelik aralıklarda birleştirilir. Açık sorgu çalışırken en fazla bir sonraki yenileme bekler. Yenileme, yüklenmekte olan ilk yanıtı iptal etmez.
- Navigasyon, arama ve filtre değişikliklerinin sorgu anahtarları ayrıdır. Eski sorgunun geç gelen yanıtı yeni ekranı değiştiremez. Sıfır satırla eski ekranın toplamı birlikte gösterilmez.
- Ekran verisi yalnızca oturum belleğinde, en fazla 100 sorgu ve 30 saniye tutulur; açılışta mevcut veri gösterilir ve tekrar doğrulanır. Başarılı yazma, çıkış ve oturum hatası önbelleği temizler. Önceki yazmadan kalan uçuş hâlindeki okuma önbelleği yeniden dolduramaz.
- Referans listeleri açık sayfa ve formun ihtiyacına göre alınır. Her canlı bildirim cihaz, arayüz, komşuluk, kullanıcı ve erişim profili listelerini yeniden indirmez. Kullanıcı işlemleri ve 30 saniyelik periyodik kontrol referansları yeniler; topoloji ekranındaki referanslar canlı bildirimlere de katılır.
- IP ayrıntısı satırdaki bilgileri hemen gösterir; kaynak gözlemleri ayrı yüklenir. Ayrıntı ve pano yanıtları, kimlik doğrulamasından sonra mevcut 5 saniyelik Redis sürüm önbelleğini kullanır. Yazma/worker bildirimleri sürümü değiştirir; Redis arızası okumayı engellemez.

## Veritabanı

- Pano sayımları ve cihaz türleri iki sorguyla alınır; sayım için kayıt listeleri oluşturulmaz.
- VLAN sıralaması ve sayfalaması veritabanında uygulanır.
- Envanter ve genel konfigürasyon listeleri şifreli konfigürasyon içeriklerini okumaz. Kullanıcı/parola ve entegrasyonların ham kanıt alanları da liste sorgularına taşınmaz.
- Keşif kapsamı erişim profilleri toplu yüklenir. Kabinet cihazları ve model görselleri toplu alınır; 20 cihazlı kabinet testi en fazla beş sorguyla tamamlanır.
- IP ayrıntısının gözlemleri bağlantı seçeneklerinde tekrar sorgulanmaz; yalnızca ilgili VLAN kayıtları okunur.

## Doğrulama

`tests/test_read_performance.py`, sorgu sayılarını, büyük şifreli içeriklerin SQL sonuçlarına alınmamasını, önbellek geçersizleştirmesini ve güncel ayrıntıların görünmesini doğrular. Gerçek ağ erişmez.

`scripts/read_performance_fixture.py` izole SQLite verisiyle çalışır; worker başlatmaz. Derlenmiş arayüzden sonra `scripts/read_performance_browser_check.py` ile test edilir. Bu kontrol bildirim yükünü, geciktirilmiş ayrıntıyı, aramayı, aktif IP filtresini, kayıt sonrası güncelliği ve VLAN dışındaki 28 sayfanın geçişini kapsar. VLAN listesi, adresler ve ayrıntılar 1440 ve 375 pikselde görsel/erişilebilirlik kontrolünden geçer.

Önceki derlemeyi karşılaştırmak için fixture sürecine `NETRIX_BROWSER_DIST` ile derleme dizini, tarayıcı sürecine `NETRIX_MEASURE_ONLY=1` verilebilir. Test adresi yalnızca `127.0.0.1:8215`'tir.
