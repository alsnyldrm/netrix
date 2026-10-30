# Üst bağlantılar, gerçek portlar ve TRK üyeleri

Cihaz ayrıntısında yalnızca **üst akış** bağlantıları gösterilir. Alt bağlantılar, aynı seviyedeki komşular ve yönü belirlenemeyen kayıtlar bu bölüme eklenmez. Bağlantı haritası tüm güncel komşulukları korur; **Bağlantı ayrıntısı** seçicisi iki cihazın fiziksel portlarını, her uçta gözlemlenen TRK adını/türünü ve protokolleri gösterir.

## Port çözümleme ve toplama

Ortak çözümleyici CDP `Device Port` alanını, LLDP `local` alt türündeki PortId için `PortDescr` alanını kullanır. Örneğin PortId `260`, PortDescr `I4` olduğunda görünen port **I4** olur. PortId ayrı kanıtta saklanır; açıklama da yoksa yerel kimlik fiziksel port adı diye sunulmaz. CDP/LLDP kayıtları aynı yerel port ve aynı chassis kimliği veya yönetim adresi kanıtıyla birleşir. Sadece benzer adla veya port numarasıyla birleştirilmez. Yönetim IP eşleşmesi aynı VRF'deki tek etkin cihazı aday olarak bağlar; profil sırları ve ham terminal çıktıları saklanmaz.

ArubaOS-Switch **54xx ve 2900** adaptörlerinde `Bilgileri cihazdan al` ve izleme görevleri, atanmış SSH profiliyle şu salt okunur komutları çalıştırır:

- `show cdp neighbors detail`: tüm CDP komşularının ayrıntıları.
- `show lldp info remote-device`: port listesini bulmak için özet; ardından doğrulanmış port listeleriyle `show lldp info remote-device <port-list>`: LLDP detail.
- `show trunks`: yerel fiziksel üye → TRK/LACP grubu.
- `show spanning-tree`: CST kök portu.

Tek PTY oturumunda yalnızca oturumluk `no page` uygulanır. SSH için kayıtlı anahtara güven tercihi geçerlidir. Toplam 60 saniye, komut başına 1 MiB ve en fazla 512 port sınırı vardır. API ağ okuması yapmaz; çalışma worker'dadır. Yetkili kapsam ve bağlantı profilleri işlem öncesi/sonrası doğrulanır. Desteklenmeyen veya başarısız detail komutu port/TRK bilgisi uydurmaz; mevcut SNMP gözlemi yine kaydedilir ve başarısızlık yalnızca hata sınıfıyla raporlanır. Başarısız veya kısmi LLDP okuması global komşuluk tablosunu boş saydırmaz.

Diğer adaptörler SNMP'nin aynı ortak port çözümlemesini kullanır; bu sürüm diğer CLI ailelerine AOS-S komutlarını göndermez. TRK bilgisi yalnızca gözlemlenmişse gösterilir.

## Üst akış ve gruplama

STP'de açıkça belirtilmiş kök portu varsa yalnızca o port veya o TRK'nin fiziksel üyeleri üst bağlantı sayılır. **STP kök portu** olarak etiketlenir; bu bilgi bütün VLAN'ların veya L3 trafiğin yönünü kanıtlamaz. Cihazın kendisinin STP kökü olması, firewall'a üst bağlantısı olmadığı anlamına gelmez.

STP kök portu bilinmiyorsa yön topolojiden çıkarılan **aday**dır: bağlı bileşende firewall'a uzaklık kullanılır. Böylece bir Backbone'un arkasındaki ikinci Backbone aynı seviyeye sabitlenmez. Firewall'a bağlı olmayan bileşenlerde Backbone/Controller türü veya `-BB-` adı başlangıç sağlar; bunlar da yoksa yön belirsiz kalır. API projeksiyonu tüm yönleri taşısa da cihaz ayrıntısı yalnızca upstream kartlarını gösterir.

TRK'nin aynı karşı cihaza giden üyeleri tek kartta toplanır. Her üyenin iki fiziksel portu ayrı satırda kalır; karşı uçtaki TRK ancak o uçtan alınmış kanıtla gösterilir. Ters gözlemler çevrilir, aynı fiziksel uçlar birleşir. Arşivlenmiş, başka VRF'deki, kendine bağlı veya güncel olmayan kayıtlar dışlanır. Manuel bağlantılar bilinmeyen portlara sahip olabilir; port uydurulmaz.

## Eski kayıtlar ve doğrulama

`python scripts/repair_neighbor_ports.py` saklanmış kanıttan yapılacak düzeltmeleri transaction rollback ile sayar; `--apply` uygular. Yeni ağ sorgusu yapmaz, `last_seen_at` zamanını yenilemez, manuel bağlantıları değiştirmez. Düzeltilmiş güncel kayıt zaten varsa eski kopya tarihçe korunarak güncellikten çıkarılır. API de eski kaydı aynı çözümleyiciyle gösterir.

- `tests/test_neighbor_detail.py`: gerçek çıktının alanlarını temsil eden sahte transkriptler; PortId/açıklama, chassis ayrımı, güvenli komut listesi, TRK, STP, worker entegrasyonu ve IP eşleştirme.
- `tests/test_device_connections.py`: ters uçlar, fiziksel üyeler, gruplama, kök portu ve Backbone arkasındaki Backbone yönü.
- `scripts/neighbor_detail_check.py`: yalnızca geçici `netrix_test` MariaDB'sinde JSON, unique anahtar, mükerrer düzeltme, idempotence ve gözlem zamanı doğrulaması.
- `scripts/device_connections_browser_check.py`: gerçek yerel API ile 1440/375/812 px, açık/koyu temalarda üst bağlantı ve harita, klavye kullanımı, hata/boş durum, taşma/hizalama ve axe.

## Resmî kaynaklar

- [AOS-S CDP detail alanları](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MRG/WB/content/common%20files/sho-cdp-nei-det.htm)
- [AOS-S LLDP PortId ve PortDescr alanları](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MCG/WC/content/common%20files/vie-lld-por-con.htm)
- [AOS-S show trunks grubu ve türü](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/sho-tru.htm)
- [AOS-S STP kök portu gösterimi](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/ATMG/WC/content/common%20files/vie-sta-spe-vla.htm)
