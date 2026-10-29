# NETRIX işletim rehberi

## Sunucu yerleşimi

- Kaynak/Compose: Docker sunucusunda `/opt/netrix`.
- Secret ortam: `/opt/netrix/.env` (0600). Anahtar ve DB parolası bu dosyadan yüklenir. Uygulama imajına veya public depoya dahil değildir.
- İlk kurulum anahtarı: `/opt/netrix/secrets/ilk-kurulum.txt` (0600). Tek kullanımlıktır; ilk yönetici oluşturulduktan sonra hesap oluşturma yetkisi kalmaz.
- SSH host anahtarları: `/opt/netrix/secrets/known_hosts`. İlgili cihazın fingerprint'ini güvenilir cihaz konsolundan doğrulayıp OpenSSH formatında ekleyin. Otomatik güvenme veya doğrulamayı kapatma seçeneği yoktur.
- Nginx site dosyası: `/opt/nginx/conf/conf.d/netrix.conf`; sertifika yolları mevcut wildcard kurulumundan alınır. Host Nginx → `127.0.0.1:8101` → API/arayüz.

İlk ziyaret: `https://netrix.fbu.edu.tr`. Kurulum anahtarı ve kendi belirleyeceğiniz e-posta/parolayla yönetici hesabı açılır. Parola en az 12 karakterdir.

## Yayın ve kontrol

Cihaz bağlantısını denemek için **Envanter → Cihaz envanteri → satır sonundaki Test** yolunu kullanın. Pencerede yalnızca kayıtlı SNMPv3 veya SSH/API profiline ait seçenekler etkin olur. Protokolü seçip **Test et** düğmesine basın; gerçek cihaz yanıtı, hata ve süre aynı pencerede görünür. Aktif cihazın yetkili kapsamda olması gerekir. SSH için güvenilir host anahtarı, API için doğrulanabilir HTTPS sertifikası ve doğru REST cihaz bilgisi yolu gereklidir. Testi iptal edebilir veya pencereyi kapatıp sonucunu Görev merkezinden izleyebilirsiniz.

`netrix` stack'inde yalnızca `netrix-app` servisi ve `netrix` container'ı vardır. API, Redis, worker ve zamanlayıcı aynı container içindedir. `docker compose up -d` container başlangıcında önce migration'ı çalıştırır. API/worker/scheduler migration başarılı olmadan başlamaz. Harici MariaDB kullanıcısının schema oluşturma/güncelleme ve uygulama tablolarında CRUD yetkisi gerekir. Redis dışarıya port açmaz. API yalnızca host loopback portunu açar.

```bash
cd /opt/netrix
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8101/api/v1/health/ready
docker compose logs --tail=50 netrix-app
docker compose exec -T netrix-app supervisorctl -c /app/deploy/supervisord.conf status
```

Nginx dosyasını kurduktan sonra `docker exec nginx nginx -t`, ancak başarılıysa `docker exec nginx nginx -s reload`. Var olan sitelerin conf dosyalarını değiştirmeyin. DB erişimi veya migration başarısızken servisi yayında/sağlıklı olarak raporlamayın.

Stack sunucunun mevcut standalone Docker/Compose düzenini kullanır; Swarm etkinleştirilmez. Portainer dışında CLI ile kurulduğu için Portainer bunu `external` ve sınırlı yönetilebilir bir stack olarak gösterebilir ([Portainer açıklaması](https://docs.portainer.io/advanced/access-control)). Yetkili kaynak dosya `/opt/netrix/compose.yaml`'dır; değişiklikler buradan uygulanır.

`docker compose restart netrix-app` bütün NETRIX süreçlerini birlikte yeniden başlatır. Tek bir sürece müdahale için `supervisorctl -c /app/deploy/supervisord.conf restart netrix-worker` komutunu container içinde çalıştırın. Redis volume'u `netrix_netrix-redis` olarak korunur; container kullanıcısı UID/GID 10001'dir. Eski ayrı Redis container'ından geçişte volume kapalıyken yedeklenip bu kullanıcıya atanır. `down -v` kalıcı Redis verisini siler; normal güncellemede kullanılmaz.

## Kullanım sırası

1. Erişim kasasında SNMPv3 authPriv (SHA256 veya SHA1 + AES128) profili oluşturun. SSH/REST yedeği için ayrı profil oluşturun.
2. Lokasyonları, gerekli VRF/VLAN/prefix'leri tanımlayın. Global VRF ilk kurulumda oluşur.
3. Keşif kapsamına yalnızca yetkili olduğunuz CIDR'ı girin. Hariç tutmaları ve gerekirse açık hedef listesini ekleyin. Zamanlama 0 iken otomatik tarama yoktur.
4. Manuel keşif başlatın; Görev merkezi üzerinden ilerleme, hata, kısmi sonuç ve iptali takip edin.
5. Cihaz ayrıntılarında yönetilen envanteri ve gözlem kanıtını ayrı inceleyin. Arayüzleri, komşuluk güvenini ve ARP/NDP/FDB port adaylarını kontrol edin.
6. Cihaza SSH/REST profili atayın, host anahtarını doğrulayın, manuel yedek alın. Arşivde maskelenmiş sürüm/diff'i inceleyin.
7. SNMP profilini atayıp izlemeyi etkinleştirin. İlk örnek baseline'dır; ikinci geçerli örnekten sonra hız çıkar. Zamanlama aralığı en az 60 saniye.
8. Alarm kuralları oluşturun. Erişilebilirlik ve config-change kurallarında eşik alanı kullanılmaz; kullanımda yüzde, no-data'da saniyedir. Kalıcı alarm akışı, görüldü ve iyileşme durumlarını takip edin.

## Yedekleme ve geri yükleme

Host üzerinde Python 3 ve Docker ile; MariaDB istemcisi çalışan NETRIX container'ında kullanılır, ek container açılmaz:

```bash
cd /opt/netrix
mkdir -p backups
chmod 700 backups
python3 scripts/backup.py --output backups/netrix-YYYYMMDD.sql
```

SQL dosyası 0600 oluşturulur; uygulama credential'ları ve config içerikleri hâlâ şifreli olsa da tüm backup hassas kabul edilir. Şifreleme anahtarını, `.env` dosyasını ve known_hosts'u veritabanından ayrı, güvenli bir yedek konumunda tutun. Anahtar olmadan cihaz sırları ve konfigürasyon arşivi çözülemez.

Geri yükleme mevcut tabloları değiştirebilir. Önce çalışan yedek alın; API/worker/scheduler'ı durdurun. Hedef DB adını açıkça belirtin:

```bash
docker compose exec -T netrix-app supervisorctl -c /app/deploy/supervisord.conf stop netrix-scheduler netrix-worker netrix-api
python3 scripts/backup.py --restore --confirm-database netrix --output backups/netrix-YYYYMMDD.sql
docker compose exec -T netrix-app alembic -c backend/alembic.ini upgrade head
docker compose exec -T netrix-app supervisorctl -c /app/deploy/supervisord.conf start netrix-api netrix-worker netrix-scheduler
```

Geri yükleme sırasında API/worker/zamanlayıcı kasıtlı olarak durduğundan container unhealthy görünür; işlem başarıyla tamamlanıp süreçler başlatılınca healthcheck tekrar geçer. Redis ve Supervisor çalışmayı sürdürür.

Bu komutlar işletim prosedürüdür; teslim sırasında üretim DB'sinde geri yükleme uygulanmaz. Geri yükleme kabul testi yalnızca atılabilir `netrix_test` veritabanında yapılır.

## Sorun giderme

- `Access denied`: parola/URL encoding, kullanıcının bağlandığı kaynak host ve hedef DB yetkisini kontrol edin. Uygulama başka uygulama kullanıcılarını veya DB yöneticisi parolasını denemez.
- Worker heartbeat yok: worker loglarının yalnızca hata sınıfı ve job ID içeren kayıtlarını inceleyin. İşler MariaDB'de kalır; 90 saniye sonra sınırlı tekrar mekanizması devreye girer.
- SSH doğrulama hatası: cihaz fingerprint'ini konsoldan doğrulayın; `known_hosts` güncelleyin. Anahtar değişimini otomatik kabul etmeyin.
- SNMP kısmi sonuç: authPriv algoritması, kullanıcı yetkileri, UDP/161 erişimi ve üreticinin MIB desteğini doğrulayın. SNMP yanıtı alınamaması fiziksel cihazın kapalı olduğunu kanıtlamaz.
- WebSocket kopması: Nginx Upgrade başlıkları, Origin ve oturum geçerliliğini kontrol edin. Arayüz yeniden bağlanmayı dener; 30 saniyelik REST yenilemesi de vardır.

## Veritabanı hedef kuralı

Uygulama yalnızca VIP `10.2.0.31:3306` kullanır. DB düğümlerine doğrudan yönlendirilmez. Salt okunur teşhis sırasında doğrudan düğüm testi yapılmış olması üretim bağlantı hedefini değiştirme yetkisi oluşturmaz. VIP kaynak adresi sorunu DB/HAProxy bakım sohbetinde ele alınır; bu uygulamanın `.env` hedefi aynı kalır.
