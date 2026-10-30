# Cihaz ayrıntısında üst akış bağlantıları

Cihaz ayrıntısındaki **Üst akış bağlantıları** bölümünde yerel port, karşı cihazın adı/yönetim IP adresi ve karşı port gösterilir. Cihaz adına basılması aynı pencerede o cihazı açar. Arayüz seçimi yapılmamış olsa bile bağlantı kayıtları görüntülenir.

`GET /api/v1/devices/{id}/connections` oturum açmış okuyuculara da açıktır. Envanterdeki güncel bağlantıları okur; ağ sorgusu veya görev oluşturmaz. Cihazın hem kendi hem de karşı uçtan alınmış gözlemleri değerlendirilir. Ters gözlemde portlar yer değiştirir. İki portu da bilinen aynı uçlar birleşir, protokoller birlikte gösterilir; paralel portlar ayrı kalır. Portu bilinmeyen kayıtlar tahminle birleştirilmez. Arşivlenmiş, başka VRF'deki veya kendine bağlı cihazlar ve artık güncel olmayan bağlantı kayıtları gösterilmez.

## Yön ve kanıt

LLDP/CDP komşuluk bilgisi trafik yönü veya STP'nin iletim durumunu kanıtlamaz. Bu nedenle yön **aday** olarak etiketlenir. Firewall başlangıç seviyesi 0, Backbone/Controller türü veya adında `-BB-` bulunan cihazlar seviye 1 kabul edilir; diğer cihazlar bu başlangıçlara bağlantı uzaklığıyla sıralanır. Özel cihaz türlerinin görünen adı da değerlendirilir. Daha düşük seviyedeki komşular üst akış adayıdır; eşit/alt seviyeler diğer komşular altında kalır. Başlangıcı bulunmayan bağlantılı bileşenlere alfabetik veya rastgele bir kök atanmaz; yön belirsiz gösterilir. Birden fazla üst bağlantı ve döngüler korunur.

Bağlantı kaynağı, kayıtlı eşleşme güveni ve son gözlem zamanı ayrıca gösterilir. Ad eşleşmesine dayanan keşif adayları doğrulanmış ilişki diye sunulmaz. Kullanıcının doğruladığı manuel bağlantılarda dahi bilinmeyen fiziksel portlar boş kalır. Son gözlem zamanı bir canlı erişim testi değildir; mevcut `is_current` durumu korunur, bu okuma sırasında yeni bir TTL politikası uygulanmaz.

Bölüm uygulamanın mevcut yenileme sinyaliyle güncellenir. Yükleme, boş liste, hata/yeniden deneme durumları ayrı gösterilir. Yenileme başarısızsa önceki veri hata bilgisiyle birlikte kalır. Yeni cihaz açıldığında önceki cihazın sonuçları taşınmaz.

## Doğrulama

- `tests/test_device_connections.py`: ters uç, çift protokol, paralel port, özel Backbone türü, çoklu üst bağlantı/döngü, belirsiz yön/port, arşiv/VRF/güncellik ve okuyucu yetkisi.
- `scripts/device_connections_fixture.py` + `scripts/device_connections_browser_check.py`: yerel gerçek API, 1440/375 px açık/koyu temada hizalama ve taşma, axe erişilebilirlik kontrolü, klavyeyle karşı cihaza geçiş, hata/yeniden deneme ve boş durum. Gerçek cihazlara bağlanmaz.
- Şema ve cihaz kayıtlarında değişiklik yoktur.
