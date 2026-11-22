# Kara Liste

Kara Liste, **IP kayıtları**, **ACL grupları**, **Cihaz durumu** ve **Loglar** ekranlarından yönetilir. Gruplar merkezi envantere referans verir. Bir IP birden fazla gruba bağlanabilir. Cihazlara yazma, **istenen durum eşitlemesi** ile yapılır: her cihazdaki NETRIX ACL’si, cihazın etkin gruplarındaki etkin IP kayıtlarıyla birebir eşitlenir. Ekleme, kaldırma, silme, grup silme ve ACL kimliği değişikliği aynı güvenli motordan geçer.

## Kayıt durumları

| Kayıt durumu | Anlamı |
| --- | --- |
| Taslak (`draft`) | Hiç gönderilmedi; cihazlara yazılmaz. Toplu ekleme ve yeni kayıt taslak oluşturur. |
| Etkin (`active`) | **Gönder** ile istendi; gruplarındaki tüm cihazlarda engellenmelidir. |
| Kaldırıldı (`disabled`) | **Kaldır** veya süre dolumuyla engel cihazlardan kaldırılır; kayıt saklanır ve yeniden gönderilebilir. |
| Siliniyor (`deleting`) | **Sil** ile engel cihazlardan kaldırılır; tüm cihazlarda doğrulandıktan sonra kayıt silinir. Hiç uygulanmamış kayıt hemen silinir. |

Listede gösterilen durum, kayıt durumu ile cihazların son doğrulanmış içeriğinden hesaplanır: Engelli, Kısmi, Gönderilmeyi bekliyor, Kaldırılmayı bekliyor, Sırada, Uygulanıyor, Hata, Silinemedi ve Hedef yok. Uygulanmış veya sonucu belirsiz cihaz “belirsiz” olarak gösterilir; başarı varsayılmaz.

## Kullanım

1. **ACL grupları** ekranında grubu oluşturun, cihazları seçin ve her aile için ACL türü ile adını veya numarasını girin.
2. **IP kayıtları** ekranında **Yeni IP** veya **Toplu ekle** (en çok 500 adres; satır, boşluk, virgül veya noktalı virgülle) ile kayıt ekleyin. İsteğe bağlı bitiş zamanı süreli engel oluşturur.
3. Satırdaki veya seçim çubuğundaki **Gönder**, **Kaldır** ve **Sil** eylemleri onay penceresiyle çalışır. Arama ve durum filtresi yalnız SQL verisini süzer.
4. **Ayrıntı** penceresi her cihaz için istenen durumu, cihazdaki son doğrulanmış durumu, son işin aşamasını, eklenen/kaldırılan adresleri ve hatayı gösterir. **Durdur** ilerleyen komutları keser.
5. **ACL grupları** ekranındaki **Eşitle**, grup cihazlarını ve gruptan çıkarılmış ancak grubun engellerini hâlâ taşıyan cihazları eşitler. **Sil**, grubun engellerini cihazlardan kaldırır; doğrulandıktan sonra grubu siler. IP kayıtları korunur.
6. **Cihaz durumu** ekranı her cihazda istenen ve doğrulanmış ACL’yi, IP sayısını ve eşitlik durumunu gösterir. **Eşitle**, **Seçilenleri eşitle** ve **Bekleyenleri eşitle** açık eylemlerdir. Yönetici, erişilemeyen veya elle temizlenmiş cihaz için **Durumu unut** ile kayıtlı durumu cihaza bağlanmadan silebilir.

Liste, ayrıntı ve önizleme açılışı ile kayıt/grup düzenlemesi pasiftir. Cihaza yazma yalnız açık kullanıcı eylemiyle veya kullanıcının girdiği bitiş zamanıyla başlar. Zamanlayıcı süresi dolan etkin kaydı Kaldırıldı durumuna alır ve süreyi giren kullanıcının yetkisiyle kaldırma işini kuyruğa alır; yetki geçersizse iş kuyruğa alınmaz ve cihaz Eşitleme bekliyor görünür. Sayfa açıkken devam eden işler WebSocket ve görünür sayfada beş saniyelik SQL yenilemesiyle izlenir. Arayüz kapandığında worker devam eder.

Grup tanımlarını ve silmeyi yöneticiler; IP kayıtlarını, gönderim/kaldırma/silmeyi ve eşitlemeyi operatörler/yöneticiler yönetir. Worker kullanıcı yetkisini, cihazın yaşam döngüsünü, modelini ve SSH hedefini bağlantı öncesinde yeniden doğrular. Firewall, router, gateway, VIP ve arşivlenmiş cihazlar kapsam dışıdır. SSH profili ve kayıtlı host anahtarı politikası kullanılır. Gerçek cihaza yazma test için otomatik tetiklenmez.

## Uygulama davranışı

- Engel kaynak IPv4 adresine ve giriş yönüne uygulanır. IPv6 kaydı saklanabilir, gönderimi açık hatayla reddedilir.
- Eşitleme işi istenen içeriği bağlantı anında SQL’den okur. Cihazdaki NETRIX ACL’sinde eksik adresler eklenir, istenmeyen adresler ve aynı adresin yinelenen kuralları kaldırılır. Yeni kural eskisi kaldırılmadan önce eklenir. Deny kuralları son izin kuralından önce kalır.
- İstenen küme boşsa NETRIX ACL’si tüm portlardan ayrılır, ACL silinir; 7205’te `nxbl_…` adres nesnesi de silinir. Cihaz Kara Liste öncesi port durumuna döner. Syslog hedefi ve debug ayarları bu adımda değiştirilmez.
- Grup ACL kimliği değişirse veya cihaz gruptan çıkarılırsa önce eski NETRIX ACL’si kaldırılır, sonra yeni ACL oluşturulur. Bu aralıkta cihazda engel bulunmaz.
- Kaldırma komutları üretici biçimlerini kullanır: AOS-S/CX/ArubaOS için `no <sıra>`, `no ip access-group …`, `no apply access-list ip … in`, `no ip access-list …`, `no access-list ip …`, `no host <IP>`, `no netdestination …`; Comware için `undo rule <sıra>`, `undo packet-filter … inbound`, `undo acl number <N>`.
- Yalnız `NETRIX-BLACKLIST` işaretli ACL değiştirilir veya silinir. Aynı kimlikte başka ACL, beklenmeyen kural içeriği ya da ACL tanımı olmadan NETRIX bağlantısı görülürse ilk yazmadan önce işlem durur. Hedef portta başka ACL varsa mevcut politika otomatik değiştirilmez.
- Tüm fiziksel portlar cihazdan SSH ile okunur. LAG üyeleri ilgili LAG arayüzü üzerinden kapsanır. Eksik/çelişkili port listesinde yazma başlamaz.
- Başarı için çalışan ve kalıcı konfigürasyonda deny listesinin istenen kümeyle tam eşitliği, son izin kuralı ve tüm port bağlantıları; kaldırmada ACL, adres nesnesi ve tüm port bağlantılarının yokluğu doğrulanır. Kalıcı konfigürasyon zaten eşitse kayıt komutu tekrar çalıştırılmaz. Trafik üretip uçtan uca paket testi yapılmaz.
- Cihaz başına tek Kara Liste işi yürür. Aynı cihaz için yeni istek, sıradaki veya çalışan işi yeniden kullanır. Çalışan iş bitmeden önce SQL’deki istenen durumu yeniden okur ve en çok üç geçişte sonradan yapılan değişiklikleri de uygular. Diğer cihaz işleriyle çakışma kuyrukta bekletilir. SSH okuması 45 saniye, cihaz işi toplam 600 saniye ile sınırlıdır.
- İptal her yazma komutu öncesinde kontrol edilir. Zaman aşımı ve worker kaybında mevcut sınırlı yeniden deneme davranışı uygulanır. Her deneme güncel cihaz okumasıyla yeni plan hazırlar.
- Toplu kaldırma, silme, grup silme ve cihaz eşitlemesi uygun olmayan cihazları (SSH profili yok, firmware sürüyor, ACL çakışması, cihaz artık uygun değil) atlar ve gerekçeyle bildirir. Tek kayıt gönderimi bu durumlarda hiçbir işi kuyruğa almadan reddedilir.
- Uygulanmış veya etkin kaydın IP adresi değiştirilemez. Silinmekte olan kayıt veya grup düzenlenemez.

## Kalıcı kayıtlar

Veri sahibi `kara_liste` şemasıdır. `acl_groups` (`status`: `active`/`deleting`), `blacklist_entries` (`status`, `expires_at`, `updated_by`) ve ilişki tablolarına ek olarak:

- `blacklist_deliveries`, her eşitleme işini cihaz, `operasyon.jobs` kaydı, SSH hedef kimliği ve tetikleyiciyle ilişkilendirir. Kayıt silindiğinde geçmiş korunur, `entry_id` boşalır.
- `device_acl_states`, cihaz başına son doğrulanmış NETRIX ACL profilini, IP listesini ve katkı veren grupları tutar. Yazma başlarken satır `dirty` olur ve hedeflenen içerik `attempted` alanına yazılır; doğrulama başarısızsa bu içerik “belirsiz” sayılır. Kaldırma doğrulandığında satır silinir. Silinmekte olan kayıt ve grup, hiçbir cihaz durumu onları taşımadığında silinir.

Her cihaz ayrı iş olduğundan bir cihazın hatası diğer cihaz sonuçlarını kaybettirmez. İş ve teslim kaydı aynı SQL transaction içinde oluşturulur. Kuyruk ve durumun sahibi SQL’dir, Redis bildirim için kullanılır.

PostgreSQL migration’ları `20261122_01`, `20261122_02`, `20261122_03` ve `20261122_04` olur. `20261122_04`, önceki yalnız-ekleme motorunun başarılı teslimlerinden cihaz durumlarını oluşturur ve gönderilmiş kayıtları `active` yapar; başarısız teslimler belirsiz (`dirty`) durum olarak taşınır. `acl_logs`, cihazdan gelen ACL olaylarını tutar. Cihaz kimliği yalnız `envanter.devices` içinde tutulur. Protokol kaynağı veya IPAM tablosuna yazılmaz. Ham SSH çıktısı, konfigürasyon sırları ve erişim parolaları teslim kayıtlarına veya loglara eklenmez.

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

Eşitleme sürümünde sahte SSH cihazlarıyla 5412/5406, 2930, 6100, 7205 ve HP 1950 için fazla adres kaldırma, yinelenen kural temizliği, boş kümede ACL/port bağlantısı/adres nesnesi kaldırma, kaldırmanın tekrarlanabilirliği ve yabancı ACL reddi sınandı. Normal worker girişinden IP kaldırma, silme, hiç gönderilmemiş taslağın işsiz silinmesi, grup silme, ACL kimliği değişimi, gruptan çıkarılan cihazın temizlenmesi, çalışan işin sonradan gelen değişikliği alması, toplu ekleme, süre dolumu ve başarısız kaldırmada kaydın korunup **Durumu unut** ile tamamlanması doğrulandı.

Önceki sürümde sahte SSH cihazlarıyla 5412/5406, 2930, 6100, 7205 ve HP 1950 için ilk ACL, ikinci IP, tekrar gönderim, mevcut ACL çakışması ve tüm port bağlantıları sınandı. Normal worker girişinden başarılı gönderim, port hatası, kalıcı kayıt uyuşmazlığı, iptal, iptal sonrası tekrar gönderim, gateway elemesi ve meşgul cihazın diğer hedefleri bekletmemesi doğrulandı.

Yerel fixture tarayıcısında 1440, 768 ve 375 piksel açık/koyu temada 48 görünüm ve son hizalama için altı ek görünüm kontrol edildi. Gönderim, sonuçlar ve durdurma API üzerinden denendi. Axe ihlali veya JavaScript hatası bulunmadı. Gerçek cihazlarda ACL yazma ve paket engelleme testi yapılmadı.

Gönderime yönelik son hedefli koşuda 31 test geçti. Geniş regresyon koşusunda 166 test geçti, ayrı PostgreSQL test veritabanı gerektiren iki test atlandı. Sonrasında eklenen controller/config-mode istemleri ve modüler VSF portları hedefli koşuda doğrulandı. Değişen Python dosyalarının Ruff, Git boşluk ve frontend üretim derlemesi kontrolleri geçti. Vite’ın mevcut ana paket boyutu uyarısı sürüyor.


## Cihaz ACL logları

**Kara Liste → Loglar**, cihazların ürettiği ACL eşleşme olaylarını gösterir. Cihaz, ACL, kaynak/hedef IPv4, engelleme/izin sonucu, alınma zamanı ve temizlenmiş cihaz mesajı gösterilir. Saat dilimi taşıyan cihaz zamanları ayrıca tutulur; diğer zamanlardan UTC tahmin edilmez. Cihaz, metin ve son 1 saat / 24 saat / 7 gün / 30 gün filtreleri vardır. Alınma zamanı ve UUID ile 50 satırlık cursor sayfalaması kullanılır.

Ortak aktarım Syslog’dur. SNMP sayaçları paket olay günlüğü değildir. Comware ACL SNMP trap seçeneği bulunur, ancak bütün hedef ailelerde ortak bir okunabilir SNMP olay tablosu doğrulanmadığından SNMP log toplaması uygulanmaz. [AOS-S ACL log etkinleştirme](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/IPV6/WC/content/common%20files/ena-acl-log-swi.htm), [6100 CLI ve ACL log](https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/PDF/cli_6000-6100.pdf), [ArubaOS Syslog](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/logging.htm), [Comware ACL log ve trap komutları](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Routers/00-Public/Reference_Guides/Command_References/H3C_MSR_Comware_7_CR-R0615/11/202210/1709612_294551_0.htm).

### Etkinleştirme ve alıcı

- **Gönder → Cihazlara gönder**, deny kurallarına AOS-S/CX/ArubaOS için `log`, Comware için `logging` ekler ve Syslog hedefini ayarlar. Daha önce uygulanmış IP kaydını bir kez yeniden göndermek log üretimini açar. Yeni loglu deny doğrulanabilir sıraya eklenmeden eski deny kaldırılmaz. Aynı ACL’deki diğer NETRIX IP engelleri de loglu kurallara yükseltilir.
- AOS-S için `debug destination logging` / `debug acl`, CX için `debug destination syslog severity info` / `debug acl log severity info` kullanılır. Controller’da güvenlik/firewall kategorisi, Comware’de ACL bilgi kategorisi etkinleştirilir. Kalıcı ve çalışan konfigürasyonda hedef ve deny log bayrağı okunarak doğrulanır. Bu doğrulama uzak sunucuya olay ulaştığının kanıtı değildir.
- Alıcı mevcut `netrix` container’ında `netrix-acl-logs` sürecidir. Host **10.2.0.87:5515/UDP ve TCP** kullanır. Sunucudaki 514 ve 5514 portları başka log servislerine aittir. `NETRIX_ACL_LOG_HOST` boşsa `NETRIX_FIRMWARE_ADVERTISE_HOST` kullanılır. `NETRIX_ACL_LOG_PORT` varsayılan 5515’tir; host LAN bind adresi `NETRIX_FIRMWARE_BIND_IP` olur. Yeni servis/container veya veritabanı kurulmaz.
- Bir cihazda aynı sunucu adresi başka Syslog portuyla tanımlıysa mevcut hedef otomatik değiştirilmez; gönderim yazma öncesinde açıklayıcı çakışma hatası verir. Ayrı alıcı adresi veya mevcut Syslog servisi üzerinden, kaynak cihaz adresini koruyan yönlendirme gerekir.
- Sayfa açma, yenileme ve migration cihaza bağlantı açmaz. Liste ilk sayfası görünürken SQL’den 10 saniyede bir yenilenir. WebSocket bildirimi de yalnız SQL görünümünü yeniler. Alıcı durumu ve son gerçek ACL kaydının zamanı görünür.

### Saklama ve sınırlar

Alıcı yalnız ACL grubunda bulunan uygun cihazların yönetim IP’sinden gelen ACL eşleşmelerini kaydeder. Syslog mesajındaki iddia edilen hostname kullanılmaz; aynı IP için belirsiz cihaz varsa kayıt alınmaz. Cihaz kendi yönetim IP’sinden göndermelidir. UDP/TCP aktarımı kimliği kriptografik olarak doğrulamaz ve TLS içermez; erişim yetkili yönetim ağıyla sınırlandırılmalıdır. Relay/NAT kaynağı cihaz IP’sini değiştirirse mesaj kabul edilmez.

Her olay 30 gün saklanır; süresi dolan kayıtlar dakikada en fazla 10.000 satırla temizlenir. Kuyruk 4096 mesaj, mesaj 8192 bayt, TCP bağlantısı 32 ile sınırlıdır. TCP satır ve RFC6587 octet-counted çerçeveleri desteklenir. SQL hatasında üç sınırlı deneme yapılır; dolu kuyruk/bozuk çerçeve/başarısız kayıt sayısı ekranda belirtilir. UDP ağ kayıpları ölçülemez. Ham cihaz mesajı 2000 karakterle sınırlanır, kontrol karakterleri çıkarılır ve sır belirteçlerinden sonrası gizlenir.

Cihazlar logları örnekleyebilir, hız sınırlayabilir veya aralıklarla birleştirebilir. CX’in log-timer varsayılanı 300 saniyedir; Comware için bir dakikalık ACL log aralığı seçilir. Her paket için ayrı kayıt garantisi verilmez. AOS-S `debug` ayarları yeniden başlatmada korunmayabilir; yeniden **Gönder** ile etkinleştirilebilir. [AOS-S debug çalışma notları](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MCG/WC/content/common%20files/ope-not-deb-sys.htm). Gerçek cihazlarda sürüm ve olay biçimi doğrulaması henüz yapılmamıştır; testlerde sahte SSH ve yerel Syslog çerçeveleri kullanılır.

ACL log eklemesinin son doğrulamasında 98 test geçti; ayrı PostgreSQL test veritabanı gerektiren iki test atlandı. UDP/TCP çerçeveleri, kaynak cihaz elemesi, sır gizleme, sayfalama/saklama, Syslog hedef çakışması, loglu kural yükseltmesi ve normal worker üzerinden açık gönderim sınandı. Yerel tarayıcıda dört ekran boyutu ve iki temada dolu/boş liste ile ayrıntı penceresi toplam 24 görünümde kontrol edildi; filtreler, sayfalama, alan hizaları, taşma ve Axe kontrolleri geçti. Frontend üretim derlemesi ve değişen Python dosyalarının Ruff kontrolü başarılıdır. Ana Vite paketinin mevcut boyut uyarısı devam eder.
