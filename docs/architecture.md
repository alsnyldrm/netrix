# NETRIX çalışan mimarisi

NETRIX; FastAPI, SQLAlchemy/Alembic, harici MariaDB ve Redis kullanan modüler monolittir. Üç modül tek `devices`/`interfaces` envanterini paylaşır. Hazır ağ yönetimi ürünü kullanılmaz.

## Süreçler

Dağıtım tek servisli `netrix` Docker Compose stack'tir. `netrix-app` servisi yalnızca `netrix` container'ını oluşturur. Aşağıdaki adlar container değil, aynı container içinde Supervisor'ın yönettiği süreç adlarıdır. Harici MariaDB ve mevcut host Nginx bu uygulama stack'inin dışındadır. Container UID/GID 10001 ile çalışır; Redis yalnızca container loopback'ini dinler, `/data` kalıcı volume'dadır.

- `netrix-api`: React arayüzünü ve `/api/v1` API'lerini sunar. Ağ sorgusu yürütmez.
- `netrix-worker`: MariaDB'den `FOR UPDATE SKIP LOCKED` ile iş alır. SNMPv3, SSH ve HTTPS REST bağlantıları bu süreçtedir.
- `netrix-scheduler`: etkin politikaları 15 saniyede bir değerlendirir; işler aynı kuyruk servisinden geçer.
- `netrix-redis`: WebSocket güncelleme sinyalleri, kimlik doğrulama hız sınırı ve süreç heartbeat'leri. İş kaydının asıl kaynağı MariaDB'dir; Redis kesintisi kalıcı işleri silmez.
Başlangıç komutu önce Alembic migration'ı uygular; başarısızlıkta API/Redis/worker/zamanlayıcı başlamadan container hata koduyla çıkar. Başarıdan sonra PID 1 Supervisor olur. Süreç arızasında ilgili süreç yeniden başlatılır; başlangıçta artan gecikmeyle beş tekrar sınırı vardır. Sağlık kontrolü dört sürecin RUNNING durumunu, DB/Redis readiness'ini ve worker/zamanlayıcının güncel heartbeat'lerini gerektirir. Kalıcı başlangıç hatasında container unhealthy olur; işletmeci logları inceleyip düzeltmelidir (Docker standalone yalnızca unhealthy olmayı otomatik restart sebebi saymaz).

SIGTERM'de önce zamanlayıcı, sonra worker, API ve son olarak Redis kapanır. Worker'a 30 saniye, tüm container'a 60 saniye kapanma süresi verilir. Yedekleme/geri yükleme istemcisi de bu container içinde ek bir süreç olarak çalışır; ek yardımcı container oluşturmaz.

`backend/netrix/identity`, `discovery`, `configuration`, `monitoring`, `alerting` protokol ve iş kurallarının sınırlarını oluşturur. Merkezi kaynak işlemleri `services.py`, modeller `models.py` içindedir. `inventory` ve `ipam` aynı servis katmanındaki transaction doğrulamalarını kullanır.

## MariaDB uyarlaması

Proje sahibinin 29 Ekim 2026 kararı PostgreSQL/TimescaleDB hedefinin yerini alır. Harici MariaDB'de InnoDB, UUID için `VARCHAR(36)`, normalize IP/CIDR için metin, ek kanıt için JSON, unsigned 64 bit sayaçlar için `DECIMAL(20,0)` kullanılır. `DATETIME(6)` değerleri UTC'ye normalize edilir, okunurken UTC tzinfo eklenir. API ISO 8601 zaman dilimli değer döndürür; arayüz tarayıcının yerel saatinde gösterir.

IPAM'de aynı VRF içindeki yazmalar VRF satırı üzerinde kilitlenir ve `lock_version` artırılır. Böylece farklı Galera düğümlerindeki eşzamanlı yazmalar da sertifikasyon aşamasında çakışır; yalnızca düğüme yerel `FOR UPDATE` kilidine güvenilmez. Geçici DB hatası API'de 503 döner; worker sınırlı tekrar uygular; VRF+IP tekilliği ayrıca DB kısıtıdır. CIDR/üyelik, site/VRF uyumu, IPv6 ve /31-/32 kuralları servis katmanında doğrulanır. İç içe prefix'lere izin verilir. Kullanım yüzdesi o prefix'e doğrudan atanmış, deprecated olmayan IP kayıtlarını sayar; alt prefix kayıtları üst prefix'e ikinci kez sayılmaz. Eski `docs/data-model.md`, daha ayrıntılı hedef modelidir; uygulanmış tablolar için Alembic migration ve `models.py` esastır.

Ham trafik varsayılan 30 gün tutulur. Zaman ve arayüz/zaman indeksleri vardır. Bu sürüm TimescaleDB hypertable, continuous aggregate veya otomatik saatlik özet kullanmaz.

## Güvenlik

İlk yönetici ancak tek kullanımlık kurulum anahtarıyla oluşturulur; DB'deki singleton satır kilidi aynı anda ikinci kurulum yapılmasını engeller. Parolalar Argon2id özetidir. Oturum token'larının yalnızca SHA-256 özeti DB'dedir. Cookie HttpOnly/Secure/SameSite Strict; yazma isteklerinde özel başlık ve Origin kontrolü vardır. Admin/operator/viewer API ve WebSocket'te kontrol edilir. Parola değişimi bütün oturumları iptal eder.

Credential ve tam konfigürasyonlar Fernet ile şifrelenir. Anahtar DB dışında `.env` dosyasındadır. API credential sırlarını döndürmez; konfigürasyon görüntüleme ve diff hassas satırları maskeler. JSON doğrulama hataları girilen sırları yansıtmaz; SQL loglarında parametreler gizlenir. Secret dosyaları ve anahtarlar Git dışında tutulur.

SSH host anahtarı varsayılan olarak `known_hosts` ile doğrulanır. `devices.ssh_trust_host_key` yalnızca açık kullanıcı seçimiyle etkinleştirilirse o cihaza ait SSH test/kimlik/yedek bağlantıları sunulan anahtarı kabul eder (`known_hosts=None`); anahtar sabitleme yapılmaz. Kullanıcı doğrulaması, timeout ve yetkili kapsam denetimi devam eder. Alembic `20261030_04` mevcut cihazlara kapalı varsayılan ekler. REST HTTPS sertifika doğrulaması açıktır; redirect takip edilmez. Üretici komutları sabit yetenek/adaptör tablosundadır; kullanıcıdan serbest komut alınmaz.

## Görev ve keşif davranışı

Aynı tür/hedef için en fazla bir etkin iş vardır. Tamamlanan işin tekrar tesliminde observation/snapshot/sample tekillikleri çift kayıt üretmez. 90 saniye heartbeat almayan işler yeniden kuyruğa alınır; en fazla üç deneme yapılır. Geçici hatalarda 15/30 saniye geri çekilme vardır. API iptal bayrağı yazar; worker en geç kontrol aralığında (5 saniye ve sürmekte olan kısa DB işlemi) ağ coroutine'lerini iptal eder. SIGTERM mevcut işi açık terminal duruma geçirir. Bir worker aynı anda tek mantıksal iş; keşif içinde en fazla dört hedef yürütür.

Kapsamlar varsayılan manuel çalışır; zamanlama açıkça etkinleştirilir. Bütün cihaz işlemleri etkin yetkili kapsamı yeniden kontrol eder. IPv6 ve 1024 adresten büyük ağlar açık hedef listesi gerektirir. Hariç tutmalar uygulanır. ICMP zorunlu değildir; SNMPv3 doğrudan sorgulanır. Başarısız hedefler kısmi/başarısız sonuçta sayılır; cevap vermemek cihazı silmez.

Yönetilen cihaz adı, gözlemlenen hostname tarafından değiştirilmez. ARP/NDP/FDB/VLAN port adayları kanıt ve güven düzeyiyle saklanır; LLDP/CDP isim eşleşmesi kesin fiziksel bağlantı sayılmaz. Birden fazla port adayı ve uplink kanıtı eşleşmeyi belirsiz bırakır. Topoloji bağlantıları son gözlem zamanını korur; kayıp komşu tek başarısız sorguda silinmez.

### Otomatik cihaz bilgileri

Cihaz oluşturulunca veya bağlantı/üretici/model/tür bilgileri değişince, aktif cihaz yetkili kapsam içindeyse ve erişim profili varsa aynı transaction içinde `identify` işi kuyruğa eklenir. Kaydetme işlemi ağ yanıtını beklemez. Kapsam/profil yoksa manuel kayıt saklanır ve sorgunun neden başlatılmadığı yanıtta bildirilir. Dağıtım mevcut cihazlar için kendiliğinden sorgu başlatmaz. Ayrıntılardaki **Bilgileri cihazdan al**, `POST /api/v1/jobs` üzerinden `kind: identify` ile yeniden sorgu başlatır.

Önce SNMPv3 profili, eksik alan varsa SSH/API profili denenir. Her alan bağımsız uygulanır: cihazdan belirlenen üretici, model ve tür manuel değerlerin üzerine yazılır; boş, bilinmeyen, desteklenmeyen veya belirsiz sonuçlar mevcut değerleri silmez. Tür, cihazın açık tür alanından veya tanınan model ailesinden/sistem açıklamasından belirlenir; bağlantı adaptörünü seçmek tek başına üretici veya tür kanıtı değildir. Yeni cihazın başlangıç türü `other` olur. Gözlem `identity`, alan başına protokol kaynağı ve okuma durumu içerir; değişen değerler olay geçmişine kaydedilir. Salt kimlik sorgusu arayüzleri silmez veya port durumlarını değiştirmez. SNMP keşif/izleme gözlemleri de aynı alan güncelleme hizmetini kullanır.

- SNMPv3: [ENTITY-MIB](https://www.rfc-editor.org/rfc/rfc4133.html) chassis(3) girdilerinin üretici/model alanları, sysObjectID ve sysDescr kullanılır. Modül/SFP modeli cihaz modeli sayılmaz; farklı şasi modelleri belirsiz bırakılır.
- SSH: IOS için [show version](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/command_reference/b_1718_9300_cr/system_management_commands.html), Junos için [show version](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/show-version.html), FortiOS için [get system status](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/173707/firmware-maturity-levels) ve Linux için [DMI sysfs alanları](https://github.com/torvalds/linux/blob/master/drivers/firmware/dmi-id.c) okunur. Cihazın kayıtlı SSH anahtar güven tercihi uygulanır; serbest komut alınmaz. Gerçek cihazların CLI exec desteği ve çıktı biçimleri ayrıca doğrulanmalıdır.
- REST: ayrı `identity_path` alanı (varsayılan `/api/system`) kullanılır. Evrensel bir üretici endpoint'i değildir; cihazın gerçek JSON bilgi yoluna ayarlanmalıdır. Kabul edilen alanlar `vendor`/`manufacturer`, `model`/`model_name`, `kind`/`device_type`/`type`; isteğe bağlı `results`, `data` veya `system` nesnesi içindedir. TLS doğrulaması açık, yönlendirme kapalı ve yanıt sınırı 256 KiB'dir. Ham API/CLI çıktısı veya token bu gözlemde saklanmaz.

Kimlik işi mevcut iptal, heartbeat, sınırlı yeniden deneme ve hedef/tür başına tek etkin iş kurallarını kullanır. Ağ isteği sırasında bağlantı hedefi veya erişim profili değişmişse eski yanıt uygulanmaz; güncel bilgilerle yeniden denenir. Üç alan alınmışsa başarılı, bir kısmı alınmışsa kısmi, hiçbiri belirlenememişse başarısız sonuç gösterilir.

### Cihaz bağlantı testleri

Envanter satırının sonundaki **Test**, cihazın güncel kayıtlı profillerini `GET /api/v1/devices/{id}/connection-tests` ile yükler. SNMPv3/SSH/API seçenekleri yalnızca atanmış ve adaptörle uyumlu profil varsa etkinleşir; sırlar tarayıcıya dönmez. Pencereyi açmak ağ isteği başlatmaz. `POST /api/v1/devices/{id}/connection-tests`, `protocol: snmpv3|ssh|rest` ile seçilen protokole ait `test_snmp`, `test_ssh` veya `test_api` işini oluşturur. Admin/operator yetkisi, aktif cihaz ve yetkili kapsam API'de ve worker'da kontrol edilir; diğer protokollere otomatik geçiş yapılmaz.

SNMPv3 testi authPriv ile sistem OID'lerini GET üzerinden okur ve sysUpTime'ın okunabilir olduğunu doğrular; tablo taraması yapmaz. SSH testi cihazın kayıtlı anahtar güven tercihiyle oturum açar; konfigürasyon komutu çalıştırmaz. API testi kayıtlı `identity_path` yoluna token ile HTTPS GET yapar; TLS doğrulaması açıktır, yönlendirme izlenmez, 2xx ve geçerli JSON nesne/liste yanıtı gerekir, üst sınır 256 KiB'dir. API başarı mesajı bu HTTP/JSON kontrolünü bildirir; endpoint'in token'ı nasıl yetkilendirdiğine ilişkin ek bir varsayım yapmaz.

Her testin yürütme süresi en fazla 30 saniyedir; SNMP taşıması 2 saniye timeout ve bir protokol tekrarı kullanır. Etkileşimli testin bağlantı hatası terminal başarısız sonuçtur; otomatik 15/30 saniyelik iş tekrarı yapılmaz. Kuyrukta/çalışıyor/başarılı/başarısız/iptal durumları pencerede izlenir ve iptal istenebilir. Aynı cihaz/protokol için bir etkin iş vardır. Sonuç; protokol, hedef, port, UTC kontrol zamanı, süre ve hassas içerik taşımayan hata kodu/mesajıdır. Test sırasında hedef/profil değişmişse eski başarı uygulanmaz. Testler cihazın üretici/model/tür, arayüz, izleme veya erişilebilirlik gözlemlerini değiştirmez; sonuç görev geçmişinde tutulur.

## Konfigürasyon, monitoring, alarmlar

SSH adaptörleri IOS (`show running-config`), Junos (`show configuration | display set | no-more`), FortiOS (`show full-configuration`), Linux (adres/yönlendirme çıktısı) için salt okunur komut çalıştırır. REST adaptörü cihaz üzerindeki açıkça tanımlanan HTTPS konfigürasyon endpoint'ini okur. Linux çıktısı tam işletim sistemi yedeği değildir. CLI exec desteği, yetki seviyesi ve pagination davranışı cihazda doğrulanmalıdır; gerçek cihaz uyumluluğu bu sürümün otomatik testleriyle kanıtlanmış sayılmaz.

Yedekler hash, boyut ve değişiklik işaretiyle sürümlenir. Görüntüleme ve unified diff maskelenmiş içerikte yapılır. Ağır dosyalar için 4 MB sınırı vardır.

Monitoring IF-MIB high-capacity sayaçları, hatalar ve drop değerlerini alır. Hız `delta_octets * 8 / elapsed_seconds`; reset, discontinuity, aşırı aralık veya kapasiteyle tutarsız hızlarda sonuç NULL'dır. Eksik veri sıfır değildir. Giriş ve çıkış ayrı hesaplanır. Alarm motoru erişim, maksimum port kullanımı, konfigürasyon değişimi ve no-data kurallarını; bekleme, histerezis, onay ve iyileşme geçişlerini uygular. Bildirim kanalı uygulamadaki kalıcı alarm akışı ve yetkili WebSocket güncellemesidir; e-posta/SMS/harici webhook teslimi bu sürümde yoktur.

Galera bağlantılarında yalnızca uygulama oturumuna `wsrep_sync_wait=1` uygulanır; bu, yazma sonrası başka düğümde eski durum okunmasını önler. Sunucunun global değişkenleri veya HAProxy ayarları değiştirilmez. VRF sürüm yazmasının sertifikasyona katılması [MariaDB sertifikasyon modeli](https://mariadb.com/docs/galera-cluster/galera-architecture/certification-based-replication) temelinde seçilmiştir; causal read davranışı [Galera sistem değişkenlerinde](https://mariadb.com/docs/galera-cluster/reference/galera-cluster-system-variables) açıklanır. Çok düğümlü eşzamanlılık için tasarlanan bu davranışın gerçek Galera çakışma testi teslimde yapılmış sayılmaz.
