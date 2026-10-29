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

SSH host key doğrulaması zorunludur. REST HTTPS sertifika doğrulaması açıktır; redirect takip edilmez. Üretici komutları sabit yetenek/adaptör tablosundadır; kullanıcıdan serbest komut alınmaz.

## Görev ve keşif davranışı

Aynı tür/hedef için en fazla bir etkin iş vardır. Tamamlanan işin tekrar tesliminde observation/snapshot/sample tekillikleri çift kayıt üretmez. 90 saniye heartbeat almayan işler yeniden kuyruğa alınır; en fazla üç deneme yapılır. Geçici hatalarda 15/30 saniye geri çekilme vardır. API iptal bayrağı yazar; worker en geç kontrol aralığında (5 saniye ve sürmekte olan kısa DB işlemi) ağ coroutine'lerini iptal eder. SIGTERM mevcut işi açık terminal duruma geçirir. Bir worker aynı anda tek mantıksal iş; keşif içinde en fazla dört hedef yürütür.

Kapsamlar varsayılan manuel çalışır; zamanlama açıkça etkinleştirilir. Bütün cihaz işlemleri etkin yetkili kapsamı yeniden kontrol eder. IPv6 ve 1024 adresten büyük ağlar açık hedef listesi gerektirir. Hariç tutmalar uygulanır. ICMP zorunlu değildir; SNMPv3 doğrudan sorgulanır. Başarısız hedefler kısmi/başarısız sonuçta sayılır; cevap vermemek cihazı silmez.

Yönetilen cihaz adı, gözlemlenen hostname tarafından değiştirilmez. ARP/NDP/FDB/VLAN port adayları kanıt ve güven düzeyiyle saklanır; LLDP/CDP isim eşleşmesi kesin fiziksel bağlantı sayılmaz. Birden fazla port adayı ve uplink kanıtı eşleşmeyi belirsiz bırakır. Topoloji bağlantıları son gözlem zamanını korur; kayıp komşu tek başarısız sorguda silinmez.

## Konfigürasyon, monitoring, alarmlar

SSH adaptörleri IOS (`show running-config`), Junos (`show configuration | display set | no-more`), FortiOS (`show full-configuration`), Linux (adres/yönlendirme çıktısı) için salt okunur komut çalıştırır. REST adaptörü cihaz üzerindeki açıkça tanımlanan HTTPS konfigürasyon endpoint'ini okur. Linux çıktısı tam işletim sistemi yedeği değildir. CLI exec desteği, yetki seviyesi ve pagination davranışı cihazda doğrulanmalıdır; gerçek cihaz uyumluluğu bu sürümün otomatik testleriyle kanıtlanmış sayılmaz.

Yedekler hash, boyut ve değişiklik işaretiyle sürümlenir. Görüntüleme ve unified diff maskelenmiş içerikte yapılır. Ağır dosyalar için 4 MB sınırı vardır.

Monitoring IF-MIB high-capacity sayaçları, hatalar ve drop değerlerini alır. Hız `delta_octets * 8 / elapsed_seconds`; reset, discontinuity, aşırı aralık veya kapasiteyle tutarsız hızlarda sonuç NULL'dır. Eksik veri sıfır değildir. Giriş ve çıkış ayrı hesaplanır. Alarm motoru erişim, maksimum port kullanımı, konfigürasyon değişimi ve no-data kurallarını; bekleme, histerezis, onay ve iyileşme geçişlerini uygular. Bildirim kanalı uygulamadaki kalıcı alarm akışı ve yetkili WebSocket güncellemesidir; e-posta/SMS/harici webhook teslimi bu sürümde yoktur.

Galera bağlantılarında yalnızca uygulama oturumuna `wsrep_sync_wait=1` uygulanır; bu, yazma sonrası başka düğümde eski durum okunmasını önler. Sunucunun global değişkenleri veya HAProxy ayarları değiştirilmez. VRF sürüm yazmasının sertifikasyona katılması [MariaDB sertifikasyon modeli](https://mariadb.com/docs/galera-cluster/galera-architecture/certification-based-replication) temelinde seçilmiştir; causal read davranışı [Galera sistem değişkenlerinde](https://mariadb.com/docs/galera-cluster/reference/galera-cluster-system-variables) açıklanır. Çok düğümlü eşzamanlılık için tasarlanan bu davranışın gerçek Galera çakışma testi teslimde yapılmış sayılmaz.
