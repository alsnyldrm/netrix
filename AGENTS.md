# NETRIX

## Network Intelligence, Discovery & Management Platform

**Türkçe adı:** Akıllı Ağ Keşif ve Yönetim Platformu

**Kısa adı ve uygulama kimliği:** NETRIX

## Amaç ve kapsam

NETRIX, sıfırdan geliştirilecek, proje sahibine ait, web tabanlı ve merkezi bir ağ keşif, IP adres yönetimi, konfigürasyon yönetimi platformudur. Mimari modüler monolittir; iki modül ortak cihaz envanterini ve merkezi kimlik doğrulamayı kullanır.

### 1. IPAM & Network Discovery

- Subnet, VLAN ve IPv4/IPv6 adres yönetimi; otomatik IP ve cihaz keşfi.
- IP, MAC, hostname ve VLAN eşleştirme; cihazların bağlı olduğu switch ve fiziksel portun tespiti.
- LLDP/CDP ile üst ve alt switch ilişkilerinin keşfi ve otomatik ağ topolojisi.
- IP ve bağlantı değişikliklerinin geçmişi ve takibi.

### 2. Configuration Management

- Switch, router ve firewall cihazlarına SSH, SNMP ve REST API üzerinden erişim.
- Cihaz yeteneklerine göre SSH/API ile otomatik ve zamanlanmış konfigürasyon yedekleme; SNMP ile desteklenen envanter ve durum bilgilerini toplama.
- Konfigürasyon sürüm geçmişi, satır bazında karşılaştırma, değişiklik tespiti ve otomatik uyarılar.

## Teknik kararlar

| Katman | Tercih |
| --- | --- |
| Backend | Python / FastAPI |
| Kalıcı veri | MariaDB (harici sunucu) |
| Görev altyapısı | Redis destekli kuyruk ve zamanlayıcı |
| Veri toplama | NETRIX için Python ile geliştirilen worker servisleri |
| Protokoller | SNMPv3, SSH, REST API; komşuluk verisi için LLDP/CDP |
| Canlı bildirim | WebSocket |
| Dağıtım | Docker Compose |
| Mimari | Modüler monolit, merkezi envanter, ayrı worker süreçleri |

## Geliştirme kuralları

1. NetBox, Oxidized, LibreNMS, Zabbix gibi hazır network yönetim ürünlerini uygulamanın temeli veya modül motoru olarak kullanma. IPAM, keşif, konfigürasyon karşılaştırma ve değişiklik uyarılarını NETRIX için geliştir.
2. Açık kaynak geliştirme kütüphaneleri ve altyapı bileşenleri kullanılabilir. Lisanslarını değerlendir ve bağımlılıkları proje dosyalarında kaydet.
3. Proje kimliği, servis adlandırmaları ve API dokümantasyonunda NETRIX kullan; teknik tanımlayıcılarda `netrix`, Compose servislerinde `netrix-*`, API başlığında `NETRIX API` kullan. API başlangıç yolu `/api/v1` olsun.
4. Modüller cihaz, arayüz, adres ve kullanıcı verilerini merkezi model üzerinden paylaşsın. Aynı cihaz için modül başına ayrı envanter oluşturma.
5. Cihaz erişim bilgilerini uygulama katmanında şifrele; anahtarları veritabanından ayrı, ortam veya secret dosyalarından al. Parola, anahtar, token ve SNMP sırlarını loglara, API yanıtlarına veya Git'e yazma. Kullanıcı parolalarını geri döndürülebilir şifreleme yerine güçlü parola özetiyle sakla.
6. Üretici ayrıntılarını yetenek tabanlı adaptörlerde tut. İş kurallarını FastAPI route'larından ve protokol istemcilerinden ayır; modüller arasında açık servis arayüzleri kullan.
7. Öncelik backend, API, veritabanı ve cihaz bağlantı motorlarıdır. Arayüzü proje sahibinin yönlendirmeleriyle, aşağıdaki Codex dışı tasarım becerilerini kullanarak tasarla. Tasarım yetkisi verilmiştir; son kullanıcı talebi tüm uygulamayı kapsar: IPAM/keşif, konfigürasyon motorları ile üretim arayüzünü birlikte geliştir.
8. Ağ işlemlerini worker'da yürüt; API isteklerini uzun taramalarla bloke etme. Timeout, sınırlı eşzamanlılık, kontrollü yeniden deneme, iptal ve yinelenen görevleri güvenli işleme davranışını tanımla.
9. Keşif yalnızca yapılandırılmış ve yetkilendirilmiş ağ kapsamlarında çalışsın. Aktif taramayı kullanıcı veya zamanlama tetiklesin; testler varsayılan olarak gerçek ağa erişmesin.
10. Envanterdeki yönetilen değerleri keşif gözlemlerinden ayır. Belirsiz cihaz/port eşleşmelerini kanıt ve güven düzeyiyle sakla; bunları kesin ilişki gibi sunma.
11. Şema değişikliklerini Alembic migration ile sürümle. Zamanları UTC ve zaman dilimli sakla; kullanıcıya gösterirken yerel saate dönüştür.
12. Uygulanan davranışı hedefli testlerle doğrula. Protokoller için sahte istemciler, MariaDB kısıtları için entegrasyon testleri kullan; çalıştırılmamış kontrolleri başarılı olarak raporlama.

## Göreve göre okunacak belgeler

- Veri modeli, migration, envanter, keşif, konfigürasyon işi yaparken [kapsamlı veri modelini](docs/data-model.md) oku. Bu belge hedef tasarımdır; tabloların uygulanmış olduğunu varsayma.
- Altyapı kurulumu ve ilk sürüm geliştirmesinde [sıralı geliştirme planını](docs/development-plan.md) izle. Her adımı kabul ölçütleriyle doğrula; yalnızca mevcut isteğin kapsadığı adımları uygula.

## Beceriler ve MCP araçları

Proje sahibi, NETRIX için Codex dışı becerilerin ve MCP sunucularının kullanımını yetkilendirmiştir. Göreve uygun araçları seç; tüm araçları her görevde çalıştırma. Burada "Codex dışı", Codex'in yerleşik sistem becerileri yerine oturumda sunulan harici beceri paketlerini ifade eder. Bu beceriler Codex içinden kullanılabilir.

### Kullanılacak harici beceriler

Beceriyi uygulamadan önce oturumdaki beceri kataloğundan ilgili `SKILL.md` dosyasını bul ve oku. Yerel kurulum yollarını bu public depoya sabitleme; eksik beceriyi varmış gibi kullanma.

| Görev | Beceri | NETRIX'teki kullanım |
| --- | --- | --- |
| Tüm tasarım, arayüz, UX ve görsel kimlik işleri | `ui-ux-pro-max` | En küçük görsel değişiklik dahil tüm ekranlar, bileşenler, hizalama, tipografi, ikonlar, uygulama simgesi ve favicon |
| PostgreSQL şeması ve performans | `postgresql-table-design`, `sql-optimization-patterns` | IPAM ilişkileri, kısıtlar, indeksler ve sorgu planları |
| Şema sürümleme | `database-migration` | Alembic değişiklikleri ve veri dönüşümleri |
| Kimlik ve sır yönetimi | `auth-implementation-patterns`, `secrets-management` | Merkezi yetkilendirme, cihaz erişim bilgileri ve anahtar yönetimi |
| Python doğrulaması | `python-testing-patterns` | Worker, API ve protokol adaptörü testleri |
| Tarayıcı doğrulaması | `webapp-testing`, `web-design-guidelines` | Arayüz hazır olduğunda gerçek tarayıcı ve erişilebilirlik kontrolleri |
| CI | `github-actions-templates` | Backend ve migration kontrollerinin GitHub Actions'a taşınması |
| Teşhis ve teslim | `systematic-debugging`, `verification-before-completion` | Hata kök nedeni ve kanıta dayalı teslim kontrolü |
| Ajan yönergeleri | `writing-for-agents` | Bu dosyanın ve görev yönergelerinin bakımı |

### Zorunlu tasarım ve hizalama kuralları

- Uygulamadaki tüm tasarımları yalnızca **UI UX Pro Max (`ui-ux-pro-max`)** ile yap. Yeni ekranlardan mevcut bir butonun boşluğuna, tek bir ikonun konumuna veya bir noktalama işaretinin görünümüne kadar en küçük tasarım değişikliğinde bile bu beceriyi oku ve uygula; değişikliğin küçüklüğü istisna değildir. Görsel değişiklik içermeyen backend işlerinde tasarım becerisi gerekmez.
- Arayüzün en küçük ayrıntısına kadar simetri ve tutarlı hizalama zorunludur. Butonlar, form alanları, tablo hücreleri, ikonlar, başlıklar ve metinler ortak hizalama eksenlerine ve düzenli boşluklara uysun. Virgül ve nokta dahil noktalama işaretleri bile metnin taban çizgisi ve tipografik aralıklarıyla uyumlu olsun. Hizasız buton, alan veya başka bir öğe bırakma.
- Her görsel değişikliği teslim etmeden önce etkilenen ekranları masaüstü ve mobil boyutlarda tarayıcıda kontrol et; kenar hizalarını, metin taban çizgilerini, ikon/metin merkezlerini ve eşdeğer öğeler arasındaki boşluk simetrisini doğrula. Tespit edilen hizasızlıkları giderdikten sonra işi tamamlanmış say.

### MCP sunucuları ve bağlantı durumu

Bu liste bu çalışma hazırlanırken görülen yetenekleri kaydeder. Her oturumda araç keşfiyle güncel erişimi doğrula; NETRIX çalışma zamanına bu MCP sunucularını bağımlılık olarak ekleme.

| MCP / araç ad alanı | Durum | Kullanım |
| --- | --- | --- |
| GitHub — `mcp__codex_apps__github` | Bağlı; hesap erişimi doğrulandı | Depo içeriği, issue, PR ve CI sonuçlarını inceleme; istenen GitHub işlemleri |
| Web arama — `mcp__codex_apps__search_service` | Oturumda araçları mevcut | Protokol, kütüphane ve sürüm kararlarında resmi kaynak araştırması |
| Eklenti yönetimi — `mcp__codex_apps__plugin_management` | Oturumda araçları mevcut | Gereken ek bağlantıların bulunması ve erişim durumlarının kontrolü |
| Figma | Henüz bağlı değil; isteğe bağlı | Figma tasarım dosyası veya tasarım aktarımı gerektiğinde keşfet ve bağlantısını doğrula |
| Playwright / tarayıcı MCP | Bu oturumda bağımsız sunucu doğrulanmadı | Erişilebilir olursa arayüz testi; aksi halde `webapp-testing` ile yerel Playwright kullan |
| PostgreSQL MCP | Bu oturumda bağımsız sunucu doğrulanmadı | Gerekirse geliştirme veritabanı şemasını inceleme; mevcut değilse migration ve yerel DB araçları kullan |

GitHub bağlantısının desteklemediği depo oluşturma ve Git aktarımı işlemleri için yerel Git ve kimliği doğrulanmış GitHub CLI kullan. MCP erişimi ile yerel CLI oturumu ayrıdır; birinin bağlı olması diğerinin kimliğinin doğrulandığı anlamına gelmez. Geniş araç kullanım yetkisi, sırların üçüncü taraflara aktarılmasına veya gerçek ağlarda kapsam dışı taramaya izin vermez.

## Güncel teslim ve dağıtım kararı (29 Ekim 2026)

- Her değişiklikten sonra ilgili doğrulamaları çalıştır, değişikliği Git commit ile kaydet, uzak depoyla senkronize et (fetch ve push) ve aynı commit'i sunucuya deploy et. Push ve sunucu sağlık kontrolü doğrulanmadan işi tamamlanmış sayma. Bu iş akışı için proje sahibinin sürekli yetkisi vardır; her seferinde yeniden onay isteme. Sır dosyalarını ve kalıcı verileri bu işlemlerin dışında tut.
- Proje sahibi tüm uygulamanın tek çalışma kapsamında geliştirilmesini ve yayına alınmasını istedi. Önceki ilk dilim sınırı bu istekle genişletildi.
- NETRIX tek servisli Docker Compose stack olarak çalışır: stack `netrix`, servis `netrix-app`, container `netrix`. API/arayüz, Redis, worker ve zamanlayıcı aynı container içindeki ayrı süreçlerdir; migration aynı container başlangıcında uygulanır. Harici MariaDB ve mevcut host Nginx kullanılır. Ayrı NETRIX Redis/worker/migration container'ı oluşturma.
- Uygulama ve dağıtım kimliği `netrix`; API başlığı `NETRIX API`, API kökü `/api/v1`.
- Docker sunucusu `10.2.0.87`. SSH bağlantı yönergeleri çalışma ortamındaki `/home/alisan/codex/key/config` dosyasındadır; anahtar içeriğini depoya kopyalama.
- Uygulama DB bağlantısı yalnızca VIP `10.2.0.31:3306` üzerinden yapılır; doğrudan SQL düğümlerine yönlendirme yapma.
- Harici MariaDB: sunucu `10.2.0.31`, veritabanı `netrix`, kullanıcı `netrix`. Parola yalnızca sunucudaki izinleri kısıtlanmış secret dosyasında tutulur; bu belgeye veya Git'e yazılmaz.
- Yeni PostgreSQL/TimescaleDB servisi kurma. Eski veri modeli ve geliştirme planındaki PostgreSQL türleri hedef kavramları anlatır; MariaDB uygulamasında UUID metin, normalize IPv4/IPv6 metin ve servis doğrulaması, JSON, UTC DATETIME kullan. UTC zaman dilimini API'de geri ekle.
- Docker uygulama portunu mevcut atamaları ve dinleyen portları inceleyerek sıradaki boş uygulama portundan seç; host Nginx bu porta proxy yapsın.
- Nginx host network modundadır. Kullanıcı yolu `/op/nginx/conf/conf` olarak iletti; sunucuda doğrulanan gerçek dizin `/opt/nginx/conf/conf.d`. NETRIX'e ayrı conf ekle; sertifika yollarını mevcut sitelerden doğrula. `nginx -t` başarılı olmadan reload yapma; mevcut siteleri değiştirme.
- Dış erişim HTTPS/443 üzerinden olur; domain `netrix.fbu.edu.tr` (proje sahibi doğruladı). İç proxy portu sunucuda boş olduğu doğrulanan `127.0.0.1:8101`; mevcut wildcard sertifika yolları `/etc/nginx/certs/fbu.edu.tr.crt` ve `/etc/nginx/certs/fbu.edu.tr.key`.
- Tasarımda yukarıdaki zorunlu tasarım ve hizalama kurallarını uygula. Sidebar, sayfa ve menüler alışılmış düzenlerden ayrılan fakat klavye, erişilebilirlik ve mobil kullanımını koruyan özgün bir görsel sisteme sahip olsun. Uygulama ikonu ve favicon aynı kimliği kullansın.
- Aktif keşif ve gerçek cihaz sorguları ancak kullanıcı tarafından tanımlanan yetkili kapsama ve açık tetiklemeye dayanır. Boş kurulumda uydurma cihaz, metrik veya başarılı yedek gösterme.

## Trafik izleme kaldırma kararı (1 Kasım 2026)

Trafik izleme kalıcı olarak kaldırıldı. Port/VLAN trafik ölçümü, izleme ekranları, butonlar, API uçları, sayaç toplama işleri ve trafik geçmişi yeniden eklenmez. Port/VLAN envanteri, IPAM, keşif/topoloji ve konfigürasyon yönetimi devam eder. Bu kaldırma işleminde yedek alınmaz.
