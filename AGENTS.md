# NETRIX

## Network Intelligence, Discovery & Management Platform

**Türkçe adı:** Akıllı Ağ Keşif ve Yönetim Platformu

**Kısa adı ve uygulama kimliği:** NETRIX

## Amaç ve kapsam

NETRIX, sıfırdan geliştirilecek, proje sahibine ait, web tabanlı ve merkezi bir ağ keşif, IP adres yönetimi, konfigürasyon yönetimi ve trafik izleme platformudur. Mimari modüler monolittir; üç modül ortak cihaz envanterini ve merkezi kimlik doğrulamayı kullanır.

### 1. IPAM & Network Discovery

- Subnet, VLAN ve IPv4/IPv6 adres yönetimi; otomatik IP ve cihaz keşfi.
- IP, MAC, hostname ve VLAN eşleştirme; cihazların bağlı olduğu switch ve fiziksel portun tespiti.
- LLDP/CDP ile üst ve alt switch ilişkilerinin keşfi ve otomatik ağ topolojisi.
- IP ve bağlantı değişikliklerinin geçmişi ve takibi.

### 2. Configuration Management

- Switch, router ve firewall cihazlarına SSH, SNMP ve REST API üzerinden erişim.
- Cihaz yeteneklerine göre SSH/API ile otomatik ve zamanlanmış konfigürasyon yedekleme; SNMP ile desteklenen envanter ve durum bilgilerini toplama.
- Konfigürasyon sürüm geçmişi, satır bazında karşılaştırma, değişiklik tespiti ve otomatik uyarılar.

### 3. Network Monitoring

- SNMPv3 ve API üzerinden cihaz izleme.
- Portların giriş/çıkış trafik hızları, Mbps/Gbps hesapları, port durumları, hata ve paket düşme istatistikleri.
- Geçmiş trafik kayıtları, canlı grafiklere veri sağlayan API ve WebSocket bildirimleri.
- Özelleştirilebilir alarm eşikleri.

## Teknik kararlar

| Katman | Tercih |
| --- | --- |
| Backend | Python / FastAPI |
| Kalıcı veri | PostgreSQL; zaman serileri için TimescaleDB |
| Görev altyapısı | Redis destekli kuyruk ve zamanlayıcı |
| Veri toplama | NETRIX için Python ile geliştirilen worker servisleri |
| Protokoller | SNMPv3, SSH, REST API; komşuluk verisi için LLDP/CDP |
| Canlı bildirim | WebSocket |
| Dağıtım | Docker Compose |
| Mimari | Modüler monolit, merkezi envanter, ayrı worker süreçleri |

## Geliştirme kuralları

1. NetBox, Oxidized, LibreNMS, Zabbix gibi hazır network yönetim ürünlerini uygulamanın temeli veya modül motoru olarak kullanma. IPAM, keşif, konfigürasyon karşılaştırma, monitoring ve alarm motorlarını NETRIX için geliştir.
2. Açık kaynak geliştirme kütüphaneleri ve altyapı bileşenleri kullanılabilir. Lisanslarını değerlendir ve bağımlılıkları proje dosyalarında kaydet.
3. Proje kimliği, servis adlandırmaları ve API dokümantasyonunda NETRIX kullan; teknik tanımlayıcılarda `netrix`, Compose servislerinde `netrix-*`, API başlığında `NETRIX API` kullan. API başlangıç yolu `/api/v1` olsun.
4. Modüller cihaz, arayüz, adres ve kullanıcı verilerini merkezi model üzerinden paylaşsın. Aynı cihaz için modül başına ayrı envanter oluşturma.
5. Cihaz erişim bilgilerini uygulama katmanında şifrele; anahtarları veritabanından ayrı, ortam veya secret dosyalarından al. Parola, anahtar, token ve SNMP sırlarını loglara, API yanıtlarına veya Git'e yazma. Kullanıcı parolalarını geri döndürülebilir şifreleme yerine güçlü parola özetiyle sakla.
6. Üretici ayrıntılarını yetenek tabanlı adaptörlerde tut. İş kurallarını FastAPI route'larından ve protokol istemcilerinden ayır; modüller arasında açık servis arayüzleri kullan.
7. Öncelik backend, API, veritabanı ve cihaz bağlantı motorlarıdır. Arayüzü proje sahibinin yönlendirmeleriyle, aşağıdaki Codex dışı tasarım becerilerini kullanarak tasarla. Tasarım yetkisi verilmiştir; ilk backend aşamasının kapsamını koru.
8. Ağ işlemlerini worker'da yürüt; API isteklerini uzun taramalarla bloke etme. Timeout, sınırlı eşzamanlılık, kontrollü yeniden deneme, iptal ve yinelenen görevleri güvenli işleme davranışını tanımla.
9. Keşif yalnızca yapılandırılmış ve yetkilendirilmiş ağ kapsamlarında çalışsın. Aktif taramayı kullanıcı veya zamanlama tetiklesin; testler varsayılan olarak gerçek ağa erişmesin.
10. Envanterdeki yönetilen değerleri keşif gözlemlerinden ayır. Belirsiz cihaz/port eşleşmelerini kanıt ve güven düzeyiyle sakla; bunları kesin ilişki gibi sunma.
11. Şema değişikliklerini Alembic migration ile sürümle. Zamanları UTC ve zaman dilimli sakla; kullanıcıya gösterirken yerel saate dönüştür.
12. Uygulanan davranışı hedefli testlerle doğrula. Protokoller için sahte istemciler, PostgreSQL kısıtları için entegrasyon testleri kullan; çalıştırılmamış kontrolleri başarılı olarak raporlama.

## Göreve göre okunacak belgeler

- Veri modeli, migration, envanter, keşif, konfigürasyon veya monitoring işi yaparken [kapsamlı veri modelini](docs/data-model.md) oku. Bu belge hedef tasarımdır; tabloların uygulanmış olduğunu varsayma.
- Altyapı kurulumu ve ilk sürüm geliştirmesinde [sıralı geliştirme planını](docs/development-plan.md) izle. Her adımı kabul ölçütleriyle doğrula; yalnızca mevcut isteğin kapsadığı adımları uygula.

## Beceriler ve MCP araçları

Proje sahibi, NETRIX için Codex dışı becerilerin ve MCP sunucularının kullanımını yetkilendirmiştir. Göreve uygun araçları seç; tüm araçları her görevde çalıştırma. Burada "Codex dışı", Codex'in yerleşik sistem becerileri yerine oturumda sunulan harici beceri paketlerini ifade eder. Bu beceriler Codex içinden kullanılabilir.

### Kullanılacak harici beceriler

Beceriyi uygulamadan önce oturumdaki beceri kataloğundan ilgili `SKILL.md` dosyasını bul ve oku. Yerel kurulum yollarını bu public depoya sabitleme; eksik beceriyi varmış gibi kullanma.

| Görev | Beceri | NETRIX'teki kullanım |
| --- | --- | --- |
| Ürün arayüzü ve etkileşim tasarımı | `impeccable` | Operasyon ekranları, bilgi hiyerarşisi, boş/hata/yüklenme durumları ve tasarım incelemesi |
| UX ve erişilebilirlik | `ui-ux-pro-max` | Envanter tabloları, IPAM formları, topoloji ve trafik ekranlarında kullanılabilirlik |
| Görsel sistem | `design-system` | Renk, tipografi, boşluk ve durum token'ları; ortak bileşen kuralları |
| Arayüz uygulaması | `frontend-design`, `ui-styling` | Özgün NETRIX arayüzü; frontend teknolojisi seçildikten sonra uygun bileşen ve stiller |
| Marka ve görsel kimlik | `brand`, `design` | NETRIX marka dili, ikon ve görsel kimlik; ihtiyaç halinde |
| PostgreSQL şeması ve performans | `postgresql-table-design`, `sql-optimization-patterns` | IPAM ilişkileri, kısıtlar, indeksler ve sorgu planları |
| Şema sürümleme | `database-migration` | Alembic değişiklikleri ve veri dönüşümleri |
| Kimlik ve sır yönetimi | `auth-implementation-patterns`, `secrets-management` | Merkezi yetkilendirme, cihaz erişim bilgileri ve anahtar yönetimi |
| Python doğrulaması | `python-testing-patterns` | Worker, API ve protokol adaptörü testleri |
| Tarayıcı doğrulaması | `webapp-testing`, `web-design-guidelines` | Arayüz hazır olduğunda gerçek tarayıcı ve erişilebilirlik kontrolleri |
| CI | `github-actions-templates` | Backend ve migration kontrollerinin GitHub Actions'a taşınması |
| Teşhis ve teslim | `systematic-debugging`, `verification-before-completion` | Hata kök nedeni ve kanıta dayalı teslim kontrolü |
| Ajan yönergeleri | `writing-for-agents` | Bu dosyanın ve görev yönergelerinin bakımı |

Tasarımda `impeccable` ana iş akışıdır; diğer tasarım becerilerini ilgili alt ihtiyaç için kullan. Aynı ekranı farklı becerilerle tekrar tekrar tasarlama. Backend geliştirmesinde tasarım becerilerini gereksiz yere devreye alma.

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

## İlk geliştirme aşamasının sınırı

İlk çalışan dilim: Docker Compose, FastAPI, PostgreSQL/TimescaleDB, Redis, worker ve zamanlayıcı altyapısı, merkezi kimlik doğrulama ve cihaz envanteri, temel IPAM ve keşif motoru. Konfigürasyon yönetimi ve monitoring için veri modeli hazırlanır; tam motorları sonraki aşamalarda geliştirilir.

Bu depoda başlangıçta yalnızca planlama belgeleri bulunabilir. Önce mevcut dosyaları incele; henüz oluşturulmamış servisleri, komutları veya testleri varmış gibi anlatma.
