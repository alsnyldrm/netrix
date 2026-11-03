# Firmware yönetimi

NETRIX'in **Firmware** bölümü sol menüde **IP adres yönetimi** bölümünün hemen altındadır. Cihazlar, Firmware deposu, Gruplar, Güncelleme planları, İşlem geçmişi ve Aktarım ve kurtarma ekranlarını kapsar. Cihaz envanteri ortaktır; firmware grupları yedekleme gruplarından bağımsızdır. Kurulum boş başlar; örnek cihaz, imaj, grup veya başarılı işlem eklenmez.

## Kapsam ve protokoller

Cihazların HTTPS/WebUI/REST servisi kullanılmaz ve kendiliğinden açılıp kapatılmaz. Uygulamanın kullanıcıya sunduğu mevcut HTTPS erişimi korunur.

| Adaptör | Komut / dosya yolu | İmaj |
| --- | --- | --- |
| Aruba 54xx, 2900 (5400/5400R, 2920/2930) | SSH komut oturumu; SFTP ile `/os/primary` veya `/os/secondary` alanına gönderme | Modele uygun `.swi`, K/KB/WB/WC ailesi |
| Aruba 61xx (6100) | SSH komut oturumu; cihazın süreli SCP hesabıyla NETRIX'ten çekmesi, `vrf default` | PL ailesi `.swi` |
| HP 1950 | SSH sınırlı CLI; `upgrade <sunucu> runtime file <dosya>.ipe` ile TFTP çekme | Ürün koduna uygun `.ipe` |

AOS-S ön kontrolde SFTP alt sistemi salt okunur sınanır. Kapalıysa yalnız planda ayrıca onaylanan **SFTP erişimini aç** seçeneği, yedekten sonra `ip ssh filetransfer` uygular; TFTP’nin kapanacağı kullanıcıya gösterilir. Sessiz protokol değişikliği yapılmaz.

1950 firmware işlemi `xtd-cli-mode` kullanmaz. Ancak mevcut konfigürasyon yedek adaptörü için ayrıca gerekli olabilen genişletilmiş CLI erişimi korunur; yedek alınamazsa firmware yazımı başlamaz. JH295A R51xx ailesi, diğer OfficeConnect 1950 SKU'larıyla karıştırılmaz. Dosya sunucusu erişiminin cihaz tarafından sağlanması gerekir. 7200 controller, AOS8→10 geçişi ve ISSU bu firmware adaptörlerinin kapsamına dahil değildir.

Kaynaklar: [AOS-S dosya sistemi ve flash yazımı](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/scp-ope-not.htm), [SCP/SFTP–TFTP yan etkileri](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/dis-tft-aut-tft-enh-sec.htm), [6100 Fundamentals](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/fundamentals_4100i-6000-6100.pdf), [HPE 1950 User Guide](https://support.hpe.com/hpesc/public/api/document/c04657809), [HPE ürün/sürüm ayrımı](https://arubanetworking.hpe.com/techdocs/comware/sftwr/HPE_Recommended_Minimum_Software_Versions_Feb_2026.pdf).

## Dosyalar ve yetki

Yönetici dosya ve plan oluşturur, başlatır, etkinleştirir veya durdurur. Operatör firmware gruplarını düzenleyebilir. Görüntüleyici metadata okuyabilir; firmware dosyasını indiremez veya değiştiremez. Tüm yazma uçları mevcut oturum/rol ve `X-Netrix-Request`/Origin kontrollerinden geçer.

Dosya önce metadata kaydıyla oluşturulur; gövde ayrı PUT isteğinde belleğe tamamen alınmadan akar. Dosya adı UUID tabanlıdır, kullanıcı dosya yolu belirleyemez. Üreticinin yayımladığı SHA-256 zorunludur; sunucuda hesaplanan değer eşleşmedikçe imaj ready olmaz. Bu karşılaştırma bağımsız üretici imzası doğrulaması yapıldığı iddiası değildir. Uygulama imajdaki yazılımı çalıştırmaz. Uyumluluk aile ve tam ürün kodu/model listesi üzerinden doğrulanır; AOS-S'de çalışan K/KB/WB/WC öneki ayrıca eşleştirilir.

Hazır imaj değiştirilemez. İşlem geçmişinin referans verdiği dosya ve firmware öncesi konfigürasyon yedeği korunur. Dosyalar `/data/firmware` altında, veritabanı dışında kalıcı tutulur. Tek dosya varsayılan 2 GiB, depo 20 GiB ve eşzamanlı yükleme dört istekle sınırlıdır. En az 1 GiB boş disk koruması vardır. Başarısız yükleme hazır dosya oluşturmaz; aynı metadata kaydı üzerinden yeniden denenebilir.

## Gruplar ve planlar

Grup adları ve sıraları sabit değildir. Aynı modeldeki farklı cihazlar işletim rollerine göre ayrı gruplarda bulunabilir. Bir cihaz yalnızca bir firmware grubuna ait olabilir; başka gruba alınmadan önce mevcut üyeliği kaldırılmalıdır. Bir planda aynı cihaz iki kez yer alamaz. Plan oluşturulurken grup adları, imajlar, sıra ve cihaz üyelikleri sabitlenir; sonraki grup değişiklikleri bu planı değiştirmez.

Plan taslaktır; oluşturmak cihaz işlemi başlatmaz. Yönetici **Başlat** ile açıkça tetikler. Zamanlama saat dilimli UTC saklanır, kullanıcı yerel saat seçer. Gruplar sırayla, grup içindeki cihazlar 1–4 sınırlı eşzamanlılıkla çalışır. Önceki grubun gerekli tüm sonuçları tamamlanmadan sonraki grup başlamaz. Başarısızlık/belirsizlikte yeni hedefler bekler.

- **Yalnız ön kontrol:** SSH erişimi, dosya bütünlüğü, kayıtlı model uyumu, çalışan sürüm ve imaj alanı okunur. Firmware yazılmaz; ayrı bir aktarım/etkinleştirme planı gerekir.
- **Aktar ve açılışa hazırla:** Ön kontrol → şifreli konfigürasyon yedeği → aktarım/yazım doğrulaması. Yeniden başlatılmaz. HP 1950'nin bu komutu sonraki açılış imajını da değiştirir.
- **Aktar ve yeniden başlat:** Önceki aşamalar → yeniden başlatma → çalışan hedef sürümü ve yazılım alanı doğrulaması. Ardışık iki başarılı SSH okuması beklenir; ping tek başına başarı sayılmaz.
- Hazırlanmış plan **Yeniden başlat ve etkinleştir** ile ayrı onaydan sonra çalışır.

AOS-S'de SFTP dönüşü flash yazımının bitmesi sayılmaz. Aktarımdan önceki olay kayıtlarıyla karşılaştırılarak yazılım alanının güncellendiğini gösteren yeni olay ve doğru `show flash` sürümü beklenir. Primary/secondary seçimi çalışan yazılım alanının tersidir; bilinmeyen yazılım alanının üzerine yazılmaz. 1950 main/current/backup kavramları primary/secondary gibi sunulmaz. BootROM nedeniyle yeniden başlatma birden fazla kez gerçekleşebilir; sürüm doğrulama 20 dakikaya kadar bekler.

Aynı cihazı iki firmware planı kullanamaz. Mevcut normal worker cihazda firmware çalışırken yeni cihaz işi almaz; daha önce başlamış cihaz işi firmware başlamadan beklenir. Keşif sonuçları IPAM'a aktarılmaz; firmware kapsamı envanter keşif CIDR yetkisine bağlanmaz. Aktif envanter kaydı ve geçerli SSH profili gerekir.

## Kesinti ve kurtarma

Worker yazma veya reboot komutunu vermeden önce aşamayı kalıcı kaydeder. Süreç bu sınırdan sonra kesilirse komut otomatik tekrarlanmaz; attention sonucu ve cihaz kilidi korunur. Ön kontrol/yedek gibi yazma öncesi başarısız hedefler kullanıcı isteğiyle yeniden denenebilir. **Sonraki işlemleri durdur** başlamış flash yazımını kesmez.

**Sürümü yeniden doğrula** yalnız salt okunur hedef doğrulamasıdır; diğer bekleyen yazmaları kendiliğinden başlatmaz. Plan, doğrulama isteği içinde kilitlenip duraklatılır; worker henüz hata durumunu plana yansıtmamış olsa da sonraki gruplar başlamaz. Asıl işlem hatası `operation_error`, son salt okunur kontrolün hatası `verification_error` olarak ayrı tutulur; sürüm uyuşmazlığı ilk aktarım/yazma hatasının yerine geçmez. Önceki ve hedef sürüm, imaj alanları, hata kodu, zamanlar ve şifreli konfigürasyon yedeği referansı korunur. Yönetici konsol/SSH ile kurtarmayı ayrıca tamamladıysa cihaz adını yazarak **Manuel kurtarmayı tamamla** ile kilidi kaldırabilir. Bu eylem başarısız kurulumu başarılı göstermez; audit kaydı üretir.

Otomatik downgrade veya uzaktan garantili kurtarma vaat edilmez. Eski imaj alanı tek başına eski sürüme uyumlu konfigürasyon garantisi değildir. Stack/VSF ve çift management module yönetim hedefleri fiziksel üyeler gibi farklı gruplara ayrılmamalıdır. Bu sürüm sıfır kesinti/ISSU sunmaz. Gerçek model/sürüm/topoloji kombinasyonu işletmeci tarafından üretici notlarıyla doğrulanmalıdır; sahte istemci ve loopback testleri donanım yükseltme sertifikası değildir.

## Tek container içinde dosya servisi

`netrix-firmware`, mevcut `netrix` container'ındaki Supervisor süreçlerinden biridir. Ayrı Redis/worker/transfer container'ı eklenmez. API yalnız indeksli ve sayfalı metadata okur; firmware sayfası ayrı JavaScript/CSS parçası olarak yüklenir. Plan ayrıntıları da sayfalıdır. Dosya hashing'i event loop dışında yapılır. İş kaydının kaynağı MariaDB'dir; Redis yalnız heartbeat ve yenileme bildirimi içindir.

SCP/SFTP servisi salt okunurdur; shell, serbest komut çalıştırma ve forwarding sunmaz. SCP komutları aynı tek dosya erişimini uygulayan protokol işleyicisine gider; yükleme ve yol aşımı reddedilir. Rastgele süreli hesap yalnız o işin cihaz IP'sine, tek dosyaya ve çalışan aktarım aşamasına erişir; parola yalnız hash olarak tutulur. Kaynak SSH host anahtarı cihazın gösterdiği fingerprint ile doğrulanır. TFTP kullanıcı doğrulaması sunmadığı için yalnız süreli, tahmin edilemez `netrix-fw-<rastgele>.ipe` dosyası ve ilgili hedef IP kabul edilir. Dizin listeleme/yazma yoktur. Bu hizmetler mevcut `netrix_netrix-redis` volume'undaki `/data/firmware` dizinini kullanır; secret dosyaları veya SSH anahtar içerikleri Git'e girmez.

Ortam değişkenleri: `NETRIX_FIRMWARE_ADVERTISE_HOST` cihazın erişeceği gerçek LAN IP'si; `NETRIX_FIRMWARE_BIND_IP` host'ta dinlenecek IP; `NETRIX_FIRMWARE_SFTP_PORT` SCP ve SFTP için ortak SSH portudur, varsayılan 2222; `NETRIX_FIRMWARE_TFTP_PUBLIC_PORT` varsayılan 69. Geliştirmede host publish varsayılan loopback'tir. TFTP veri portları UDP/20000–20015'tir.

Dağıtım sunucusunda UDP/69 mevcut PXE servisine aittir. NETRIX, UDP/1069 yayımlar; `scripts/firmware_tftp_dispatch.py` host NAT tablosunda sadece `00 01` RRQ opcode'u ardından `netrix-fw-` dosya önekini taşıyan, host'un belirli LAN IP'sine gelen UDP/69 isteklerini NETRIX container'ına yönlendirir. Diğer TFTP istekleri ve mevcut PXE kuralları değişmez. `netrix-firmware-dispatch.timer`, container adresi değiştiğinde bu dar yönlendirmeyi yeniler. Bu bir host ağ kuralıdır, ek uygulama container'ı değildir.

Nginx'te yalnız NETRIX imaj aktarım yolunun gövde sınırı 2 GiB'ye yükseltilir, istek tamponlaması kapatılır. Diğer NETRIX uçları ve mevcut siteler korunur. `nginx -t` başarılı olmadan reload yapılmaz.

## Doğrulama

- `tests/test_firmware.py`: hash/uyumluluk, yetki, sıra, çakışan planlar, aşama sınırı, iptal, yeniden başlatma sonrası belirsizlik ve salt okunur uzlaştırma.
- `tests/test_firmware_adapters.py`: sahte CLI/SFTP ile kaynak anahtarı, parçalı istemler, AOS-S flash bitişi, CX default VRF ve HP 1950 komutları.
- `scripts/firmware_transfer_check.py`: geçici DB ve loopback üzerinde gerçek SFTP/TFTP ikili aktarımı ve reddetme kontrolleri.
- `scripts/firmware_mariadb_check.py`: yalnız atılabilir `netrix_test` üzerinde migration, FK/CHECK/UNIQUE, UTC ve eşzamanlı planlar.
- `scripts/firmware_browser_check.py`: yalnız geçici fixture üzerinde 1.000 cihazla sayfalama, dosya yükleme, grup/sıra/onay, masaüstü/mobil hizalama, açık/koyu tema ve Axe kontrolü.


## CX 6100 aktarım düzeltmesi — 3 Kasım 2026

PL.10.17.1030 çalışan bir 6100, CLI yardımında SFTP listelenmesine rağmen gerçek firmware indirmesini `Download failed with exit code 1: Unsupported protocol` ile reddetti (cihaz olayları 4413/4403). Salt okunur `show images` ve `show boot-history` kontrolünde eski çalışan sürüm, aktif yazılım alanı ve önceki primary imajı korundu; yeni bir reboot yoktu. Bu adaptör artık SSH ile `copy scp://... {primary|secondary} vrf default` kullanır. Bu bulgu bütün CX sürümlerinin SFTP desteklemediği anlamına gelmez. Cihaz HTTPS'i açılmaz ve şifresiz protokole otomatik geçilmez.

SCP kaynağı, mevcut geçici kullanıcı/parola hash'i, hedef cihaz IP'si, süre ve tek dosya sınırlarını kullanır. Aynı sunucunun SFTP alt sistemi AOS-S akışı ve SSH istemci uyumluluğu için korunur. Gerçek döngüsel SCP/SFTP testinde ikili dosya eşitliği, upload/shell/silme/yol aşımı reddi ayrıca doğrulanır.


## CX doğrulaması ve Firmware hizalaması — 3 Kasım 2026

SCP aktarımı sonrası cihazın 4401 olayı primary alanında PL.10.18.1010 kurulumunu doğrularken tek seferlik anlık okuma hata verdi. Sonraki salt okunur okumada sürüm ve SHA-256 depo dosyasıyla eşleşti; çalışan secondary sürüm değişmedi ve cihaz yeniden başlamadı. CX adaptörü aktarım komutunu yinelemeden `show images` okumasını en fazla 60 saniye, iki saniyelik aralıklarla yeniler. Doğru alanın tam sürümü ve SHA-256 değeri birlikte eşleşmeden yeniden başlatmaya geçilmez. Eski hata anındaki ham çıktı saklanmadığından ilk okumanın içeriği geriye dönük olarak belirlenemedi.

Arayüzde primary/secondary bölümleri **yazılım alanı** olarak adlandırılır. Altı Firmware ekranının tabloları ortak hücre başlangıçları, satır üst hizaları ve bağlantı girintilerini kullanır. Form etiketleri ve kontroller aynı sütun ekseninde kalır; dar ekranlarda tablolar kendi alanında yatay kaydırılır. Dolu plan ve geçmiş tabloları, hata ayrıntıları ve formlar masaüstü/mobil, açık/koyu tema ile ölçülür. UI UX Pro Max UX verisindeki tablo taşması ve metin yeniden akışı önerileri uygulandı; React veri aramasında hizalamaya özgü doğrulanmış eşleşme bulunamadığından uygulamanın mevcut CSS grid/flex düzeni esas alındı.

Bu düzeltmenin doğrulaması: firmware, adaptör, Aruba terminali ve sürüm ayrıştırma testlerinden **94 test geçti**. 375, 768, 1024 ve 1440 px genişliklerde açık/koyu tema dahil **77 tarayıcı görünümü** hizalama, taşma ve Axe kontrollerini geçti. Python Ruff, frontend TypeScript/Vite derlemesi ve Prettier kontrolü başarılıdır. Bu ölçümler geçici test verisi üzerinde yapılır; gerçek cihazda yeniden başlatma testi yürütülmemiştir.

## Hazır CX imajının tekrar aktarılmaması — 3 Kasım 2026

6100 yeni planı, önceki planda primary alanına yazılıp SHA-256 ile doğrulanmış aynı imajı yeniden aktarabiliyordu. CX hazırlama akışı artık her zaman güncel konfigürasyon yedeğini alır ve ardından çalışan sürümü, aktif alanı ve `show images` çıktısını yeniden okur. Etkin olmayan hedef alanın tam sürümü **ve SHA-256** depo dosyasıyla eşleşiyorsa yeni SCP hesabı açılmaz ve dosya yeniden yazılmaz. `evidence.transfer_reused=true` saklanır; bu denemede yeni veri taşınmadığı için `transfer_bytes=0` olur. Yalnız sürüm adı eşleşmesi yeterli değildir. Hash/sürüm eksikliği veya uyuşmazlığı normal SCP aktarımına gider. Yedek sırasında çalışan sürüm veya aktif alan değişirse işlem yazmadan durur.

Hazırlama planı bu durumda da yeniden başlatmaz. Yükseltme yalnız mevcut kullanıcı başlatma/kesinti onayıyla ilerler ve açılış sonrası sürüm doğrulamasını korur. Bu iyileştirme ilk kez gönderilen bir dosyanın fiziksel aktarım hızını artırdığı iddiasını taşımaz; doğrulanmış aynı dosyanın gereksiz tekrarını kaldırır.

Canlı plandaki `preflight_at=2026-11-03T17:26:32.768756Z` ile `staged_at=2026-11-03T17:28:27.240294Z` arasındaki süre yaklaşık 114,5 saniyedir. Bu aralık konfigürasyon yedeği, aktarım, cihazda yazım ve son okuma işlemlerini birlikte kapsar; saf ağ hızı hesaplamak için kullanılamaz. Aynı sunucuda gerçek SCP işleyicisiyle, geçici dosya/kimlik ve yalnız loopback üzerinden yapılan iki 32 MiB okuma 0,427/0,430 saniye sürdü (74,9/74,3 MiB/s); hash'ler eşleşti. Bu test üretim erişim kayıtlarını veya gerçek cihazları kullanmadı; DB yetkilendirme/ilerleme kaydı yerine süreç içi test değerleri kullanıldığı için uçtan uca üretim aktarım hızı değildir.

Doğrulama: 103 hedefli firmware/adaptör/terminal/sürüm testi geçti. Yeni regresyonlar hem hazırlama hem yükseltmede tekrar aktarımını atlamayı; hash yokluğu/uyuşmazlığını, diğer alandaki imajı, yedek sırasında değişen aktif alan/sürümü ve yedek başarısızlığında yazmanın engellenmesini kapsar. Ruff kontrolü ve format doğrulaması başarılıdır.


## Firmware gruplarında toplu seçim ve tek üyelik — 3 Kasım 2026

Grup oluşturma/düzenleme penceresi, görünen sayfadaki uygun cihazların seçimini ve filtreye uyan tüm uygun cihazların tek istekle seçimini destekler. Sayfa/filtre değişikliği mevcut seçimleri silmez; **Seçimleri temizle** bütün seçimi kaldırır. Toplu seçim yalnız kimlikleri okur ve tüm gruplarda geçerli mevcut 1000 cihaz sınırını aşınca filtreyi daraltmayı ister; sonuçları sessizce kesmez. Filtre alanında Enter tuşu grubu erken kaydetmez.

Gelişmiş filtreler: ad/IP/model/üretici araması, cihaz ailesi, model/ürün kodu, üretici, çalışan sürüm, metin olarak IP adresi öneki, yönetim VLAN’ı, atanmış konum ve grup üyeliği. IP öneki bir CIDR hesaplaması değildir. Filtreler sunucuda birleşir; sayfalı sonuç ve toplu seçim aynı koşulları kullanır. Üyelik bilgisi toplu sorguyla gelir; her cihaz için ayrı grup sorgusu yapılmaz. Başka gruba ait cihazın mevcut grubu görünür, seçimi kapalıdır. Düzenlenen grubun mevcut üyeleri seçilebilir kalır.

Kayıt işlemi servis katmanında cihazları sabit sırada kilitler; başka firmware grubunun üyesi için HTTP 409 döner. Çakışan güncelleme ad/açıklama/üyelikleri kısmen değiştirmez. Veritabanındaki `uq_firmware_member_device` benzersiz kısıtı, eşzamanlı istek ve doğrudan DB yazımında da tek üyelik sağlar. Alembic `20261103_39`, mevcut çakışmaları keyfi seçimle temizlemez; açık çözüm ister. Kullanıcının seçimiyle `HP-SW-CO-02-A-00-01` cihazı **6100** grubunda kalır; **6100-02-LOBİ** grubundaki yalnız bu üyelik kaldırılır. Grup ve eski planların sabitlenmiş ad/cihaz/sıra bilgileri korunur.

İlgili kontroller `tests/test_firmware_groups.py`, atılabilir MariaDB için `scripts/firmware_groups_mariadb_check.py` ve yalnız geçici tarayıcı fixture’ı kullanan `scripts/firmware_group_browser_check.py` içindedir. Yeni bağımlılık veya gerçek cihaz işlemi eklenmez.
