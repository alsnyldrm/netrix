# NETRIX doğrulama kaydı — 29 Ekim 2026

## FortiGate SSH/SCP yedeği ve SSH zorunluluğu (30 Ekim 2026)

- Üretim veritabanındaki son FortiGate kaydı yalnızca 962 byte, başlıksız ve `--More--` içeriyordu. Ham içerik/sırlar araç çıktısına alınmadan kontrol edildi. Kök neden `show full-configuration` ekran çıktısının sayfalama bitmeden başarılı yedek sayılmasıydı.
- FortiGate artık mevcut SSH bağlantısı üzerinden SCP `sys_config` dosyasını indirir. SSH profili API ve worker'da zorunlu; REST/SNMP yedek kaynağı veya alternatif değildir. Eski kuyruk işleri de worker'da yeniden doğrulanır. Aktif config karşılaştırması aynı dosyayı kullanır; geçersiz eski FortiGate kaydıyla karşılaştırma başlamaz.
- `pytest -q`: SNMPv2c ve CSV değişiklikleriyle birleştirme sonrasında 180 geçti; mevcut Starlette/httpx deprecation uyarısı sürüyor. Tam dosyanın şifreli saklanması, maskelenmiş yanıt/diff, REST/SNMPv3/SNMPv2c yedek reddi, eski işler, bağlantı değişimi, kesilmiş/sayfalanmış çıktı, boyut sınırı, hata ve iptalde geçici dosya temizliği doğrulandı.
- `scripts/ssh_trust_check.py`: gerçek SSH/SCP protokolüyle yalnızca yerel loopback sunucusunda sys_config transferi geçti. Yetki reddi, kesilmiş transfer ve CLI sayfası reddedildi; bilinmeyen host anahtarı, açık güven seçimi, kayıtlı anahtar ve parola kontrolleri geçti.
- `scripts/backup_devices_browser_check.py`: iki yedek ekranının cihaz listesi/ayrıntıları 1440 px açık ve 375 px koyu görünümde hizalama, taşma ve axe WCAG A/AA kontrollerini geçti. Görüntüler incelendi; JavaScript hatası yok. TypeScript/Vite, Ruff, Prettier ve `git diff --check` geçti.
- Şema ve bağımlılık değişmedi. Gerçek FortiGate'e yeni ağ sorgusu veya ayar değişikliği yapılmadı; eski yedekler silinmedi. Cihazda SSH, admin-scp ve sürüme uygun yönetici yetkisi gerekir. [Resmi kaynaklar ve kapsam sınırları](fortigate-ssh-backup.md).

## Cihaz bazlı yedek gezinme (30 Ekim 2026)

- Cihaz Yedekleri ve Karşılaştır ana ekranları yedek sayısı/son yedek zamanı içeren cihaz listesine dönüştürüldü. Cihaz seçilmeden yedek listesi istenmez; ayrıntı sorguları cihaz kimliğiyle sınırlandırılır.
- Envanter/yedek backend testleri: 15 geçti. Aynı adlı cihazlar, arşivlenmiş cihaz geçmişi, yedeği olmayan cihazın dışlanması, cihaz sayfalaması, sayısal filtre ve 25 kaydı aşan yedek geçmişinde cihaz sınırı doğrulandı. Yeni migration veya bağımlılık yok.
- `scripts/backup_devices_browser_check.py`: iki sayfada cihaz listesi/cihaz geçmişi, geri dönüş, arama, klavye odağı, yalnızca cihaza ait yedek istekleri ve sahte aktif config sonucu geçti. 1440 px açık / 375 px koyu görünümde hizalama, yatay taşma ve axe WCAG A/AA kontrolleri geçti; JavaScript hatası yok. Ekran görüntüleri görsel olarak incelendi. Gerçek cihaz sorgusu çalıştırılmadı.
- TypeScript/Vite derlemesi, Ruff ve `git diff --check` geçti.

## Form satır hizalaması düzeltmesi (30 Ekim 2026)

- Önceki checkbox kontrolü yalnızca kutu/metin iç hizasını ölçüyordu; komşu girişlerle satır hizasını kapsamıyordu. Ortak kaynak formu başlık, kontrol ve açıklama için paylaşılan grid satırlarına geçirildi. Checkbox kontrolleri girişlerle aynı yükseklik ve genişlikte; açıklamalar alanın sol kenarından başlıyor.
- `scripts/ssh_trust_browser_check.py` artık yan yana alanların başlık/kontrol üst kenarlarını ve yüksekliklerini, açıklama başlangıçlarını ve sütun genişliklerini ölçüyor. Cihaz ve diğer dokuz kaynak formu masaüstü/mobil ölçümlerini geçti. Cihaz formunda dört tema/ekran kombinasyonu, kayıt kalıcılığı, klavye kullanımı, yatay taşma ve axe WCAG A/AA kontrolleri geçti; JavaScript hatası yok.
- Cihaz formunun masaüstü ve mobil ekran görüntüleri görsel olarak incelendi. TypeScript/Vite, Prettier, Ruff ve `git diff --check` geçti. Backend veya veritabanı şeması değişmedi.

## Cihaz bazında SSH anahtar güveni (30 Ekim 2026)

- `pytest -q`: 109 test geçti. Anahtar güven tercihi kapalı/açıkken test, kimlik okuma ve yedekleme; API kaydetme/yeniden okuma; worker'a aktarım ve test sırasında tercih değişince eski sonucun reddi doğrulandı. Mevcut Starlette/httpx deprecation uyarısı devam ediyor.
- `scripts/ssh_trust_check.py`: yalnızca geçici loopback SSH sunucusuyla gerçek bağlantı kuruldu. Bilinmeyen anahtar varsayılan durumda reddedildi; açık güven tercihiyle üç işlem geçti; yanlış parola reddedildi; özel porttaki kayıtlı anahtar normal doğrulamayla kabul edildi. Gerçek ağ cihazları bu kontrolde sorgulanmadı.
- `scripts/ssh_trust_browser_check.py`: ekleme/düzenleme, REST'te gizleme, kapalı varsayılan, iki yönde kaydetme, klavye kullanımı ve checkbox/metin/yardım yazısı hizalaması geçti. Açık/koyu masaüstü, 375 px mobil ve 812 px yatay görünümde axe WCAG A/AA ihlali ve JavaScript hatası yok. Bağlantı testi penceresi ve arka plan yenileme regresyonları da geçti.
- Alembic `20261030_04`, izole MariaDB 11.8.3 `netrix_test` ortamında veri içeren tabloda downgrade → upgrade → schema check turunu geçti; mevcut bilgiler, kapalı varsayılan ve tercihin kalıcılığı doğrulandı. MariaDB kısıt/UTC/kilit entegrasyon kontrolleri geçti; geçici DB ve ağ kaldırıldı.
- Ruff, Prettier, TypeScript/Vite ve `git diff --check` kontrolleri geçti. Üretim geçişi öncesinde `/opt/netrix/backups/before-ssh-trust-20261030.sql` yedeği alındı (0600, boş değil).

Bu kayıt çalıştırılan kontrolleri ve kapsam sınırlarını ayırır. Gerçek ağ cihazlarında SNMP/SSH/REST toplama testi yapılmadı; verilen DB/Docker/Nginx altyapı bağlantıları test edildi.

## Cihaz satırından SNMP/SSH/API testi (30 Ekim 2026)

- Envanter satırına Test düğmesi ve protokol seçimi/sonuç penceresi eklendi. Gerçek protokol çağrıları worker'da yapılır; API profilleri sunucudan okuyup yalnızca atanmış seçenekleri etkinleştirir. Seçilmeyen protokol denenmez. Profil/kapsam/yetki doğrulaması arayüzle sınırlı değildir.
- `pytest -q`: 104 test geçti; mevcut Starlette/httpx uyarısı devam ediyor. Sahte istemcilerle protokol ve kayıtlı sırların doğru seçimi, SNMP GET/noSuchObject, transport kapanışı, SSH doğrulaması ve komut çalıştırılmaması, API HTTPS/JSON/yanıt sınırı/yönlendirme yasağı, hata/zaman aşımı, tekrar teslim, aktif iş tekilliği, iptal, bağlantı değişimi, kapsam ve viewer sınırları doğrulandı. Cihaz envanteri ve gözlemler test sonucuyla değiştirilmedi.
- TypeScript/Vite, Prettier, Ruff, `git diff --check`, mevcut 20 ekran/4 boyut tarayıcı akışı ve arka plan yenileme regresyonu geçti.
- `scripts/connection_test_browser_check.py`: yerel sahte API yanıtlarıyla SNMP+SSH/API profil matrisi, yalnızca seçilen protokolün gönderilmesi, kuyruğa alma/çalıştırma, başarı/hata/iptal ve odak iadesi geçti. Açık/koyu 1440 px, koyu 375 px ve açık 812 px yatay görünümde yeni pencerenin axe-core WCAG A/AA kontrolü ihlalsiz; JavaScript hatası yok.
- Şema değişmedi; migration eklenmedi. Gerçek ağ cihazında bağlantı testi otomatik doğrulama sırasında tetiklenmedi; gerçek sorgu kullanıcı Test et düğmesine bastığında çalışır.

## Otomatik üretici, model ve cihaz türü (30 Ekim 2026)

- Cihaz kaydı/değişikliğiyle atomik `identify` işi, SNMPv3 → SSH/API tamamlama, alan başına güncelleme, bilinmeyen/boş sonuçlarda manuel değerleri koruma, kaynak/gözlem ve değişiklik geçmişi uygulandı. Kapsam/profil yokluğunda cihaz kaydı korunuyor ve sorgu başlatılmıyor. Mevcut cihazlar dağıtım sırasında topluca sorgulanmıyor.
- `pytest -q`: 81 test geçti; mevcut Starlette/httpx deprecation uyarısı devam ediyor. Sahte cihaz yanıtlarıyla SNMP şasi/SFP ayrımı, belirsiz modeller, IOS/Junos/FortiOS/Linux/REST ayrıştırma, protokol tamamlama, timeout/yeniden deneme, iptal, tekrar teslim, sorgu sırasında bağlantı değişimi, sırların yanıtlardan uzak tutulması ve manuel alanların korunması doğrulandı. SSH host anahtarı ve HTTPS doğrulaması, yönlendirme yasağı, IPv6/özel port ve 256 KiB yanıt sınırı kontrol edildi.
- Atılabilir MariaDB 11.8.3 / `netrix_test` üzerinde Alembic upgrade → downgrade → upgrade ve şema kontrolü geçti. Yeni migration ayrıca veri içeren tabloda geri/ileri çalıştırıldı; mevcut üretici/model/tür değerleri ve yeni REST bilgi yolu varsayılanı doğrulandı. MariaDB kısıt/UTC/kilit entegrasyon kontrolleri geçti; test container'ı ve izole ağı kaldırıldı.
- TypeScript/Vite, Prettier, Ruff, `git diff --check`, 20 ekran/4 boyut tarayıcı kontrolü, arka plan yenileme regresyonu ve mevcut beş ekranlık axe-core taraması geçti. Tarayıcıda REST bilgi yolu, manuel alanlar, yeniden sorgulama düğmesi ve açık cihaz ayrıntılarının gelen verilerle güncellenmesi yerel fixture/sahte yanıtlarla doğrulandı.
- Üretim migration'ından önce `/opt/netrix/backups/before-identity-20261030.sql` yedeği alındı; dosya boş değil ve izinleri 0600. Gerçek ağ cihazlarında yeni kimlik komutları çalıştırılmadı; üretici/firmware uyumluluğu bu testlerle kanıtlanmış sayılmaz.

## Veri girişinde pencerenin kapanması (30 Ekim 2026)

- Ortak diyalog bileşeninde dış alana tıklayarak kapatma kaldırıldı; açık kapatma düğmeleri ve Escape kullanılmaya devam ediyor.
- `scripts/browser_check.py` cihaz adı, üretici ve model alanlarında çift tıklama, metin seçimini pencere dışına sürükleme, dış alana tıklama ve girilen değerlerin korunmasını doğruluyor. Dış alan tıklaması kontrolü düzeltme öncesinde başarısız, düzeltme sonrasında başarılı oldu. Kaydetme, kapatma, Vazgeç, Escape ve odağın geri verilmesi de kontrol edildi.
- TypeScript/Vite üretim derlemesi, Prettier, Ruff, 20 ekran/4 boyut tarayıcı akışı ve arka plan yenileme regresyonu geçti. Testler yerel fixture/sahte protokollerle çalıştı; gerçek ağ cihazı sorgulanmadı.

## Arka plan yenileme düzeltmesi (30 Ekim 2026)

- Canlı bildirim ve periyodik yenileme, aynı sorgunun tablosunu veya trafik grafiğini yükleme alanıyla değiştirmiyor. İlk sorguda ve filtre/arayüz/zaman aralığı değişiminde yükleme durumu korunuyor.
- `scripts/refresh_check.py`, yerel üretim derlemesinde sahte API/WebSocket ve geciktirilmiş yanıtlarla hatayı düzeltme öncesinde yeniden üretti; düzeltme sonrasında geçti. Tablo/grafik DOM sürekliliği, klavye odağı, güncel verinin uygulanması, 30 saniyelik periyodik yenileme, boş sonuçlar ve hata sonrası toparlanma doğrulandı. Gerçek cihazlara erişilmedi.
- TypeScript/Vite derlemesi, Prettier, Ruff, `git diff --check`, 20 ekran/4 boyut tarayıcı akışı ve 53 backend testi geçti. Backend testlerinde mevcut Starlette/httpx deprecation uyarısı var.

## Otomatik kontroller

| Kontrol | Sonuç / kapsam |
| --- | --- |
| `pytest -q` | 53 test geçti. Tek container başlangıcı, migration hatası/iptali, tüm süreçleri kapsayan healthcheck ve container içi yedekleme istemcisi dahil. Rol sınırları, ilk kurulum, oturum iptali, sır maskeleme/şifreleme, IPAM, VLAN, IPv6, /31-/32, görev tekrarı/iptali/kurtarma, kısmi keşif, sayaç reset/gap, alarm histerezisi ve konfigürasyon diff. |
| Protokol testleri | Sahte SNMP GET/WALK ve SSH istemcileri; sayısal MIB ayrıştırma, host key kontrolü, ARP/NDP/FDB belirsizliği. Varsayılan test fixture'ı gerçek IP soket bağlantılarını engeller. |
| `ruff check backend tests scripts` | Geçti. |
| `git diff --check` | Geçti. |
| TypeScript + Vite üretim derlemesi | Geçti. |
| Üretim Python bağımlılık kontrolü | Container içinde `pip check`: broken requirement yok. |
| Sır taraması | Git'in takip ettiği ve ignore edilmeyen kaynaklarda gerçek DB parolası, şifreleme anahtarı veya kurulum token'ı bulunmadı. |

Pytest'te Starlette test istemcisinin httpx kullanımına ilişkin bir upstream deprecation uyarısı var; test hatası yoktur.

## MariaDB ve altyapı

Atılabilir MariaDB 11.8.3 ortamında migration upgrade → downgrade → upgrade ve Alembic şema kontrolü çalıştırıldı. FK/CHECK/UNIQUE kısıtları, `DATETIME(6)` UTC/mikrosaniye, `DECIMAL(20,0)` unsigned 64 bit sayaç, iki eşzamanlı VRF ataması ve `SKIP LOCKED` iş alımı doğrulandı. İlk teslimdeki yedekleme aracı aynı atılabilir DB'de yedekleme/geri yükleme turunu geçti; tek container için güncellenen aracın kontrolleri aşağıda ayrıca kaydedildi. Üretim DB'sinde test verisi veya geri yükleme uygulanmadı.

Üretim bağlantısı yalnızca `10.2.0.31:3306` VIP'si üzerinden; MariaDB 11.8.9 kullanılıyor. İlk bağlantı, VIP NAT zinciri ve user-host eşleşmesi nedeniyle 1045 döndürdü. DB bakım sohbetinde kullanıcının izniyle hesap host kısıtı değiştirildikten sonra VIP bağlantısı doğrulandı. NETRIX uygulama hedefi değiştirilmedi. DB/HAProxy global yapılandırması bu uygulama çalışmasında değiştirilmedi.

Galera için VRF sürüm yazması ve uygulama oturumuna özgü causal read bariyeri eklendi. Çok düğümlü eşzamanlı sertifikasyon çakışması testi yapılmadı; tek MariaDB üzerindeki transaction/kısıt ve schema testleri bu testi ikame etmez.

Compose servislerinin healthcheck'leri, worker/zamanlayıcı heartbeat'leri, migration çıkış kodu ve loopback `8101` readiness kontrol edildi. Redis AOF kalıcı volume ile yapılandırıldı; geçici bir doğrulama anahtarı yazılıp Redis yeniden başlatıldı, aynı anahtar okunarak kalıcılık doğrulandı ve ardından anahtar silindi. Uygulama yeniden oluşturulurken DB şeması/kurulum durumu korundu.

## Arayüz ve yayın

Gerçek MariaDB + Redis kullanan atılabilir Docker kurulumunda tarayıcı testleri: ilk kurulum/giriş, cihaz kaydı, ayrıntı penceresi, Ctrl/⌘ K araması, Escape ve çıkış. 20 ekran; 375×812, 812×375, 768×1024 ve 1440×900 boyutlarında kontrol edilir; sayfa düzeyinde yatay taşma ve JavaScript hatası yoktur. Gerçek Redis üzerinden yetkili WebSocket bağlantısı doğrulandı.

Axe-core ile panoramada, envanterde, keşifte, monitoring ve ayarlarda WCAG A/AA etiketlerine göre otomatik tarama yapıldı; son taramada ihlal yok. Bu, bütün erişilebilirlik ölçütlerinin manuel denetlendiği anlamına gelmez.

Host Nginx yapılandırması `nginx -t` geçti ve reload edildi. HTTP 301 → HTTPS, `443 → 127.0.0.1:8101`, API readiness HTTP 200 doğrulandı. Test istemcisi mevcut kurum sertifika zincirini açıkça güvenilir kabul ederek TLS doğruladı. Üretim arayüzü normal DNS çözümüyle, bilinen sertifika anahtarı pinlenerek ve salt okunur isteklerle tarayıcıda açıldı; admin hesabı veya cihaz görevi oluşturulmadı.

İlk testlerde DNS kaydı yoktu; sonraki sunucu sorgusunda `netrix.fbu.edu.tr → 10.2.0.87` A kaydı çözülür hale geldi. DNS yönetimi bu uygulama çalışmasında yapılmadı. İlk TLS/tarayıcı testi açık host eşlemesiyle yapıldı. Son normal DNS kontrolünde hem geliştirme ortamından hem Docker sunucusundan HTTPS readiness HTTP 200 döndü.

## Tek container stack güncellemesi

Proje sahibinin son dağıtım talebi uygulandı: `netrix` adlı Docker Compose stack, `netrix-app` adlı tek servis ve `netrix` adlı tek container içerir. Sunucu standalone Docker kullanır; Swarm kapalıdır. Container imajı `netrix:1.1.0`, doğrulanan imaj kimliği `sha256:fa5be9d554c12615053870864fe1473cfc0a85b04abe57656ca75ab61ff94111`.

- `docker compose config --services` yalnızca `netrix-app` döndürdü. Proje etiketiyle çalışan ve durmuş container'ların tamamı sayıldı: yalnızca `netrix` var. Eski migration/API/Redis/worker/zamanlayıcı container'ları ve geçici deneme container'ları kaldırıldı.
- Dört süreç (`netrix-api`, `netrix-redis`, `netrix-worker`, `netrix-scheduler`) aynı container'da Supervisor tarafından RUNNING durumunda yönetiliyor. Redis 8.2.2; MariaDB istemcisi Debian `1:10.11.19-0+deb12u1`.
- `scripts/container_check.py` üretimden ayrı SQLite/anonim volume ve `--network none` ile çalıştırıldı. Temiz migration ve başlangıç; worker SIGKILL sonrasında yeni PID ile toparlanma; worker durdurulduğunda Docker unhealthy ve yeniden başlatıldığında sağlığa dönüş; container yeniden başlatmasında Redis AOF kalıcılığı; düzgün SIGTERM kapanışı ve migration hatasında servislerin başlamadan hata koduyla çıkması geçti. İlk denemede bulunan yapılandırma dosyası sahipliği sorunu düzeltildikten sonra bütün akış tekrar çalıştırıldı ve geçti.
- Üretim geçişinden önce `.env`, Compose ve kapalı Redis volume'u `/opt/netrix/backups/before-single-20261029T190145Z` altında korumalı olarak yedeklendi. Eski volume korunarak UID/GID 10001'e atandı. Mevcut Redis'e yazılan geçici doğrulama anahtarı hem geçişten hem üretimde bütün container yeniden başlatmasından sonra okundu; ardından silindi.
- Container UID 10001 ile, salt okunur kök dosya sistemi ve yalnızca `127.0.0.1:8101` port yayınıyla çalışıyor. Redis aynı container'ın loopback adresinde. DB hedefi VIP `10.2.0.31/netrix`; şifreleme anahtarı, kurulum token'ı ve DB ayarlarının korumalı önceki ortam dosyasıyla aynı olduğu içerikleri yazdırılmadan doğrulandı.
- Güncellenen `scripts/backup.py` mevcut container'ın MariaDB istemcisini kullanarak üretim yedeği aldı: `/opt/netrix/backups/netrix-after-single-20261029.sql`, izin 0600 ve dosya boş değil. Ek yardımcı container oluşturulmadı. Yeni geri yükleme istemcisinin onay kontrolü, argv içinde sır bulunmaması ve özel client dosyasının temizlenmesi birim testlerinde doğrulandı; güncellenmiş araçla canlı geri yükleme uygulanmadı.
- Üretimde container yeniden başlatıldıktan sonra Docker healthcheck ve dört süreç sağlıklı. HTTPS readiness mevcut kurum sertifika zinciriyle doğrulandı. Normal DNS ve mevcut sertifika anahtarıyla salt okunur Playwright kontrolü HTTP 200, giriş/kurulum ekranı, favicon, DB/Redis sağlığı ve JavaScript hata bulunmaması kontrollerini geçti. İlk yönetici oluşturulmadı; yetkili ağ kapsamı veya gerçek tarama eklenmedi.
- Güncel `pytest -q`: 53 geçti; `ruff check backend tests scripts` ve `git diff --check` geçti. Yeni imaj frontend üretim derlemesini de içerir; container içinde `pip check` kırık bağımlılık bulmadı.

## Arayüz yeniden tasarımı (29 Ekim 2026)

Arayüz UI UX Pro Max ile baştan yenilendi: Teknik kobalt renk sistemi (açık + koyu tema), IBM Plex Sans/Mono (self-hosted), gruplu tek sidebar (daraltılabilir, mobilde çekmece), yeni giriş ekranı, sayfa geçişleri ve yeni favicon/uygulama simgesi. Ayrıntılar `design-system/netrix/MASTER.md` içindedir.

- TypeScript + Vite üretim derlemesi ve Prettier kontrolü geçti.
- `scripts/browser_check.py` yerel atılabilir fixture'da geçti: 20 ekran, 4 boyut, yatay taşma yok, JavaScript hatası yok; mobil çekmece, tema anahtarı ve daraltılmış sidebar akışları eklendi.
- `scripts/accessibility_check.py` (axe-core, WCAG A/AA) açık temada ve aynı betiğin koyu tema varyantıyla ihlalsiz geçti. Metin token'ları üç yüzey renginde de en az 4.5:1 kontrast verir.
- `pytest -q` Windows geliştirme ortamında çalıştırıldı: 52 geçti, 1 başarısız (`test_backup_uses_private_client_file_without_secret_arguments`, POSIX 0600 dosya izni Windows'ta uygulanamaz). Asyncio'nun Windows'taki loopback socketpair'i ağ korumasına takıldığı için yalnızca socketpair'i saran yerel bir test eklentisi kullanıldı; backend değişmedi. Linux container'da yeniden çalıştırılmadı.
- `ruff check backend tests scripts` ve `git diff --check` geçti. Bu değişiklik deploy edilmedi.

## Envanter ve yedek yönetimi doğrulaması (30 Ekim 2026)

- Linux yerel Python ortamında tam test takımı: **123 geçti**. Son Türkçe filtre genişletmesinden sonra ilgili 14 envanter/yedek testi tekrar geçti. Gerçek ağ erişimi test fixture'ı tarafından engellenir. Arama/sayfalama/VE-VEYA, cihaz kapsamlı seçim, sadece seçili-etkin portlarda örnek kaydı, atomik toplu güncelleme, rol sınırları, eski yedeklerin korunması, grup zamanlaması/tekrarsız kuyruk, saklama ve çalışan karşılaştırmanın korunması kapsanır. Canlı karşılaştırmada protokol okuması sahte istemciyle doğrulanır; gerçek cihaz uyumluluğu testi değildir.
- `scripts/inventory_browser_check.py`: geçici yerel SQLite ve gerçek API üzerinde 35 cihazla arama, sütun seçimi, toplu düzenleme, port seçimi/devre dışı bırakma, filtre, yedek görüntüleme/değişenler, kapsam reddi ve grup oluşturma geçti. Yedi ekran ve dört pencere 1440/375 pikselde axe WCAG A/AA ihlali ve JavaScript hatası olmadan geçti; taşma ve filtre kontrol hizaları ölçüldü, ekran görüntüleri incelendi.
- Önceki regresyonlar: `scripts/refresh_check.py`, `scripts/connection_test_browser_check.py`, `scripts/ssh_trust_browser_check.py` geçti. WebSocket/polling sırasında tablo ve odak korunması, protokol profil kapıları, hata/başarı/iptal, SSH güven seçimi ve ortak form hizaları doğrulandı.
- Üretimden ayrı, Docker `--internal` ağındaki atılabilir MariaDB 11.8.3 üzerinde veri içeren `04 → 05 → 04 → 05` geçişi, Alembic schema eşitliği, önceki cihaz/SSH tercihinin ve portların korunması, ilişkili alan/kapasite araması ve etkin grup politikası geçti. Mevcut `mariadb_check.py` FK/CHECK/UNIQUE, UTC, uint64, eşzamanlı VRF kilidi ve SKIP LOCKED kontrolleri de geçti. Deneme DB/container/ağ kaldırıldı; üretim verisi bu testlere alınmadı.
- TypeScript/Vite üretim derlemesi, Ruff, Prettier ve diff boşluk denetimi geçti. Üretim geçişi öncesinde `/opt/netrix/backups/before-inventory-backups-20261030.sql` yedeği alındı; izin 0600 ve boş olmadığı doğrulandı. Kimlik bilgileri veya yedek içerikleri çıktıya yazdırılmadı.

## SNMPv2c erişim kasası — 30 Ekim 2026

- `pytest -q`: 133 test geçti; gerçek ağ bağlantıları test fixture'ı tarafından engellendi. Community doğrulama, şifreleme, değiştirme, API/audit maskeleme; v2c GET/walk/probe, keşif, izleme, kimlik kaynağı ve ayrı bağlantı testi görevi doğrulandı.
- `npm --prefix frontend run build`, `ruff check backend tests scripts`, değişen TSX dosyalarının Prettier kontrolü ve `git diff --check` geçti.
- `scripts/snmpv2c_browser_check.py`: yerel API ve atılabilir SQLite verisiyle kasa oluşturma/güncelleme, protokole göre alanlar, gizlenen sırların gönderilmemesi, cihaz/kapsam profili seçimi geçti. 1440px masaüstü, 375px mobil ve 812px yatay görünüm; açık/koyu tema; klavye, alan hizaları ve taşma kontrol edildi. Kasa ve dört protokollü bağlantı testi penceresinde axe WCAG A/AA ihlali yok.
- Atılabilir MariaDB 11.8.3 `netrix_test`: `scripts/snmpv2c_migration_check.py` ile eski kısıt, upgrade, mevcut şifreli verinin korunması, yeni kısıt, v2c profilleri varken veri silmeyen downgrade engeli, downgrade/upgrade ve Alembic schema kontrolü geçti. `scripts/mariadb_check.py` UTC, FK/CHECK/UNIQUE, uint64 ve eşzamanlılık kontrolleri geçti.
- Bu kontroller üretim cihazına sorgu veya tarama göndermedi. Yayın sonrası sağlık kontrolü ayrıca yapılır.

## CSV / XLSX aktarımı ve aktarım sonrası bağlantı testleri — 30 Ekim 2026

- Tam Python takımı: 193 test geçti. Son denetim kaydı biçim ayrımından sonra 36 CSV/XLSX testi tekrar çalıştırıldı. Zorunlu/isteğe bağlı şablon alanları, seyrek Excel satırları, seçili cihazların maskelemesi, formül/ZIP sınırları, atomik kayıt/kuyruk, kapsam ve rol kontrolleri doğrulanır. Gerçek ağ erişimi yasaktır; bağlantı sonucu testlerinde gerçek worker sahte protokol istemcisine bağlanır.
- `scripts/device_csv_browser_check.py`, `scripts.device_transfer_fixture` üzerinde her iki formatın dosya seçimi, indirme, önizleme, normal aktarma, aktarım + test, başarısız/başarılı/test edilemedi sonuçları ve mükerrer kayıt reddini doğrular. Masaüstü 1440px ve mobil 375px, açık/koyu tema toplam 20 axe kontrolünde ihlal/JavaScript hatası yok. Başlık/özet kenarları ve alt düğme yükseklikleri ölçülür; ekran görüntüleri görsel incelenir. Klavye ile açılır menü gezinme/Escape ve mobilde test düğmesine erişim doğrulandı.
- TypeScript/Vite derlemesi, Ruff ve bağımlılık tutarlılığı kontrolü geçti. Şema değişikliği yok; mevcut görev kuyruğu ve erişim profilleri kullanılır. Yerel tarayıcı fixture'ı üretim modüllerince içe aktarılmaz ve gerçek cihaz bağlantısı açmaz.

## İçe aktarma zorunlu alanları ve Excel seçim listeleri — 30 Ekim 2026

- Tam Python takımı 277 test geçti. Son başlık uyumluluğu ve sütun fontu değişikliğinden sonra 85 CSV/XLSX/şablon testi tekrar geçti. Sekiz zorunlu alanın eksik sütun/boş hücre kontrolleri, Hayır seçiminin geçerliliği, Global VRF varsayılanı, açık VRF seçiminin korunması ve Global yoksa veri oluşturmadan hata doğrulandı.
- İndirilen XLSX dosyaları openpyxl ve OOXML üzerinden incelendi: bütün giriş sütunlarında 2–501. satırlar için listeler, görünür seçim oku, adlandırılmış aralıklar, protokol filtresi, güncel sistem kayıtları, aynı adlı lokasyonlar, 500'den fazla seçenek varken içe aktarma ve eski şablondaki silinmiş profilin reddi doğrulandı. Dosyada formül/Excel hatası/harici bağlantı yok; SQL yakalaması şifreli erişim bilgisi sütununun dahi okunmadığını doğruladı. Microsoft Excel masaüstü uygulaması bu ortamda çalıştırılmadı.
- TypeScript/Vite derlemesi, Ruff ve diff kontrolü geçti. Yerel tarayıcıda CSV/XLSX indirme, önizleme, aktarma ve sahte worker sonuçları; 1440px/375px ve açık/koyu temalarda 28 axe kontrolü geçti. Ekran boyutu değişiminden sonra tarayıcının odak kaydırması tamamlanıp ölçüldü; hizalama ve tablo içi yatay kaydırma görsel olarak kontrol edildi.
- Şema değişikliği yok. Kullanıcının açıklamasına göre zorunluluklar yalnızca içeri aktarmaya uygulandı; cihaz ekleme/düzenleme formunun kuralları değiştirilmedi.

## Cihaz arşivi ve geri yükleme — 30 Ekim 2026

- Envanter, CSV ve XLSX aktarımına ait 99 hedefli Python testi geçti. Arşiv görünümünün normal listeden ayrılması, arşivdeki mükerrer IP'nin açıklayıcı aktarım hatası, tekli/toplu geri yükleme, yönetici yetkisi, atomik hata davranışı, aynı kimlik/arayüz/yedek/profil/grup geçmişinin korunması ve yeni ağ görevi oluşmaması doğrulandı. Gerçek ağ bağlantıları test fixture'ı tarafından engellendi.
- `scripts/archive_browser_check.py` geçici yerel envanter fixture'ında gerçek API ile arşivleme, sidebar menüsü, arama, sütun seçimi, vazgeçme, tekli/toplu geri yükleme ve sayfa yenilemesi akışlarını doğruladı. 1440px/375px açık/koyu temada 16 axe WCAG A/AA kontrolü ihlalsiz geçti; JavaScript hatası ve sayfa yatay taşması yok. Araç çubuğu ve diyalog düğmelerinin hizaları ölçüldü; masaüstü/mobil ekran görüntüleri incelendi.
- TypeScript/Vite derlemesi, Ruff, Prettier ve diff boşluk kontrolü geçti. Şema değişikliği yok; geri yükleme Bakımda durumuyla yapılır ve ağ görevi başlatmaz. Üretimde cihaz kaydına müdahale edilmeden mevcut arşiv durumu salt okunur sorguyla doğrulandı.

## Yönetilebilir cihaz türleri — 30 Ekim 2026

- Tam Python test takımı: **290 geçti**. Tür ekleme/düzenleme/silme, ad tekilliği, rol sınırları, cihazlara atama/toplu değiştirme, yeni adla cihaz/arayüz araması ve filtreleme, arşiv dahil silme engeli, FK, audit, silinmiş gözlem türünde manuel değerin korunması, CSV/XLSX aktarımı ve güncel Excel seçenekleri doğrulandı. Testlerde gerçek ağ erişimi kapalıdır.
- `scripts/device_types_migration_check.py`, üretimden ayrı Docker `--internal` ağında atılabilir MariaDB 11.8.3 / `netrix_test` üzerinde geçti: veri içeren 06 → 07 geçişi, eski ve beklenmeyen tür kodlarının korunması, cihaz/profil/arayüz ilişkileri, FK silme/yazma engelleri, yeni adla arama, özelleştirme varken downgrade engeli, 07 → 06 → 07 ve Alembic schema check. Geçici DB/container/ağ kaldırıldı.
- `scripts/device_types_browser_check.py`: gerçek yerel API üzerinde tür CRUD, Lokasyonlar altındaki menü sırası, cihaz formu, türü kullanan cihaz için silme hatası, arayüz görünümü, toplu değişiklik ve indirilmiş XLSX seçim listesi geçti. 1440px/375px, açık/koyu temada 16 axe WCAG A/AA kontrolü ihlalsiz; JavaScript hatası/yatay taşma yok. Form alanlarının hizaları ölçüldü, ekran görüntüleri görsel olarak incelendi.
- TypeScript/Vite, Ruff, Prettier ve diff boşluk kontrolü geçti. İlk tam test denemesinde eşzamanlı Vite derlemesi geçici assets dizinini kaldırdığı için fixture başlangıcı etkilendi; derleme tamamlandıktan sonraki tam takım geçti. İlk tarayıcı denemesinde yeni varsayılan kapalı menü grubu açılmamıştı; betik gerçek menüyü açacak şekilde güncellenip geçti.

## Açık portların otomatik eklenmesi — 30 Ekim 2026

- Uzak depodaki topoloji değişiklikleri birleştirildikten sonra tam Python test takımı: **307 geçti**.
- `tests/test_interface_auto_selection.py`: açık portların seçimi ve ölçümü, kapalı/bilinmeyen portların ilk açık gözleminde eklenmesi, kapanan seçili portun korunması, kalıcı dışlama ve yeniden dahil etme, ifIndex değişiminde tercihin korunması, silme/devre dışı bırakma ayrımı, eski tam seçim API'si ve rol/atomik doğrulama testleri geçti. Değişiklik listesiyle kayıt, eşzamanlı otomatik eklenen portları yanlışlıkla dışlamaz. Gerçek ağ bağlantıları test fixture'ında engellidir.
- `scripts/interface_auto_migration_check.py` atılabilir MariaDB 11.8.3 / `netrix_test` üzerinde geçti: veri içeren 07 → 08 geçişi, eski kullanıcı seçimleri, silinmiş ve elle seçilmiş portlar, sonradan keşfedilen portlar, eski worker oturumunda yeni dışlamanın korunması, korumalı downgrade, 08 → 07 → 08 ve Alembic schema check. MariaDB eski transaction için 1020 döndürdüğünde mevcut worker yeniden deneme davranışına uygun yeni transaction kullanılır. Üretim verisi testlere alınmadı; geçici DB/container/ağ kaldırıldı.
- `scripts/interface_auto_browser_check.py`: gerçek yerel API ve sahte port gözlemleriyle ilk seçim, sonradan açılma, canlı yenilemede kaydedilmemiş tercihin korunması, yalnızca değişen portların kaydı, diyalogu yeniden açma, kapalı portu dışlama ve elle yeniden dahil etme geçti. 1440px/375px açık/koyu temada 16 axe WCAG A/AA kontrolü ihlalsiz; JavaScript hatası ve yatay taşma yok. Kart başlıkları ve checkbox merkezleri ölçüldü; masaüstü/mobil ekran görüntüleri incelendi.
- TypeScript/Vite, Ruff, Prettier ve diff boşluk kontrolü geçti. Yayın öncesi `/opt/netrix/backups/before-interface-auto-20261030.sql` yedeği alındı; 0600 izni ve boş olmadığı doğrulandı. Sırlar ve yedek içerikleri çıktıya yazdırılmadı.

## Özel cihaz türlerinin korunması — 30 Ekim 2026

- Uzak depodaki Aruba yedekleme güncellemesi birleştirildikten sonra tam Python test takımı: **322 geçti**.
- Üretimde salt okunur olay sorgusu, ekran görüntüsündeki üç cihazın Backbone katalog kodunun kayıt sonrası SNMPv2c kimlik sorgusuyla `switch` değerine çevrildiğini doğruladı. Dört regresyon testi düzeltme öncesinde aynı tür kaybıyla başarısız oldu; düzeltme sonrası kimlik, cihaz türü ve envanter kapsamındaki 54 test geçti.
- Yeni kayıt, tekli/toplu düzenleme ve sorgu sürerken değişen tür senaryoları gerçek yerel API ve sahte protokol istemcisiyle doğrulandı. Kimlik sorgusu ve izleme özel türü korurken üretici/modeli günceller; gözlemlenen `switch` keşif kanıtında kalır ve envanterde tür değişmiş gibi olay üretilmez. Standart türlerin otomatik tespiti mevcut testlerle korunur. Gerçek cihaz sorgusu yapılmadı.
- Şema veya arayüz değişikliği yok. Ruff ve diff boşluk kontrolü geçti. Üretim düzeltmesi öncesi `/opt/netrix/backups/before-custom-kind-20261030.sql` yedeği alındı; izin 0600 ve boş olmadığı doğrulandı.

## LLDP/CDP komşu kanıtı ve H3 düzeltmesi (30 Ekim 2026)

- H3 örneğinde CDP `38:21:c7:3c:b2:40` ikili kimliği ile LLDP sistem adı `HP-SW-CO-01-A-09-01` ve uzak port `49` canlı, salt okunur SNMP sorgusunda eşleşti. LLDP yerel kimliği `227`, port açıklaması ve IF-MIB adı `H3` olarak gözlendi.
- Backend test kümesi: 328 test geçti. Eklenen başarısız/desteklenmeyen komşuluk tablosu testiyle hedefli protokol/topoloji doğrulamaları ayrıca çalıştırıldı. Gerçek ağ erişimi testlerde yasak; canlı sorgu ayrı ve kullanıcı tetiklemesiyle yapıldı.
- `scripts/neighbor_migration_check.py`: atılabilir, Docker `--internal` ağındaki MariaDB 11.8.3 / `netrix_test` üzerinde eski veriyle 08 → 09 geçişi, JSON kanıt, UTC son gözlem zamanı, H3 kaydının aynı kimlikle düzeltilmesi, geçmiş/güncel ayrımı, korumalı downgrade, round trip ve Alembic şema kontrolü geçti. Üretim verileri bu test ortamına taşınmadı.
