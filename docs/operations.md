# NETRIX işletim rehberi

## Sunucu yerleşimi

- Kaynak/Compose: Docker sunucusunda `/opt/netrix`.
- Secret ortam: `/opt/netrix/.env` (0600). Anahtar ve DB parolası bu dosyadan yüklenir. Uygulama imajına veya public depoya dahil değildir.
- İlk kurulum anahtarı: `/opt/netrix/secrets/ilk-kurulum.txt` (0600). Tek kullanımlıktır; ilk yönetici oluşturulduktan sonra hesap oluşturma yetkisi kalmaz.
- SSH host anahtarları: `/opt/netrix/secrets/known_hosts`. İlgili cihazın fingerprint'ini güvenilir cihaz konsolundan doğrulayıp OpenSSH formatında ekleyin. Cihaz ekleme/düzenleme formundaki **Anahtara güven** seçeneği varsayılan olarak kapalıdır. İşaretlenip kaydedilirse yalnızca o cihazın sunduğu SSH anahtarı kabul edilir; bu ayar SSH testi, kimlik okuma ve yedekleme için geçerlidir. Bu modda anahtar dosyayla karşılaştırılmaz veya sabitlenmez; kullanıcı adı/parola doğrulaması devam eder. Seçeneği kaldırıp kaydetmek dosya üzerinden doğrulamayı yeniden etkinleştirir.
- Nginx site dosyası: `/opt/nginx/conf/conf.d/netrix.conf`; sertifika yolları mevcut wildcard kurulumundan alınır. Host Nginx → `127.0.0.1:8101` → API/arayüz.

İlk ziyaret: `https://netrix.fbu.edu.tr`. Kurulum anahtarı ve kendi belirleyeceğiniz e-posta/parolayla yönetici hesabı açılır. Parola en az 12 karakterdir.

## Yayın ve kontrol

Cihaz bağlantısını denemek için **Envanter → Cihaz envanteri → satır sonundaki Test** yolunu kullanın. Pencerede yalnızca kayıtlı SNMPv3/SNMPv2c veya SSH/API profiline ait seçenekler etkin olur. Protokolü seçip **Test et** düğmesine basın; gerçek cihaz yanıtı, hata ve süre aynı pencerede görünür. Aktif cihazın yetkili kapsamda olması gerekir. SSH için güvenilir host anahtarı veya cihazda açık **Anahtara güven** ayarı; API için doğrulanabilir HTTPS sertifikası ve doğru REST cihaz bilgisi yolu gereklidir. Testi iptal edebilir veya pencereyi kapatıp sonucunu Görev merkezinden izleyebilirsiniz.

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

1. Erişim kasasında SNMPv3 authPriv (SHA256 veya SHA1 + AES128) veya SNMPv2c community profili oluşturun. SNMPv2c seçildiğinde yalnızca community alanı gerekir; şifreli saklanır ve API yanıtlarına dönmez. Yedek için ayrı SSH profili oluşturun.
2. Lokasyonları, gerekli VRF/VLAN/prefix'leri tanımlayın. Global VRF ilk kurulumda oluşur.
3. Keşif kapsamına yalnızca yetkili olduğunuz CIDR'ı girin. Hariç tutmaları ve gerekirse açık hedef listesini ekleyin. Zamanlama 0 iken otomatik tarama yoktur.
4. Manuel keşif başlatın; Görev merkezi üzerinden ilerleme, hata, kısmi sonuç ve iptali takip edin.
5. Cihaz ayrıntılarında yönetilen envanteri ve gözlem kanıtını ayrı inceleyin. Arayüzleri, komşuluk güvenini ve ARP/NDP/FDB port adaylarını kontrol edin.
6. Cihaza SSH profili atayın, host anahtarını doğrulayın, manuel yedek alın. FortiGate için admin-scp ve hesabın SCP yedek yetkisi gereklidir; [SSH/SCP yönergesini](fortigate-ssh-backup.md) izleyin. Arşivde maskelenmiş sürüm/diff'i inceleyin.
7. SNMP profilini atayıp izlemeyi etkinleştirin. İlk örnek baseline'dır; ikinci geçerli örnekten sonra hız çıkar. Zamanlama aralığı en az 60 saniye.
8. Alarm kuralları oluşturun. Erişilebilirlik ve config-change kurallarında eşik alanı kullanılmaz; kullanımda yüzde, no-data'da saniyedir. Kalıcı alarm akışı, görüldü ve iyileşme durumlarını takip edin.

## Cihaz türleri

**Envanter → Lokasyonlar** menüsünün hemen altındaki **Cihaz Türü** ekranından tür adı ve açıklaması eklenir/düzenlenir. Cihaz ekleme/düzenleme, toplu değişiklik, cihaz/arayüz araması ve CSV/XLSX aktarımı aynı listeyi kullanır. Excel şablonundaki tür listesi indirme anında yenilenir. Türün adını değiştirmek cihazın kimliğini veya geçmişini değiştirmez; bağlı cihaz ve arayüzlerde yeni ad görünür.

Operatör/yönetici ekleyip düzenleyebilir, yalnızca yönetici silebilir. Arşiv dahil herhangi bir cihaza atanmış tür silinemez; önce bu cihazlara başka bir tür atayın. Sınıflandırılamayan yeni cihazlar için kullanılan varsayılan **Diğer** türünün adı düzenlenebilir, fakat kayıt silinemez. Kullanılmayan diğer türler silinebilir. Cihazdan okunan tür katalogdan silinmişse mevcut manuel tür korunur.

`20261030_07` migration'ı eski tür kodlarını ve bağlı cihazları koruyarak `device_types` tablosunu ve FK kısıtını ekler. Özelleştirilmiş tür verisi varken downgrade veri kaybetmek yerine durur.

Backbone, Controller gibi sonradan eklenen katalog türleri kullanıcı sınıflandırmasıdır. Cihaz ekleme/düzenleme, toplu düzenleme veya içeri aktarmayla seçilen bu türler SNMP/SSH/API kimlik sorgusu, keşif ve izleme sırasında genel Switch/Router tespitiyle değiştirilmez. Gözlemlenen donanım türü keşif kanıtında saklanır; üretici/model güncellenmeye devam eder. Standart türlerde (Switch, Router, Firewall, Sunucu, Diğer) mevcut otomatik tür tespiti sürer. İsim değil, katalog kodu esas alınır.

## Arşivlenmiş cihazlar

Cihaz envanterindeki **Sil** işlemi fiziksel silme yapmaz; cihazı arşivler ve normal listeden kaldırır. Aynı VRF/IP kimliği, arayüzleri ve yedek geçmişi korunur. Bu yüzden arşivdeki cihaz aynı IP ile yeniden içeri aktarılamaz; aktarım hatası arşiv menüsüne yönlendirir.

**Envanter → Arşivlenmiş cihazlar** bölümünde IP/ad dahil bütün kayıt alanlarında arama, VE/VEYA filtreleri ve sütun seçimi kullanılabilir. Yönetici, satırdaki **Geri yükle** düğmesiyle veya birden çok cihazı seçerek kayıtları geri yükler. İzleyici ve operatör arşivi görüntüleyebilir; geri yükleme yönetici yetkisi ister.

Geri yüklenen cihaz aynı kimlikle **Cihaz envanteri** listesine **Bakımda** durumunda döner. Profiller, güven tercihi, grup ve geçmiş korunur; izleme kapalı, cihazın yedek aralığı 0 olur. Bakımda durumu, korunan yedek grubunun zamanlamasını da durdurur. Cihaz ayarlarından yaşam döngüsünü Aktif yapıp izleme/zamanlama ayarlarını düzenleyin. Geri yükleme kendi başına bağlantı testi veya keşif başlatmaz.

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
- SSH host anahtarı doğrulama hatası: cihazı düzenleyip **Anahtara güven** seçeneğini işaretleyerek kaydedin veya cihaz fingerprint'ini konsoldan doğrulayıp `known_hosts` kaydını güncelleyin. Ardından **Test → SSH → Test et** ile tekrar deneyin.
- SNMP kısmi sonuç: authPriv algoritması, kullanıcı yetkileri, UDP/161 erişimi ve üreticinin MIB desteğini doğrulayın. SNMP yanıtı alınamaması fiziksel cihazın kapalı olduğunu kanıtlamaz.
- WebSocket kopması: Nginx Upgrade başlıkları, Origin ve oturum geçerliliğini kontrol edin. Arayüz yeniden bağlanmayı dener; 30 saniyelik REST yenilemesi de vardır.

## Veritabanı hedef kuralı

Uygulama yalnızca VIP `10.2.0.31:3306` kullanır. DB düğümlerine doğrudan yönlendirilmez. Salt okunur teşhis sırasında doğrudan düğüm testi yapılmış olması üretim bağlantı hedefini değiştirme yetkisi oluşturmaz. VIP kaynak adresi sorunu DB/HAProxy bakım sohbetinde ele alınır; bu uygulamanın `.env` hedefi aynı kalır.

## Envanter ve yedek ekranlarının kullanımı

- **Envanter → Cihaz envanteri:** tüm kayıtlarda arama, VE/VEYA koşullu filtre, kullanıcıya ait sütun seçimi. Satır kutularını seçerek toplu düzenleme/silme açılır. Düzenleme penceresinde yalnızca işaretlenen alanlar uygulanır; tek bir hatalı kayıt tüm toplu işlemi geri alır.
- **Cihaz ayrıntısı → Arayüzler:** açık (`up`) portlar otomatik seçilip uygulamaya alınır. Kapalı veya durumu bilinmeyen portlar ilk açık gözleminde eklenir; önceden eklenen portlar kapandığında listede kalır. İşaretini kaldırıp **Arayüz seçimini kaydet** dediğiniz portlar sonraki gözlemlerde tekrar eklenmez; yeniden işaretleyip kaydetmek bu engeli kaldırır. Görünenleri kaldır işlemi kapalı portlar için de bu tercihi kaydeder. Canlı yenileme kaydedilmemiş seçimleri korur. Yeni adayları görmek için SNMP profiliyle **Ölçüm al** veya mevcut zamanlanmış izleme kullanılabilir; cihaz yapılandırması değişmez.
- **Envanter → Arayüzler:** önce cihazı, sonra portlarını açın. Arama kapasite, ifIndex, durum ve cihaz türünü kapsar. Seçili portları devre dışı bırakmak NETRIX ölçümlerini durdurur; fiziksel port durumu değişmez. Silinen port geçmişi korunur ve cihaz ayrıntısından yeniden seçilebilir.
- **Yedekler → Cihaz yedekleri:** önce yedeği bulunan cihazlar, yedek sayısı ve son yedek tarihiyle listelenir. Cihaz adına veya satırdaki görüntüleme düğmesine basınca yalnızca o cihazın yedekleri açılır; **Cihazlara dön** ile listeye dönülür. Arama, filtreleme ve sayfalama her iki düzeyde çalışır. Maskelenmiş görüntüleme/indirme, önceki sürümle fark ve admin için silme desteklenir. Arşivlenmiş cihazların yedekleri de erişilebilir. **Değişenler** yalnızca önceki yedeğe göre değişen sürümleri gösterir.
- **Yedekler → Karşılaştır:** önce cihaz seçilir, ardından yalnızca o cihazın yedekleri arasından seçilen yedek ile cihazın o anda okunan aktif konfigürasyonu karşılaştırılır. Görev penceresinde durum/iptal/fark izlenir. Desteklenen SSH profili, aktif cihaz ve yetkili kapsam gerekir; SNMP/REST yedekleme veya karşılaştırma yapılmaz.
- **Yedekler → Gruplandırma ayarları:** firewall, switch, controller, backbone gibi adlarla grup oluşturun; aralık ve tutulacak yedek sayısını belirleyin. **Yedekleme ayarları** ekranında cihazları seçip grubu veya cihaz politikasını uygulayın. Grup ayarı üyelerin cihaz ayarını geçersiz kılar. Aralık 0 kapalı, diğer değerler en az 300 saniye; saklama 0 sınırsızdır. Saklama sınırını azaltmak eski sürümleri otomatik siler. Karşılaştırmada kullanılan sürüm işlem tamamlanana kadar korunur.

`20261030_05` öncesinde MariaDB yedeği alın. Geçiş yeni grup/politika ve arayüz seçim alanlarını ekler; downgrade bu yeni tercihleri kaybettirir. Veri içeren atılabilir MariaDB'de upgrade/downgrade/upgrade ve Alembic schema farkı kontrolü için `scripts/inventory_migration_check.py` yalnızca `netrix_test` veritabanını kabul eder.

`20261030_08`, `interfaces.auto_add_excluded` alanıyla kullanıcı tercihini gözlemlenen port durumundan ayırır. Silinmiş portlar ve eski seçim kaydı sırasında mevcut olup seçilmemiş portlar dışlanmış kabul edilir; sonraki keşifler otomatik eklemeye açıktır. Arşivlenmemiş cihazların mevcut açık ve dışlanmamış portları geçişte seçilir. Downgrade, kayıtlı dışlamaları kaybettirecekse durur. `scripts/interface_auto_migration_check.py` yalnızca atılabilir `netrix_test` veritabanında geçişi ve eşzamanlı kullanıcı tercihinin korunmasını doğrular.

## SNMPv2c erişim profilleri

**Yönetim → Erişim kasası → Yeni kayıt → Protokol: SNMPv2c** yolunda profil adı ve cihazın community değerini girin. Düzenlemede community yeniden girilerek değiştirilir. Profil, cihazın SNMP profili ve keşif kapsamının SNMP erişim profili alanlarında seçilebilir; keşif, izleme, kimlik okuma ve bağlantı testi aynı kayıtlı sürümü kullanır. SNMPv3 varsayılanı korunur; sürümler arasında otomatik geçiş yapılmaz.

`20261030_06` migration'ı yalnızca erişim profili protokol kısıtını genişletir. Mevcut şifreli değerleri değiştirmez. Downgrade, SNMPv2c profili varsa veri silmeden durur; önce bu profillerin bağımlılıkları kaldırılıp profiller silinmelidir. Atılabilir `netrix_test` veritabanındaki doğrulama: `scripts/snmpv2c_migration_check.py`.

## Cihazları CSV / XLSX ile içe/dışa aktarma

**Envanter → Cihaz envanteri → İçeri Aktar → CSV veya XLSX** üzerinden güncel şablonu indirin. UTF-8 CSV'de virgül, noktalı virgül veya sekme desteklenir; üst sınır 1 MiB / 500 cihazdır. İlk sekiz sütun sırasıyla `Cihaz adı *`, `Yönetim IP adresi *`, `SNMP profili *`, `SSH / API profili *`, `Anahtara güven *`, `Lokasyon *`, `Yaşam döngüsü *`, `Konfigürasyon adaptörü *` şeklindedir ve zorunludur. Diğer alanlar isteğe bağlıdır; sütunları kaldırılabilir. VRF boş bırakılırsa kayıtlı **Global** VRF kullanılır. Global bulunamazsa hata verilir; başka VRF kendiliğinden seçilmez veya oluşturulmaz. Bu zorunluluklar yalnızca içeri aktarmaya aittir; cihaz formu değişmez.

XLSX şablonunda Cihazlar ve Açıklamalar sayfaları, ayrıca gizli Seçenekler sayfası bulunur. 2–501. satırlarda bir hücreyi seçip yanındaki oka basarak listeden değer seçin. SNMP listesi yalnızca SNMPv2c/v3; SSH/API listesi yalnızca SSH/rest profillerini içerir. Lokasyon, VRF ve yedek grubu sistemdeki kayıtlardan; yaşam döngüsü, tür ve adaptör desteklenen seçeneklerden gelir. Diğer alanlar mevcut değerleri önerir, yeni metin/sayı girişine de izin verir. Anahtara güven ve Zamanlanmış izleme için Evet/Hayır seçilebilir. Parola sütunlarında yalnızca maske önerilir. Seçenekler **indirme anında** günceldir; yeni profil/lokasyon ekledikten sonra şablonu yeniden indirin. CSV açılır liste saklayamaz; alanları metin olarak doldurun.

Örnek satırdaki 192.0.2.10 adresini ve diğer seçimleri kendi cihazınıza göre değiştirin. Profil ve lokasyon örnekleri varsa sistemdeki ilk kayıtla doldurulur; kayıt yoksa boş kalır. API profili seçildiğinde `rest`, SSH için uyumlu SSH adaptörü seçilmelidir. Kayıtlar ad veya kimlikle eşleştirilir; aynı adlı birden fazla kayıt varsa listede kimlikleri gösterilir. Türkçe sütun başlıkları veya `DeviceInput` anahtarları kabul edilir. Eski `Adaptör` ve `VRF *` başlıkları da okunabilir; yeni zorunluluklar yine uygulanır.

Anahtara güven için Hayır/false geçerlidir, boş değer kabul edilmez. Zorunlu sütun eksikse veya satırda boşsa dosya içeri alınmaz. Excel doğrulaması kopyala/yapıştır ile aşılabilse bile sunucu tekrar kontrol eder; eski şablondaki silinmiş profil/lokasyon kabul edilmez. Parola/token/SNMP anahtarı/community sütunları boş veya yıldızlı olabilir; gerçek sırlar **Erişim kasası** üzerinden yönetilir. Şablon oluşturulurken erişim profillerinin şifreli sır sütunları dahi okunmaz; içeri aktarma bu sırları değiştirmez.


Dosya seçildiğinde salt okunur doğrulama ve önizleme yapılır. Hatalı satır varsa hiçbir cihaz eklenmez. **İçeri aktar** tekrar doğrular ve tüm cihazları tek transaction ile oluşturur. Aynı VRF/IP adresindeki cihazlar, arşivlenmiş olanlar dahil, mükerrer kabul edilir; mevcut cihazlar güncellenmez. Başarılı kayıtta olağan kimlik sorgusu yalnızca atanmış profil ve yetkili kapsam varsa worker'a alınır; önizleme hiçbir ağ işi oluşturmaz.

Dışa aktarmak için cihazların kutularını seçin ve **Dışarı Aktar** düğmesine basıp **CSV** veya **XLSX** seçin. Yalnızca seçili cihazlar çıkarılır. SSH parolası, API token, SNMP anahtarları ve community atanmış profillere göre sabit `********` olarak yazılır; secret payload'ı okunmaz veya çözülmez. CSV UTF-8 BOM içerir. Excel formülü olarak yorumlanabilecek hücrelere koruyucu tek tırnak eklenir; NETRIX yeniden içe aktarırken bu korumayı geri alır. İçe ve dışa aktarma admin/operator yetkisi gerektirir ve denetim kaydına yalnızca işlem/satır sayısı yazılır.


**İçeri Aktar ve Test Et**, içe aktarma ile birlikte atanmış SNMPv3/SNMPv2c ve SSH/API profilleri için bağlantı testlerini aynı transaction içinde kuyruğa alır. API cihaz bağlantısı açmaz; mevcut worker motoru gerçek protokol testi yapar. Önizleme veya normal **İçeri Aktar** düğmesi bağlantı testleri başlatmaz. Aktif olmayan veya yetkili kapsam dışında kalan cihazlar kaydedilir ancak test başlatılmaz; sonuç penceresinde gerekçesiyle **Test edilemedi** görünür. Sonuç özeti cihaz bazındadır: tüm protokoller başarılıysa başarılı; tamamlanan testlerden biri başarısızsa başarısız; süren test varsa bekleyen. Test hatası cihaz kaydını silmez. Pencere kapatıldığında işler sürer ve Görev merkezinden izlenebilir.

XLSX dosyası 1 MiB, açılmış ZIP toplamı 8 MiB, en fazla 500 cihaz ve şablondaki sütun sayısı ile sınırlıdır. Hücre formülleri, Excel hata değerleri ve makrolar reddedilir; değerleri doğrudan girin. CSV ve XLSX aynı alan, profil, mükerrer kayıt ve transaction doğrulamasını kullanır. Bağlantı testi sonuçları yalnızca operator/admin tarafından sorgulanabilir.

## Bağlantı haritası

Harita yalnızca merkezi envanterdeki cihazların adını ve yönetim IP adresini gösterir. Firewall en üstte; backbone (`backbone` türü veya `-BB-` ad bileşeni) ve controller aynı seviyededir. Diğer cihazlar kayıtlı bağlantıların uzaklığına göre alt seviyelere yerleşir. Bu yerleşim bir görsel düzendir; aynı seviyedeki bağlantılar, döngüler ve çoklu uplink kayıtları korunur. Envantere eşleşmeyen komşular bağlantı tablosunda kalır. Kesik çizgiler aday eşleşmedir; kaynağı ve güveni tablodan inceleyin.

**+ / −** haritayı büyütür/küçültür; **Sığdır** tüm haritayı alana sığdırır. Büyütülen haritada kaydırma çubukları, dokunma veya odaklanan harita üzerinde klavye ile gezinilebilir. Cihaz düğmeleri Enter/Space ile açılır. Eski 12 cihaz/200 bağlantı görüntüleme sınırları kaldırılmıştır.

SNMP komşu adları ve portlar UTF-8 metin olarak çözümlenir. İkili 6 bayt kimlikler MAC, diğer ikili kimlikler hex biçimindedir. Önceden metin olarak saklanan kontrol karakterli MAC kimlikleri API sunumunda düzeltilir; ham gözlemler değiştirilmez. Sonraki toplama aynı eski linki yeniden kullanır. CDP sysName mevcutsa Device-ID yerine tercih edilir ([Cisco CISCO-CDP-MIB](https://raw.githubusercontent.com/cisco/cisco-mibs/main/v2/CISCO-CDP-MIB.my)).

Kullanıcı açıkça fiziksel bağlantıyı doğruladığında, işletim erişimiyle `scripts/confirm_topology_link.py --local-id UUID --remote-id UUID` çalıştırılabilir. Aynı VRF içindeki iki arşivlenmemiş cihaz için tekrar güvenli kayıt açar; kaynak `manual`, güven 1 olur ve olay geçmişine yazılır. Portlar verilmediğinden boş kalır. Bu işlem ağ sorgusu yapmaz ve otomatik keşif olarak sunulmaz.
