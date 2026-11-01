# NETRIX çalışan mimarisi

NETRIX; FastAPI, SQLAlchemy/Alembic, harici MariaDB ve Redis kullanan modüler monolittir. Cihaz kimlikleri ortaktır; envanter keşfi ile VLAN IPAM toplama akışları ayrıdır. Hazır ağ yönetimi ürünü kullanılmaz.

Bağlantı menüsündeki harita, komşuluk cihaz listesi, bağlantı ayrıntıları ve işlemleri cihaz envanterine aittir (`devices.discovery_scope_id` dolu). IPAM için ortak tabloda tutulan envanter dışı cihazlar bu görünümlere veya bağlantı kimliği eşlemesine katılmaz. Kaynak ve eşleşmiş uzak cihaz için aynı sınır API sorgularında, sayaçlarda ve işlemlerde uygulanır; serbest protokol gözlemleri envanterdeki kaynak cihazın kanıtı olarak kalır. Silinen komşuluklarda arşivlenmiş envanter cihazının geçmişi korunur; geri yüklemeden önce cihaz geri alınmalıdır.

## Süreçler

Dağıtım tek servisli `netrix` Docker Compose stack'tir. `netrix-app` servisi yalnızca `netrix` container'ını oluşturur. Aşağıdaki adlar container değil, aynı container içinde Supervisor'ın yönettiği süreç adlarıdır. Harici MariaDB ve mevcut host Nginx bu uygulama stack'inin dışındadır. Container UID/GID 10001 ile çalışır; Redis yalnızca container loopback'ini dinler, `/data` kalıcı volume'dadır.

- `netrix-api`: React arayüzünü ve `/api/v1` API'lerini sunar. Ağ sorgusu yürütmez.
- `netrix-worker`: MariaDB'den `FOR UPDATE SKIP LOCKED` ile iş alır. SNMPv3, SSH ve HTTPS REST bağlantıları bu süreçtedir.
- `netrix-tests`: kullanıcı bağlantı testleri için ayrı worker süreci; en fazla dört eşzamanlı salt okunur probe. Normal keşif/yedekleme ve toplu aktarım işleri bu kapasiteyi kullanmaz.
- `netrix-scheduler`: etkin politikaları 15 saniyede bir değerlendirir; işler aynı kuyruk servisinden geçer.
- `netrix-redis`: WebSocket güncelleme sinyalleri, kimlik doğrulama hız sınırı ve süreç heartbeat'leri. İş kaydının asıl kaynağı MariaDB'dir; Redis kesintisi kalıcı işleri silmez.
Başlangıç komutu önce Alembic migration'ı uygular; başarısızlıkta API/Redis/worker/zamanlayıcı başlamadan container hata koduyla çıkar. Başarıdan sonra PID 1 Supervisor olur. Süreç arızasında ilgili süreç yeniden başlatılır; başlangıçta artan gecikmeyle beş tekrar sınırı vardır. Sağlık kontrolü beş sürecin RUNNING durumunu, DB/Redis readiness'ini ve worker/zamanlayıcı/test çalıştırıcısının güncel heartbeat'lerini gerektirir. Kalıcı başlangıç hatasında container unhealthy olur; işletmeci logları inceleyip düzeltmelidir (Docker standalone yalnızca unhealthy olmayı otomatik restart sebebi saymaz).

SIGTERM'de önce zamanlayıcı, sonra worker, API ve son olarak Redis kapanır. Worker'a 30 saniye, tüm container'a 60 saniye kapanma süresi verilir. Yedekleme/geri yükleme istemcisi de bu container içinde ek bir süreç olarak çalışır; ek yardımcı container oluşturmaz.

`backend/netrix/identity`, `discovery`, `configuration`, `alerting` protokol ve iş kurallarının sınırlarını oluşturur. Merkezi kaynak işlemleri `services.py`, modeller `models.py` içindedir. `inventory` ve `ipam` aynı servis katmanındaki transaction doğrulamalarını kullanır.

## MariaDB uyarlaması

Proje sahibinin 29 Ekim 2026 kararı PostgreSQL/TimescaleDB hedefinin yerini alır. Harici MariaDB'de InnoDB, UUID için `VARCHAR(36)`, normalize IP/CIDR için metin, ek kanıt için JSON, unsigned 64 bit sayaçlar için `DECIMAL(20,0)` kullanılır. `DATETIME(6)` değerleri UTC'ye normalize edilir, okunurken UTC tzinfo eklenir. API ISO 8601 zaman dilimli değer döndürür; arayüz tarayıcının yerel saatinde gösterir.

IPAM'de aynı VRF içindeki yazmalar `system_state` tablosundaki `vrf:<UUID>` satırında serileştirilir; atomik upsert sayacı artırır. Böylece farklı Galera düğümlerindeki eşzamanlı yazmalar da sertifikasyon aşamasında çakışır; yalnızca düğüme yerel satır kilidine güvenilmez. VRF kaydı güncel paylaşımlı okumayla doğrulanır; üst kayda özel yazma kilidi konmadığından komşu tablolardaki FK kontrolleri engellenmez. Keşif kapsamı oluşturma/düzenleme bu IPAM yazma kilidini almaz ve tarama başlatmaz. Mevcut `vrfs.lock_version` alanı uyumluluk için korunur. Geçici DB hatası API'de 503 döner; HTTP metodu, yol ve sayısal hata kodu sırlar/SQL parametreleri olmadan loglanır. Worker sınırlı tekrar uygular; VRF+IP tekilliği ayrıca DB kısıtıdır. CIDR/üyelik, site/VRF uyumu, IPv6 ve /31-/32 kuralları servis katmanında doğrulanır. VLAN CIDR'ları aynı VRF içinde çakışamaz. Kullanım yüzdesi son 24 saat içindeki son ICMP yanıtı olumlu olan adresleri sayar. Eski `docs/data-model.md`, daha ayrıntılı hedef modelidir; uygulanmış tablolar için Alembic migration ve `models.py` esastır.

Trafik toplama ve geçmiş tabloları 20261101_20 migration ile kalıcı olarak kaldırıldı.

## Güvenlik

İlk yönetici ancak tek kullanımlık kurulum anahtarıyla oluşturulur; DB'deki singleton satır kilidi aynı anda ikinci kurulum yapılmasını engeller. Parolalar Argon2id özetidir. Oturum token'larının yalnızca SHA-256 özeti DB'dedir. Cookie HttpOnly/Secure/SameSite Strict; yazma isteklerinde özel başlık ve Origin kontrolü vardır. Admin/operator/viewer API ve WebSocket'te kontrol edilir. Parola değişimi bütün oturumları iptal eder.

Credential ve tam konfigürasyonlar Fernet ile şifrelenir. Anahtar DB dışında `.env` dosyasındadır. API credential sırlarını döndürmez; konfigürasyon görüntüleme ve diff hassas satırları maskeler. JSON doğrulama hataları girilen sırları yansıtmaz; SQL loglarında parametreler gizlenir. Secret dosyaları ve anahtarlar Git dışında tutulur.

SSH host anahtarı varsayılan olarak `known_hosts` ile doğrulanır. `devices.ssh_trust_host_key` yalnızca açık kullanıcı seçimiyle etkinleştirilirse o cihaza ait SSH test/kimlik/yedek bağlantıları sunulan anahtarı kabul eder (`known_hosts=None`); anahtar sabitleme yapılmaz. Kullanıcı doğrulaması, aktif cihaz denetimi ve timeout devam eder. Alembic `20261030_04` mevcut cihazlara kapalı varsayılan ekler. REST HTTPS sertifika doğrulaması açıktır; redirect takip edilmez. Üretici komutları sabit yetenek/adaptör tablosundadır; kullanıcıdan serbest komut alınmaz.

## Görev ve keşif davranışı

Aynı tür/hedef için en fazla bir etkin iş vardır. Tamamlanan işin tekrar tesliminde observation/snapshot/sample tekillikleri çift kayıt üretmez. 90 saniye heartbeat almayan işler yeniden kuyruğa alınır; en fazla üç deneme yapılır. Geçici hatalarda 15/30 saniye geri çekilme vardır. API iptal bayrağı yazar; worker en geç kontrol aralığında (1 saniye ve sürmekte olan kısa DB işlemi) ağ coroutine'lerini iptal eder. SIGTERM kullanıcı iptali olmayan arka plan işlerini yeniden kuyruğa alır; etkileşimli işlemler sonlandırılır. Tek worker sürecinde en fazla dört arka plan görevi yürür; bunların en fazla ikisi SNMP ağ keşfidir. Böylece uzun taramalar diğer işlerin bütün kapasitesini kullanamaz. Aynı hedefe ait arka plan işleri sırayla yürütülür; boş kapasite 250 ms aralıkla kontrol edilir. Görevin ilk çalıştırılma zamanı sonuç metadatasında korunur. IPAM ping/adres keşfi aynı anda en fazla 32 adresi kontrol eder; her gruptan önce ve sonra VLAN tarama ayarı ve iptal durumu yeniden doğrulanır. Görev merkezi hedef ağ/cihazı listeler; açıklama penceresi işin amacı, durum, zamanlar ve seçilmiş sonuçları düz metinle gösterir, ham sonuç/konfigürasyon çıktısı göstermez.

Kapsamlar varsayılan manuel çalışır; zamanlama açıkça etkinleştirilir. Envantere yeni cihaz almak etkin envanter kapsamı gerektirir. Mevcut cihazın bağlantı ve konfigürasyon işleri bu kapsama bağlı değildir. IPv4 kapsamları adres sayısı sınırı olmadan kaydedilir; hedefler belleğe topluca alınmadan 16 sabit tüketici tarafından işlenir. SNMP profilleri seçilen sırayla önce temel sistem GET sorgusuyla denenir (1 saniye taşıma süresi, bir tekrar, toplam 3 saniye üst sınır). Yalnızca yanıt veren profille kapsamlı tablolar okunur; aynı keşifte en fazla dört kapsamlı okuma yapılır. Büyük ağların tamamlanma süresi hedef sayısına, yanıt vermeyen adreslere ve cihaz yanıt sürelerine bağlıdır. Açık hedef listesi IPv4 için isteğe bağlı, IPv6 için zorunludur. Hariç tutmalar uygulanır. ICMP zorunlu değildir; SNMPv3 doğrudan sorgulanır. Başarısız hedefler kısmi/başarısız sonuçta sayılır; cevap vermemek cihazı silmez.

Yönetilen cihaz adı, gözlemlenen hostname tarafından değiştirilmez. ARP/NDP/FDB/VLAN port adayları kanıt ve güven düzeyiyle saklanır; LLDP/CDP adı aynı VRF içindeki tekil uç kimliğiyle doğrulanır. Yalnızca FDB üzerinde görülen birden fazla port ve transit uplink kanıtı belirsiz bırakılır. Topoloji bağlantıları son gözlem zamanını korur; kayıp komşu tek başarısız sorguda silinmez.

IPAM fiziksel bağlantı çözümlemesinde firewall ARP/NDP kaydı yalnızca IP–MAC kimlik kanıtıdır; yönlendirilmiş VLAN arayüzü cihazın bağlı portu olarak gösterilmez. Komşunun kendi MAC'i aynı portun FDB kaydıyla örtüşüyorsa AP/sunucu komşuluğu transit uplink sayılmaz; o komşunun arkasındaki farklı MAC'ler bu istisnadan yararlanmaz.

### VLAN IPAM sınırı

VLAN, IP bloğu ve DNS/zamanlama ayarlarının sahibidir. Kayıt ile `ipam_discover` işi atomik oluşturulur. Bağımsız ağ bloğu tablosu, API ve envanterden IPAM'e eski gözlem aktarımı kaldırılmıştır. Entegrasyonlar VMware, DHCP, Corner Switch ve Backbone Switch kaynaklarını IPAM içinde toplar; envanter/topoloji gözlemlerini kullanmaz. Ayrıntılar: [VLAN ve entegrasyonlar](ipam-integrations.md).

VLAN silme önizlemesi `/api/v1/ipam/vlans/delete-preview`, toplu silme `/api/v1/ipam/vlans/bulk-delete` üzerindedir. Silme IP/gözlemleri ve o VLAN'ın ping/keşif işlerini kapsar. Envanter, keşif kapsamları ve tüm VLAN'lara hizmet veren entegrasyonlar korunur. Eski bir kolektör silinmiş VLAN'a yeniden IP yazamaz.

### Otomatik cihaz bilgileri

Cihaz oluşturulunca veya bağlantı/üretici/model/tür bilgileri değişince, cihaz aktifse ve erişim profili varsa aynı transaction içinde `identify` işi kuyruğa eklenir. Kaydetme işlemi ağ yanıtını beklemez. Yeni cihaz adresi envanter keşif kapsamı dışındaysa kayıt reddedilir. Profil yoksa kapsam içindeki kayıt saklanır ve kimlik sorgusunun başlatılmadığı bildirilir. Dağıtım mevcut cihazlar için kendiliğinden sorgu başlatmaz. Ayrıntılardaki **Bilgileri cihazdan al**, `POST /api/v1/jobs` üzerinden `kind: identify` ile yeniden sorgu başlatır.

Önce SNMPv3 profili, eksik alan varsa SSH/API profili denenir. Her alan bağımsız uygulanır: cihazdan belirlenen üretici, model ve tür manuel değerlerin üzerine yazılır; boş, bilinmeyen, desteklenmeyen veya belirsiz sonuçlar mevcut değerleri silmez. Tür, cihazın açık tür alanından veya tanınan model ailesinden/sistem açıklamasından belirlenir; bağlantı adaptörünü seçmek tek başına üretici veya tür kanıtı değildir. Yeni cihazın başlangıç türü `other` olur. Gözlem `identity`, alan başına protokol kaynağı ve okuma durumu içerir; değişen değerler olay geçmişine kaydedilir. Salt kimlik sorgusu arayüzleri silmez veya port durumlarını değiştirmez. SNMP keşif gözlemleri de aynı alan güncelleme hizmetini kullanır.

- SNMPv3: [ENTITY-MIB](https://www.rfc-editor.org/rfc/rfc4133.html) chassis(3) girdilerinin üretici/model alanları, sysObjectID ve sysDescr kullanılır. Modül/SFP modeli cihaz modeli sayılmaz; farklı şasi modelleri belirsiz bırakılır.
- SSH: IOS için [show version](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/command_reference/b_1718_9300_cr/system_management_commands.html), Junos için [show version](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/command/show-version.html), FortiOS için [get system status](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/173707/firmware-maturity-levels) ve Linux için [DMI sysfs alanları](https://github.com/torvalds/linux/blob/master/drivers/firmware/dmi-id.c) okunur. Cihazın kayıtlı SSH anahtar güven tercihi uygulanır; serbest komut alınmaz. Gerçek cihazların CLI exec desteği ve çıktı biçimleri ayrıca doğrulanmalıdır.
- REST: ayrı `identity_path` alanı (varsayılan `/api/system`) kullanılır. Evrensel bir üretici endpoint'i değildir; cihazın gerçek JSON bilgi yoluna ayarlanmalıdır. Kabul edilen alanlar `vendor`/`manufacturer`, `model`/`model_name`, `kind`/`device_type`/`type`; isteğe bağlı `results`, `data` veya `system` nesnesi içindedir. TLS doğrulaması açık, yönlendirme kapalı ve yanıt sınırı 256 KiB'dir. Ham API/CLI çıktısı veya token bu gözlemde saklanmaz.

Kimlik işi mevcut iptal, heartbeat, sınırlı yeniden deneme ve hedef/tür başına tek etkin iş kurallarını kullanır. Ağ isteği sırasında bağlantı hedefi veya erişim profili değişmişse eski yanıt uygulanmaz; güncel bilgilerle yeniden denenir. Üç alan alınmışsa başarılı, bir kısmı alınmışsa kısmi, hiçbiri belirlenememişse başarısız sonuç gösterilir.

### Cihaz bağlantı testleri

Cihazın **Kaydı düzenle** penceresindeki **Bağlantı testi → Test**, cihazın güncel kayıtlı profillerini `GET /api/v1/devices/{id}/connection-tests` ile yükler. SNMPv3/SNMPv2c/SSH/API seçenekleri yalnızca atanmış ve adaptörle uyumlu profil varsa etkinleşir; sırlar tarayıcıya dönmez. Pencereyi açmak ağ isteği başlatmaz. `POST /api/v1/devices/{id}/connection-tests`, `protocol: snmpv3|snmpv2c|ssh|rest` ile seçilen protokole ait `test_snmp`, `test_snmpv2c`, `test_ssh` veya `test_api` işini oluşturur. Admin/operator yetkisi ve aktif cihaz API'de ve worker'da kontrol edilir; diğer protokollere otomatik geçiş yapılmaz.

Etkileşimli uç nokta, işlemi `result.interactive` işaretiyle ayrı `netrix-tests` sürecine verir. API ağ probe'u çalıştırmaz. Kalıcı görev kaydındaki `queued` yalnızca worker'a kısa teslim durumudur: çalıştırıcı 250 ms aralıkla kontrol eder ve dört boş yuvadan birinde başlatır; uzun normal işleri beklemez. Bu süre bir uçtan uca gecikme garantisi değildir; veritabanı ve ağ bağlantısı süreleri ayrıca etkilidir. Toplu aktarım testleri ve genel `/jobs` işleri arka plan worker'ında kalır. Aynı cihaz/protokol için bekleyen normal test varsa açık Test isteği bunu etkileşimli yürütmeye yükseltir; zaten çalışan test ikinci kez açılmaz.

Kabul, Redis dağıtık kilidi ve MariaDB güncel kilitlemeli okumasıyla sınırlanır. Dört etkileşimli test zaten kabul edilmişse yeni istek 429 ile reddedilir ve yeni iş kaydı bırakılmaz. Çalıştırıcı heartbeat'i 15 saniyeden eskiyse veya Redis erişilemezse 503 döner. MariaDB 1020/1213 işlem çatışmasında yalnızca kabul transaction'ı bir kez tekrar edilir; cihaz probe'u tekrarlanmaz. Normal worker etkileşimli işleri, etkileşimli worker normal işleri almaz. Test çalıştırıcısı kesilirse eski çalışan test 90 saniyelik mevcut toparlama sınırında başarısız kapatılır; otomatik tekrar kuyruğuna dönmez. Test iptali etkileşimli yürütücüde 250 ms aralıkla kontrol edilir (sürmekte olan kısa DB işlemi ayrıca etkileyebilir).

SNMPv3 testi authPriv ile sistem OID'lerini GET üzerinden okur ve sysUpTime'ın okunabilir olduğunu doğrular; tablo taraması yapmaz. SSH testi cihazın kayıtlı anahtar güven tercihiyle oturum açar; konfigürasyon komutu çalıştırmaz. API testi kayıtlı `identity_path` yoluna token ile HTTPS GET yapar; TLS doğrulaması açıktır, yönlendirme izlenmez, 2xx ve geçerli JSON nesne/liste yanıtı gerekir, üst sınır 256 KiB'dir. API başarı mesajı bu HTTP/JSON kontrolünü bildirir; endpoint'in token'ı nasıl yetkilendirdiğine ilişkin ek bir varsayım yapmaz.

Her testin yürütme süresi en fazla 30 saniyedir; SNMP taşıması 2 saniye timeout ve bir protokol tekrarı kullanır. Etkileşimli testin bağlantı hatası terminal başarısız sonuçtur; otomatik 15/30 saniyelik iş tekrarı yapılmaz. Başlatılıyor/çalışıyor/başarılı/başarısız/iptal durumları pencerede izlenir ve iptal istenebilir. Aynı cihaz/protokol için bir etkin iş vardır. Sonuç; protokol, hedef, port, UTC kontrol zamanı, süre ve hassas içerik taşımayan hata kodu/mesajıdır. Test sırasında hedef/profil değişmişse eski başarı uygulanmaz. Testler cihazın üretici/model/tür, arayüz veya erişilebilirlik gözlemlerini değiştirmez; sonuç görev geçmişinde tutulur.

## Konfigürasyon ve değişiklik uyarıları

Yedekleme yalnızca SSH kullanır; API ve worker SSH profilini ve adaptörü doğrular. REST/SNMP yedekleme ve protokoller arasında otomatik geçiş yoktur. IOS (`show running-config`), Junos (`show configuration | display set | no-more`) ve Linux (adres/yönlendirme çıktısı) SSH komutları kullanır. FortiOS, SSH/SCP ile `sys_config` dosyasını indirir; CLI ekran çıktısı yedek sayılmaz. SCP hataları, kesilen aktarım, eksik dosya başlığı/bitişi, sayfalama ve 4 MiB üstü dosya reddedilir. Geçici dosya 0700 dizinde 0600 izinlidir, başarı/hata/iptalde temizlenir; üretimde `/tmp` tmpfs üzerinde bulunur. Cihazdaki `admin-scp` ve yönetici yetkileri otomatik değiştirilmez. [Fortinet kaynakları ve ön koşullar](fortigate-ssh-backup.md). Linux çıktısı tam işletim sistemi yedeği değildir. CLI exec desteği, yetki seviyesi ve pagination davranışı cihazda doğrulanmalıdır; gerçek cihaz uyumluluğu bu sürümün otomatik testleriyle kanıtlanmış sayılmaz.

Yedekler hash, boyut ve değişiklik işaretiyle sürümlenir. Görüntüleme ve unified diff maskelenmiş içerikte yapılır. Ağır dosyalar için 4 MB sınırı vardır.

Alarm motoru konfigürasyon değişiklikleri için bekleme, onay ve iyileşme geçişlerini uygular. Trafik, port kullanımı ve veri yokluğu alarmları kaldırılmıştır.

Galera bağlantılarında yalnızca uygulama oturumuna `wsrep_sync_wait=1` uygulanır; bu, yazma sonrası başka düğümde eski durum okunmasını önler. Sunucunun global değişkenleri veya HAProxy ayarları değiştirilmez. VRF sürüm yazmasının sertifikasyona katılması [MariaDB sertifikasyon modeli](https://mariadb.com/docs/galera-cluster/galera-architecture/certification-based-replication) temelinde seçilmiştir; causal read davranışı [Galera sistem değişkenlerinde](https://mariadb.com/docs/galera-cluster/reference/galera-cluster-system-variables) açıklanır. Çok düğümlü eşzamanlılık için tasarlanan bu davranışın gerçek Galera çakışma testi teslimde yapılmış sayılmaz.

## Seçilebilir envanter ve yedek yönetimi (30 Ekim 2026)

`inventory.management` cihaz, arayüz ve yedek listelerini sunucu tarafında sayfalar; arama bütün açık alanları, cihaz/lokasyon/VRF/profil/grup adlarını ve Türkçe durum etiketlerini kapsar. En fazla 20 izinli alan koşulu sırasıyla VE/VEYA ile birleştirilir. Değişen yedekler ve cihaz kapsamı, kullanıcı koşullarından bağımsız zorunlu filtrelerdir. Sütun tercihleri kullanıcı ve ekran başına tarayıcıda saklanır. Gizli profil ve konfigürasyon içerikleri arama/sütun API'sine katılmaz.

Keşfedilen arayüzler merkezi envantere adaydır. `is_managed` envantere alınmayı, `is_deleted` listeden kaldırılmayı, `auto_add_excluded` tekrar otomatik eklenmeme tercihini tutar. Cihaz silme arşivler, zamanlamaları kapatır ve konfigürasyon geçmişini korur.

Toplu cihaz değişiklikleri yalnızca VRF, lokasyon, üretici, tür, model, yaşam döngüsü, adaptör, erişim profilleri, SSH güveni ve yedek aralıkları için kabul edilir. Satırlar sıralı kilitlenir; doğrulama başarısızsa tüm işlem geri alınır. Silme admin, değiştirme ve arayüz seçimi admin/operator yetkisindedir.

`configuration.management` grup politikası, saklama sınırı ve canlı karşılaştırmayı yönetir. Grup atanmış cihazda grup aralığı/saklama sınırı cihaz değerlerinin yerini alır; 0 zamanlamayı kapatır/saklamayı sınırsız yapar. Zamanlayıcı aynı cihaz için son yedek denemesini de dikkate alır. Saklama en yeni N sürümü ve kalıcı base config kaydını tutar; çalışan/kuyruktaki karşılaştırmanın temel yedeği tamamlanana kadar korunur. Yeni yedekten sonra ve zamanlayıcı çevriminde temizlik uygulanır.

`compare` işi kayıtlı SSH profiliyle aktif konfigürasyonu worker'da salt okunur çeker ve seçilen yedekle maskelenmiş unified diff üretir. Aktif cihaz, bağlantı ayarlarının değişmediği ve iptal durumu kontrol edilir. Yeni yedek oluşturmaz veya yedek zamanlamasını ötelemez. Diff yalnızca admin/operator karşılaştırma uç noktasında döner; genel görev yanıtında gizlenir. Yedek indirme de maskelenmiş içeriktir. Silinen cihazın eski yedekleri listelenebilir; canlı karşılaştırma aktif cihaz gerektirir.

Konfigürasyon farkları, onaylar ve çoklu cihaz karşılaştırması için [base config kuralları](configuration-baselines.md) geçerlidir.
