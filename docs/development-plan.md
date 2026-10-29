# NETRIX ilk geliştirme adımları

> **29 Ekim 2026 güncellemesi:** Proje sahibi harici MariaDB ve üç modülün arayüz/motorlarıyla birlikte teslimini istedi. Bu belgedeki PostgreSQL/TimescaleDB seçimleri eski hedef tasarıma aittir. Son dağıtım kararı tek servisli `netrix` Compose stack ve tek container içinde API, Redis, worker ve zamanlayıcıdır. Çalışan MariaDB tür eşlemeleri, süreçler ve uygulanan davranışlar için [mimariyi](architecture.md) ve migration dosyalarını esas alın.
Bu plan sıralıdır. Her adımın çıktısı ve kabul ölçütü tamamlanmadan ona bağlı adıma geçilmez. Belge hedef planıdır; tamamlanmış iş listesi değildir. Veri ayrıntıları için [veri modelini](data-model.md) kullan.

1. **Proje iskeleti ve bağımlılık kararları.** Python sürümünü, bağımlılık yönetimini, SQLAlchemy/Alembic kullanımını, Redis kuyruk/zamanlayıcı kütüphanesini ve protokol kütüphanelerini seçip sabitle. `backend`, `workers`, `tests` ve `docs` yerleşimini oluştur; backend içinde identity, inventory, ipam, discovery, configuration, monitoring ve alerting modül sınırlarını tanımla. **Kabul:** kurulum komutları ve kararlar belgelenmiş, boş uygulama içe aktarılabiliyor.

2. **Docker Compose altyapısı.** Tek `netrix-app` servisini, `netrix` container'ını, kalıcı Redis volume'unu, dört süreci birlikte denetleyen healthcheck'i ve secret/ortam örneklerini tanımla. API/arayüz, Redis, worker ve zamanlayıcı aynı container içinde Supervisor tarafından yönetilir. Migration, Supervisor başlamadan önce uygulanır; hata varsa uygulama başlamaz. Harici MariaDB kullanılır. **Kabul:** Compose tek servis üretir; temiz kurulum, süreç yeniden başlatma, migration hatasında kapalı kalma ve container yeniden başlatmasında kalıcılık doğrulanır.

3. **FastAPI çekirdeği.** Ayar yönetimi, DB oturumu, yapılandırılmış ve sırları maskeleyen loglar, request ID ve standart hata yanıtlarını ekle. `/api/v1`, `NETRIX API` OpenAPI kimliği ve ayrı liveness/readiness uçlarını kur. **Kabul:** OpenAPI üretiliyor, health testi geçiyor; bağımlılık yokluğunda readiness başarısız olurken liveness çalışıyor.

4. **İlk migration ve merkezi kimlik doğrulama.** Kullanıcı/rol/yetki, audit, site, üretici/model, cihaz/arayüz, VRF/VLAN/prefix/IP, credential ve iş/keşif tablolarını ekle. Merkezi yetki kontrolleri ve güvenli ilk yönetici oluşturma komutunu hazırla. **Kabul:** migration boş DB'ye uygulanıyor; korunan API yetkisiz isteği reddediyor, admin/operator/viewer sınırları doğrulanıyor; sabit varsayılan parola yok.

5. **Merkezi cihaz envanteri API'si.** Site, model, cihaz, endpoint, arayüz ve etiket CRUD uçlarını; filtreleme, sayfalama, yaşam döngüsü ve audit kayıtlarını geliştir. **Kabul:** bir cihaz bütün modüllerin paylaşacağı tek kimlikle yönetiliyor; FK/tekillik/yanlış site ilişkisi kontrolleri ve API entegrasyon testleri geçiyor.

6. **Temel IPAM API'si.** VRF, VLAN domain, VLAN, IPv4/IPv6 prefix, IP ve arayüz atamalarını ekle. Kapsama, hiyerarşi, çakışma, rezervasyon ve kullanım hesaplarını uygula. **Kabul:** farklı VRF'lerde aynı IP kabul ediliyor; aynı VRF'deki tekrar ve hatalı atamalar reddediliyor; IPv6, /31 ve /32 örnekleri doğrulanıyor.

7. **Şifreli erişim profilleri ve adaptör sözleşmesi.** Credential şifreleme, key version, maskeleme ve SNMPv3/SSH/API istemci arayüzlerini geliştir. Timeout, hata sınıfları ve SSH host key doğrulamasını tanımla. Önce SNMPv3 salt okunur veri toplama adaptörünü uygula. **Kabul:** DB'de açık sır bulunmuyor; API/log sızıntı testleri ve sahte protokol istemcisi testleri geçiyor.

8. **Kalıcı görev yürütme.** Redis kuyruğu, zamanlayıcı, PostgreSQL iş durumları, outbox yayınlayıcı, idempotency, retry/backoff, heartbeat, hedef kilidi ve iptal mekanizmasını ekle. **Kabul:** API bir iş kimliği döndürüyor; aynı teslim ikinci mantıksal kayıt üretmiyor; worker kesintisinden sonra iş kaybolmadan devam edebiliyor veya açık hata durumuna geçiyor.

9. **İlk çalışan keşif dilimi.** Yetkili CIDR kapsamı ve hariç tutmaları uygula; IPv6'da geniş adres alanını körlemesine taramak yerine seed/hedef listeleri ve komşuluk verilerini kullan. Sınırlı eşzamanlı erişilebilirlik ve SNMPv3 sorgularıyla sistem, hostname, cihaz kimliği ve arayüz bilgilerini topla. API üzerinden keşif başlatma/izleme/iptal uçlarını ekle. **Kabul:** fixture ağı iki kez tarandığında cihazlar çoğalmıyor; kapsam dışına çıkılmıyor; ICMP yanıtlamayan cihaz yalnızca bu nedenle yok sayılmıyor; kısmi hata raporlanıyor.

10. **Port korelasyonu ve topoloji.** ARP/NDP, FDB, VLAN ve LLDP/CDP tablolarını yeteneklere göre topla. IP–MAC–switch–port eşleştirmesini, çözülemeyen komşuları, güven düzeylerini ve bağlantı geçmişini uygula. **Kabul:** uç port/uplink ayrımı, LAG, döngülü topoloji, eksik LLDP ve çift yönlü aynı link örnekleriyle doğrulanıyor; belirsiz eşleşme kesin diye sunulmuyor.

11. **Değişiklik olayları ve WebSocket.** IP/hostname/MAC/bağlantı değişimlerini kalıcı kaydet; yetki kontrollü aboneliklere commit sonrasında bildir. **Kabul:** rollback bildirim üretmiyor; kullanıcı yetkisi olmayan verilere abone olamıyor; yeniden bağlanan istemci güncel durumu API'den alabiliyor.

12. **İlk aşama teslim doğrulaması.** Migration, API, IPAM, credential, kuyruk ve keşif testlerini çalıştır. Temiz Compose kurulumu, yedekleme/geri yükleme, örnek veri ve yetkili laboratuvar keşfi için çalıştırma rehberi yaz. **Kabul:** Compose → yönetici → cihaz/credential → prefix/kapsam → keşif → sonuç sorgulama akışı tekrarlanabiliyor; kullanılan komutlar ve sonuçları teslimde raporlanıyor. Gerçek cihaz testi yapılmadıysa bunu açıkça belirt.

İlk aşamadan sonra sırasıyla konfigürasyon yedekleme/sürüm/diff motoru, SNMPv3 trafik örnekleme ve TimescaleDB saklama politikaları, alarm/bildirim motoru geliştirilir. Arayüz, proje sahibinin tasarımı ve ayrı kapsam doğrultusunda bu API'lere bağlanır.
