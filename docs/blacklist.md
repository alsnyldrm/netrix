# Kara Liste

Kara Liste, **IP kayıtları** ve **ACL grupları** ekranlarından yönetilir. Gruplar merkezi envantere referans verir. Bir IP birden fazla gruba bağlanabilir. **Gönder → Cihazlara gönder**, seçili cihazlarda yeni ACL oluşturulmasını ve tüm fiziksel portlarda giriş yönüne uygulanmasını worker kuyruğuna alır.

## Kullanım

1. Grubu oluşturun, cihazları seçin ve her aile için ACL türü ile adını veya numarasını girin. Mevcut SQL grupları da kullanılabilir.
2. Bir IPv4 adresini ve hedef grupları kaydedin.
3. Satırdaki **Gönder** eylemini açıp hedef cihaz sayısını inceleyin ve **Cihazlara gönder** düğmesine basın.
4. **Sonuçlar** penceresinde her cihazın aşamasını, durumunu, port sayısını ve hatasını izleyin. **Durdur** ilerleyen komutları keser. Uygulanmış kurallar geçerliliğini korur. Tekrar **Gönder**, cihazın mevcut durumunu okuyarak eksik adımları tamamlar.

Liste/ayrıntı açılışı ve kayıt değişiklikleri pasiftir. Gönderim yalnız açık kullanıcı eylemiyle başlar. Sayfa açıkken devam eden işler WebSocket ve görünür sayfada beş saniyelik SQL yenilemesiyle izlenir. Arayüz kapandığında worker devam eder.

Grup tanımlarını yöneticiler, IP kayıtlarını ve gönderimleri operatörler/yöneticiler yönetir. Worker kullanıcı yetkisini, cihazın yaşam döngüsünü, modelini ve SSH hedefini bağlantı öncesinde yeniden doğrular. Firewall, router, gateway, VIP ve arşivlenmiş cihazlar kapsam dışıdır. SSH profili ve kayıtlı host anahtarı politikası kullanılır. Gerçek cihaza yazma test için otomatik tetiklenmez.

## Uygulama davranışı

- Engel kaynak IPv4 adresine ve giriş yönüne uygulanır. IPv6 gönderimi açık hatayla reddedilir.
- NETRIX, deny kurallarını son izin kuralından önce ekler. Diğer adreslerin iletişimi için son izin kuralı korunur.
- Tüm fiziksel portlar cihazdan SSH ile okunur. LAG üyeleri ilgili LAG arayüzü üzerinden kapsanır. Eksik/çelişkili port listesinde yazma başlamaz.
- Hedef portta başka ACL varsa cihazda ilk yazma başlamadan çakışma raporlanır. Mevcut politika otomatik değiştirilmez. Aynı cihazın tüm portları için farklı ACL isteyen grup tanımları gönderim öncesinde reddedilir.
- Yeni ACL’ler `NETRIX-BLACKLIST` açıklamasıyla işaretlenir. Aynı kimlikte başka bir ACL veya beklenmeyen kural içeriği varsa işlem durur.
- 7205’te session ACL, IP listesini bir `netdestination` nesnesi üzerinden kullanır. Bu yardımcı nesnenin adı ACL kimliğinin hash’inden `nxbl_…` biçiminde üretilir. IP eklerken izin kuralını kaldırmak gerekmez.
- Tekrar gönderim önce güncel konfigürasyonu okur. Eşdeğer deny çoğaltılmaz. Kısmi uygulama sonrası eksik port bağlantıları ve kayıt doğrulaması tamamlanır.
- Başarı için hem çalışan hem kalıcı konfigürasyonda deny, son izin ve tüm port bağlantıları doğrulanır. Bu durum gönderim anındaki konfigürasyon doğrulamasıdır. Trafik üretip uçtan uca paket testi yapılmaz.
- Cihaz başına tek ACL gönderimi yürür. Diğer cihaz işleriyle çakışma kuyrukta bekletilir. Mevcut worker kapasitesi en fazla dört arka plan işidir. SSH okuması 45 saniye, cihaz işi toplam 600 saniye ile sınırlıdır.
- İptal her yazma komutu öncesinde kontrol edilir. Zaman aşımı ve worker kaybında mevcut sınırlı yeniden deneme davranışı uygulanır. Her deneme güncel cihaz okumasıyla yeni plan hazırlar.
- Gönderim geçmişi bulunan bir kaydın IP adresi değiştirilemez. Yeni IP ayrı kayıt olarak eklenir. Bu sürüm ekleme ve tekrar gönderimi kapsar. Önceki engellerin kaldırılması uygulanmaz.

## Kalıcı kayıtlar

Veri sahibi `kara_liste` şemasıdır. `acl_groups`, `blacklist_entries` ve ilişki tablolarına ek olarak `blacklist_deliveries`, değişmez hedef/IP/ACL tanımını cihaz ve `operasyon.jobs` kaydıyla ilişkilendirir. Her cihaz ayrı iş olduğundan bir cihazın hatası diğer cihaz sonuçlarını kaybettirmez. Aynı aktif gönderimin tekrar isteği aynı iş kimliğini döndürür. İş ve teslim kaydı aynı SQL transaction içinde oluşturulur. Kuyruk ve durumun sahibi SQL’dir, Redis bildirim için kullanılır.

PostgreSQL migration’ları `20261122_01` ve `20261122_02` olur. Cihaz kimliği yalnız `envanter.devices` içinde tutulur. Protokol kaynağı veya IPAM tablosuna yazılmaz. Ham SSH çıktısı, konfigürasyon sırları ve erişim parolaları teslim kayıtlarına veya loglara eklenmez.

## Üretici araştırması

Model adının yanında işletim sistemi ve çalışan sürüm de komut seçimini belirler. Aşağıdaki komut biçimleri araştırma sonucudur. Kullanıcı ACL adını ve varsa numarasını girer. Örneklerdeki adlar ve sıra numaraları otomatik atama kararı değildir.

| Cihaz | İşletim sistemi ve ACL kimliği | Belgelenmiş komut ailesi |
| --- | --- | --- |
| Aruba 5412 | zl için K/ProVision, R zl2 için KB/ArubaOS-Switch. Standart ACL 1–99, genişletilmiş 100–199 veya isimli ACL | `ip access-list extended <ACL>` ve kaynak IP’yi engelleyen ACE |
| Aruba 5406 | 5412 ile aynı OS ayrımı ve kimlik kuralları | Aynı AOS-S ACL komut ailesi |
| Aruba 2930F/M | WC/ArubaOS-Switch. Standart veya genişletilmiş ACL | Aynı AOS-S ACL komut ailesi |
| Aruba 6100 | PL/AOS-CX. İsimli IPv4 ACL | `access-list ip <ACL>`, sıra numarasıyla deny kuralı |
| Aruba 7205 | ArubaOS. İsimli session ACL | `ip access-list session <ACL>`, host kaynağı için deny kuralı |
| HP 1950 | Comware 7. Temel ACL 2000–2999, gelişmiş 3000–3999. İsim isteğe bağlı | Comware referanslarında ACL/rule komut ailesi. 1950’nin sınırlı SSH CLI desteği ayrıca değerlendirilir |

5412/5406 zl ve R zl2 aileleri farklı sürüm kılavuzlarıyla kontrol edilmelidir. AOS-S listelerinde sıralama ve örtük deny davranışı önemlidir. Kaynak IP’yi engelleyen bir kayıt, kendisinden önceki izin kuralı nedeniyle etkisiz kalabilir. İlk uygulama öncesinde mevcut ACL ve bağlandığı port/VLAN okunmalıdır. [HP 5400zl erişim güvenliği kılavuzu](https://ftp.hp.com/pub/networking/software/3500-5400-6200-ASG-0207-K.12.XX-Book.pdf), [5400R 16.11 kılavuzu](https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.11/Aruba%203810M5400R%20Access%20Security%20Guide%20for%20AOS-S%2016.11.pdf), [2930F/M 16.11 kılavuzu](https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.11/Aruba%202930MF%20Access%20Security%20Guide%20for%20AOS-S%2016.11.pdf).

6100’de ACL oluşturma ve arayüze bağlama ayrı işlemlerdir. IPv4 ACL’nin port/VLAN giriş yönü desteklenir. Belgede çıkış yönü desteği 6100 için MAC ACL ile sınırlıdır. Var olan aynı tür ACL bağlantısını değiştirmek mevcut erişim politikasını etkileyebilir. [IPv4 ACL komutu](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/acls_4100i-6000-6100/Content/Chp_ACLs/ACLs_cmds/acc-lis-ip.htm), [arayüz/LAG bağlantısı](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/acls_4100i-6000-6100/Content/Chp_ACLs/ACLs_cmds/app-acc-lis-to-int-lag.htm), [VLAN bağlantısı](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.13/HTML/acls_4100i-6000-6100/Content/Chp_ACLs/ACLs_cmds/app-acc-lis-to-vla.htm).

7205 session ACL kuralları ilk eşleşme sırasıyla değerlendirilir. ACL’nin rol/politika bağlantısı da etkinliğini belirler. Kaynak adres engeli için belgelenmiş biçim `host <IP> any any deny` olur. Bu ifade kaynak yönünü tanımlar. Hedef yönünün de engellenmesi ayrı kural gerektirir. [ArubaOS session ACL komut referansı](https://arubanetworking.hpe.com/techdocs/ArubaOS/oxygen/AOS-8%20Command%20Line%20Interface%20Guide/i/ip-access-list-session.html).

HPE 1950 kullanıcı kılavuzu, `xtd-cli-mode` modunu destek personelinin sorun giderme aracı olarak tanımlar. Genel Comware 7 komutlarının varlığı, her 1950 yazılımında rutin SSH yazma desteği kanıtı değildir. NETRIX’in mevcut HP adaptörü ayrı, şifreli kasa parolasıyla bu oturum modunu kullanabilir. Kara Liste motoru için ACL komutu ve çıktı doğrulaması ayrıca gerekir. Gömülü parola kullanılmaz. [HPE 1950 ürün belgesi](https://support.hpe.com/hpesc/public/docDisplay?docId=c04686146&docLocale=en_US&page=GUID-F3BA82F7-A27B-4C0C-A9CB-FA621616A624.html), [HPE tarafından yazılmış 1950 kullanıcı kılavuzunun kopyası, s.154](https://www.intesiscon.com/ficheros/manuales-tecnicos/251-HPE-c04657809-HPE-OfficeConnect-1950-Switch-Series-User-Guide.pdf), [üretici Comware 7 ACL komut referansı](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/11/202210/1709612_294551_0.htm).

## Port uygulaması için ek üretici başvuruları

AOS-S port ve trunk bağlantısı, CX fiziksel/LAG bağlantısı, ArubaOS Ethernet/port-channel session ACL bağlantısı ve Comware paket filtre komutları incelendi. 6100 IPv4 çıkış yönü kısıtı nedeniyle bütün ailelerde kaynak adres için giriş yönü kullanılır. [AOS-S port ACL](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/ASG/KB/content/asg%20kb/fil-inb-ipv-tra-per-por.htm), [CX port ve LAG ACL](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/acls_4100i-6000-6100/Content/Chp_ACLs/ACLs_cmds/app-acc-lis-to-int-lag.htm), [ArubaOS Ethernet](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/intrfc-gigaether.htm), [ArubaOS port-channel](https://arubanetworking.hpe.com/techdocs/ArubaOS/oxygen/AOS-8%20Command%20Line%20Interface%20Guide/i/interface-port-channel.html), [ArubaOS netdestination](https://arubanetworking.hpe.com/techdocs/ArubaOS/oxygen/AOS-8%20Command%20Line%20Interface%20Guide/GUID-607383DC-CFE6-4B0E-911A-8743AB3EB4DF.html), [Comware ACL ve paket filtre](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/11/202210/1709612_294551_0.htm).

## Doğrulama

Sahte SSH cihazlarıyla 5412/5406, 2930, 6100, 7205 ve HP 1950 için ilk ACL, ikinci IP, tekrar gönderim, mevcut ACL çakışması ve tüm port bağlantıları sınandı. Normal worker girişinden başarılı gönderim, port hatası, kalıcı kayıt uyuşmazlığı, iptal, iptal sonrası tekrar gönderim, gateway elemesi ve meşgul cihazın diğer hedefleri bekletmemesi doğrulandı.

Yerel fixture tarayıcısında 1440, 768 ve 375 piksel açık/koyu temada 48 görünüm ve son hizalama için altı ek görünüm kontrol edildi. Gönderim, sonuçlar ve durdurma API üzerinden denendi. Axe ihlali veya JavaScript hatası bulunmadı. Gerçek cihazlarda ACL yazma ve paket engelleme testi yapılmadı.

Gönderime yönelik son hedefli koşuda 31 test geçti. Geniş regresyon koşusunda 166 test geçti, ayrı PostgreSQL test veritabanı gerektiren iki test atlandı. Sonrasında eklenen controller/config-mode istemleri ve modüler VSF portları hedefli koşuda doğrulandı. Değişen Python dosyalarının Ruff, Git boşluk ve frontend üretim derlemesi kontrolleri geçti. Vite’ın mevcut ana paket boyutu uyarısı sürüyor.
