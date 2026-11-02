# Firmware yönetimi

NETRIX'in **Firmware** bölümü sol menüde **IP adres yönetimi** bölümünün hemen altındadır. Cihazlar, Firmware deposu, Gruplar, Güncelleme planları, İşlem geçmişi ve Aktarım ve kurtarma ekranlarını kapsar. Cihaz envanteri ortaktır; firmware grupları yedekleme gruplarından bağımsızdır. Kurulum boş başlar; örnek cihaz, imaj, grup veya başarılı işlem eklenmez.

## Kapsam ve protokoller

Cihazların HTTPS/WebUI/REST servisi kullanılmaz ve kendiliğinden açılıp kapatılmaz. Uygulamanın kullanıcıya sunduğu mevcut HTTPS erişimi korunur.

| Adaptör | Komut / dosya yolu | İmaj |
| --- | --- | --- |
| Aruba 54xx, 2900 (5400/5400R, 2920/2930) | SSH komut oturumu; SFTP ile `/os/primary` veya `/os/secondary` alanına gönderme | Modele uygun `.swi`, K/KB/WB/WC ailesi |
| Aruba 61xx (6100) | SSH komut oturumu; cihazın süreli SFTP hesabıyla NETRIX'ten çekmesi, `vrf default` | PL ailesi `.swi` |
| HP 1950 | SSH sınırlı CLI; `upgrade <sunucu> runtime file <dosya>.ipe` ile TFTP çekme | Ürün koduna uygun `.ipe` |

AOS-S ön kontrolde SFTP alt sistemi salt okunur sınanır. Kapalıysa yalnız planda ayrıca onaylanan **SFTP erişimini aç** seçeneği, yedekten sonra `ip ssh filetransfer` uygular; TFTP’nin kapanacağı kullanıcıya gösterilir. Sessiz protokol değişikliği yapılmaz.

1950 firmware işlemi `xtd-cli-mode` kullanmaz. Ancak mevcut konfigürasyon yedek adaptörü için ayrıca gerekli olabilen genişletilmiş CLI erişimi korunur; yedek alınamazsa firmware yazımı başlamaz. JH295A R51xx ailesi, diğer OfficeConnect 1950 SKU'larıyla karıştırılmaz. Dosya sunucusu erişiminin cihaz tarafından sağlanması gerekir. 7200 controller, AOS8→10 geçişi ve ISSU bu firmware adaptörlerinin kapsamına dahil değildir.

Kaynaklar: [AOS-S dosya sistemi ve flash yazımı](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/scp-ope-not.htm), [SCP/SFTP–TFTP yan etkileri](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/KB/content/kb/dis-tft-aut-tft-enh-sec.htm), [6100 Fundamentals](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/PDF/fundamentals_4100i-6000-6100.pdf), [HPE 1950 User Guide](https://support.hpe.com/hpesc/public/api/document/c04657809), [HPE ürün/sürüm ayrımı](https://arubanetworking.hpe.com/techdocs/comware/sftwr/HPE_Recommended_Minimum_Software_Versions_Feb_2026.pdf).

## Dosyalar ve yetki

Yönetici dosya ve plan oluşturur, başlatır, etkinleştirir veya durdurur. Operatör firmware gruplarını düzenleyebilir. Görüntüleyici metadata okuyabilir; firmware dosyasını indiremez veya değiştiremez. Tüm yazma uçları mevcut oturum/rol ve `X-Netrix-Request`/Origin kontrollerinden geçer.

Dosya önce metadata kaydıyla oluşturulur; gövde ayrı PUT isteğinde belleğe tamamen alınmadan akar. Dosya adı UUID tabanlıdır, kullanıcı dosya yolu belirleyemez. Üreticinin yayımladığı SHA-256 zorunludur; sunucuda hesaplanan değer eşleşmedikçe imaj ready olmaz. Bu karşılaştırma bağımsız üretici imzası doğrulaması yapıldığı iddiası değildir. Uygulama imajdaki yazılımı çalıştırmaz. Uyumluluk aile ve tam ürün kodu/model listesi üzerinden doğrulanır; AOS-S'de çalışan K/KB/WB/WC öneki ayrıca eşleştirilir.

Hazır imaj değiştirilemez. İşlem geçmişinin referans verdiği dosya ve firmware öncesi konfigürasyon yedeği korunur. Dosyalar `/data/firmware` altında, veritabanı dışında kalıcı tutulur. Tek dosya varsayılan 2 GiB, depo 20 GiB ve eşzamanlı yükleme dört istekle sınırlıdır. En az 1 GiB boş disk koruması vardır. Başarısız yükleme hazır dosya oluşturmaz; aynı metadata kaydı üzerinden yeniden denenebilir.

## Gruplar ve planlar

Grup adları ve sıraları sabit değildir. Aynı model farklı işletim rollerine göre farklı gruplarda bulunabilir. Bir planda aynı cihaz iki kez yer alamaz. Plan oluşturulurken grup adları, imajlar, sıra ve cihaz üyelikleri sabitlenir; sonraki grup değişiklikleri bu planı değiştirmez.

Plan taslaktır; oluşturmak cihaz işlemi başlatmaz. Yönetici **Başlat** ile açıkça tetikler. Zamanlama saat dilimli UTC saklanır, kullanıcı yerel saat seçer. Gruplar sırayla, grup içindeki cihazlar 1–4 sınırlı eşzamanlılıkla çalışır. Önceki grubun gerekli tüm sonuçları tamamlanmadan sonraki grup başlamaz. Başarısızlık/belirsizlikte yeni hedefler bekler.

- **Yalnız ön kontrol:** SSH erişimi, dosya bütünlüğü, kayıtlı model uyumu, çalışan sürüm ve imaj alanı okunur. Firmware yazılmaz; ayrı bir aktarım/etkinleştirme planı gerekir.
- **Aktar ve açılışa hazırla:** Ön kontrol → şifreli konfigürasyon yedeği → aktarım/yazım doğrulaması. Yeniden başlatılmaz. HP 1950'nin bu komutu sonraki açılış imajını da değiştirir.
- **Aktar ve yeniden başlat:** Önceki aşamalar → yeniden başlatma → çalışan hedef sürümü ve banka doğrulaması. Ardışık iki başarılı SSH okuması beklenir; ping tek başına başarı sayılmaz.
- Hazırlanmış plan **Yeniden başlat ve etkinleştir** ile ayrı onaydan sonra çalışır.

AOS-S'de SFTP dönüşü flash yazımının bitmesi sayılmaz. Aktarımdan önceki olay kayıtlarıyla karşılaştırılarak yeni banka güncelleme olayı ve doğru `show flash` sürümü beklenir. Primary/secondary seçimi çalışan bankanın tersidir; bilinmeyen bankanın üzerine yazılmaz. 1950 main/current/backup kavramları primary/secondary gibi sunulmaz. BootROM nedeniyle yeniden başlatma birden fazla kez gerçekleşebilir; sürüm doğrulama 20 dakikaya kadar bekler.

Aynı cihazı iki firmware planı kullanamaz. Mevcut normal worker cihazda firmware çalışırken yeni cihaz işi almaz; daha önce başlamış cihaz işi firmware başlamadan beklenir. Keşif sonuçları IPAM'a aktarılmaz; firmware kapsamı envanter keşif CIDR yetkisine bağlanmaz. Aktif envanter kaydı ve geçerli SSH profili gerekir.

## Kesinti ve kurtarma

Worker yazma veya reboot komutunu vermeden önce aşamayı kalıcı kaydeder. Süreç bu sınırdan sonra kesilirse komut otomatik tekrarlanmaz; attention sonucu ve cihaz kilidi korunur. Ön kontrol/yedek gibi yazma öncesi başarısız hedefler kullanıcı isteğiyle yeniden denenebilir. **Sonraki işlemleri durdur** başlamış flash yazımını kesmez.

**Sürümü yeniden doğrula** yalnız salt okunur hedef doğrulamasıdır; diğer bekleyen yazmaları kendiliğinden başlatmaz. Önceki ve hedef sürüm, imaj alanları, hata kodu, zamanlar ve şifreli konfigürasyon yedeği referansı korunur. Yönetici konsol/SSH ile kurtarmayı ayrıca tamamladıysa cihaz adını yazarak **Manuel kurtarmayı tamamla** ile kilidi kaldırabilir. Bu eylem başarısız kurulumu başarılı göstermez; audit kaydı üretir.

Otomatik downgrade veya uzaktan garantili kurtarma vaat edilmez. Eski imaj alanı tek başına eski sürüme uyumlu konfigürasyon garantisi değildir. Stack/VSF ve çift management module yönetim hedefleri fiziksel üyeler gibi farklı gruplara ayrılmamalıdır. Bu sürüm sıfır kesinti/ISSU sunmaz. Gerçek model/sürüm/topoloji kombinasyonu işletmeci tarafından üretici notlarıyla doğrulanmalıdır; sahte istemci ve loopback testleri donanım yükseltme sertifikası değildir.

## Tek container içinde dosya servisi

`netrix-firmware`, mevcut `netrix` container'ındaki Supervisor süreçlerinden biridir. Ayrı Redis/worker/transfer container'ı eklenmez. API yalnız indeksli ve sayfalı metadata okur; firmware sayfası ayrı JavaScript/CSS parçası olarak yüklenir. Plan ayrıntıları da sayfalıdır. Dosya hashing'i event loop dışında yapılır. İş kaydının kaynağı MariaDB'dir; Redis yalnız heartbeat ve yenileme bildirimi içindir.

SFTP servisi salt okunur ve shell/exec/forwarding sunmaz. Rastgele süreli hesap yalnız o işin cihaz IP'sine, tek dosyaya ve çalışan aktarım aşamasına erişir; parola yalnız hash olarak tutulur. Kaynak SSH host anahtarı cihazın gösterdiği fingerprint ile doğrulanır. TFTP kullanıcı doğrulaması sunmadığı için yalnız süreli, tahmin edilemez `netrix-fw-<rastgele>.ipe` dosyası ve ilgili hedef IP kabul edilir. Dizin listeleme/yazma yoktur. Bu hizmetler mevcut `netrix_netrix-redis` volume'undaki `/data/firmware` dizinini kullanır; secret dosyaları veya SSH anahtar içerikleri Git'e girmez.

Ortam değişkenleri: `NETRIX_FIRMWARE_ADVERTISE_HOST` cihazın erişeceği gerçek LAN IP'si; `NETRIX_FIRMWARE_BIND_IP` host'ta dinlenecek IP; `NETRIX_FIRMWARE_SFTP_PORT` varsayılan 2222; `NETRIX_FIRMWARE_TFTP_PUBLIC_PORT` varsayılan 69. Geliştirmede host publish varsayılan loopback'tir. TFTP veri portları UDP/20000–20015'tir.

Dağıtım sunucusunda UDP/69 mevcut PXE servisine aittir. NETRIX, UDP/1069 yayımlar; `scripts/firmware_tftp_dispatch.py` host NAT tablosunda sadece `00 01` RRQ opcode'u ardından `netrix-fw-` dosya önekini taşıyan, host'un belirli LAN IP'sine gelen UDP/69 isteklerini NETRIX container'ına yönlendirir. Diğer TFTP istekleri ve mevcut PXE kuralları değişmez. `netrix-firmware-dispatch.timer`, container adresi değiştiğinde bu dar yönlendirmeyi yeniler. Bu bir host ağ kuralıdır, ek uygulama container'ı değildir.

Nginx'te yalnız NETRIX imaj aktarım yolunun gövde sınırı 2 GiB'ye yükseltilir, istek tamponlaması kapatılır. Diğer NETRIX uçları ve mevcut siteler korunur. `nginx -t` başarılı olmadan reload yapılmaz.

## Doğrulama

- `tests/test_firmware.py`: hash/uyumluluk, yetki, sıra, çakışan planlar, aşama sınırı, iptal, yeniden başlatma sonrası belirsizlik ve salt okunur uzlaştırma.
- `tests/test_firmware_adapters.py`: sahte CLI/SFTP ile kaynak anahtarı, parçalı istemler, AOS-S flash bitişi, CX default VRF ve HP 1950 komutları.
- `scripts/firmware_transfer_check.py`: geçici DB ve loopback üzerinde gerçek SFTP/TFTP ikili aktarımı ve reddetme kontrolleri.
- `scripts/firmware_mariadb_check.py`: yalnız atılabilir `netrix_test` üzerinde migration, FK/CHECK/UNIQUE, UTC ve eşzamanlı planlar.
- `scripts/firmware_browser_check.py`: yalnız geçici fixture üzerinde 1.000 cihazla sayfalama, dosya yükleme, grup/sıra/onay, masaüstü/mobil hizalama, açık/koyu tema ve Axe kontrolü.
