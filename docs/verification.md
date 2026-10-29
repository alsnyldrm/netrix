# NETRIX doğrulama kaydı — 29 Ekim 2026

Bu kayıt çalıştırılan kontrolleri ve kapsam sınırlarını ayırır. Gerçek ağ cihazlarında SNMP/SSH/REST toplama testi yapılmadı; verilen DB/Docker/Nginx altyapı bağlantıları test edildi.

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
