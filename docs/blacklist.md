# Kara Liste

Kara Liste, **IP kayıtları**, **ACL grupları** ve **Cihaz durumu** ekranlarından yönetilir. Gruplar merkezi envantere referans verir. Bir IP birden fazla gruba bağlanabilir. Cihazlara yazma, **istenen durum eşitlemesi** ile yapılır: her cihazdaki NETRIX ACL’si, cihazın etkin gruplarındaki etkin IP kayıtlarıyla birebir eşitlenir. Ekleme, kaldırma, silme, grup silme ve ACL kimliği değişikliği aynı güvenli motordan geçer.

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
5. **ACL grupları** ekranındaki **Eşitle**, hiç IP yokken de ACL adı/ID’sini oluşturur ve tüm fiziksel portlara giriş yönünde bağlar. Son izin kuralı diğer iletişimi korur. Ayrıca grup cihazlarını ve gruptan çıkarılmış ancak grubun engellerini hâlâ taşıyan cihazları eşitler. **Sil**, grubun engellerini cihazlardan kaldırır; doğrulandıktan sonra grubu siler. IP kayıtları korunur.
6. **Cihaz durumu** ekranı her cihazda istenen ve doğrulanmış ACL’yi, IP sayısını ve eşitlik durumunu gösterir. **Eşitle**, **Seçilenleri eşitle** ve **Bekleyenleri eşitle** açık eylemlerdir. Yönetici, erişilemeyen veya elle temizlenmiş cihaz için **Durumu unut** ile kayıtlı durumu cihaza bağlanmadan silebilir.

Liste, ayrıntı ve önizleme açılışı ile kayıt/grup düzenlemesi pasiftir. Cihaza yazma yalnız açık kullanıcı eylemiyle veya kullanıcının girdiği bitiş zamanıyla başlar. Zamanlayıcı süresi dolan etkin kaydı Kaldırıldı durumuna alır ve süreyi giren kullanıcının yetkisiyle kaldırma işini kuyruğa alır; yetki geçersizse iş kuyruğa alınmaz ve cihaz Eşitleme bekliyor görünür. Sayfa açıkken devam eden işler WebSocket ve görünür sayfada beş saniyelik SQL yenilemesiyle izlenir. Arayüz kapandığında worker devam eder.

Grup tanımlarını ve silmeyi yöneticiler; IP kayıtlarını, gönderim/kaldırma/silmeyi ve eşitlemeyi operatörler/yöneticiler yönetir. Worker kullanıcı yetkisini, cihazın yaşam döngüsünü, modelini ve SSH hedefini bağlantı öncesinde yeniden doğrular. Firewall, router, gateway, VIP ve arşivlenmiş cihazlar kapsam dışıdır. SSH profili ve kayıtlı host anahtarı politikası kullanılır. Gerçek cihaza yazma test için otomatik tetiklenmez.

## Uygulama davranışı

- Engel kaynak IPv4 adresine ve giriş yönüne uygulanır. IPv6 kaydı saklanabilir, gönderimi açık hatayla reddedilir.
- Eşitleme işi istenen içeriği bağlantı anında SQL’den okur. Cihazdaki NETRIX ACL’sinde eksik adresler eklenir, istenmeyen adresler ve aynı adresin yinelenen kuralları kaldırılır. Yeni kural eskisi kaldırılmadan önce eklenir. Deny kuralları son izin kuralından önce kalır.
- Son IP kaldırıldığında etkin gruba ait ACL ve port bağlantıları korunur; yalnız engel kuralları kaldırılır. ACL, grup silindiğinde veya cihaz ilgili bütün gruplardan çıkarıldığında portlardan ayrılıp silinir. 7205 boş ACL’si yalnız son izin kuralını içerir; boş adres nesnesine deny bağlanmaz. Cihazdaki Syslog ve debug ayarlarına dokunulmaz.
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

PostgreSQL migration’ları `20261122_01`, `20261122_02`, `20261122_03`, `20261122_04` ve `20261122_05` olur. `20261122_04`, önceki yalnız-ekleme motorunun başarılı teslimlerinden cihaz durumlarını oluşturur ve gönderilmiş kayıtları `active` yapar; başarısız teslimler belirsiz (`dirty`) durum olarak taşınır. `20261122_05`, kaldırılan ACL log deposu `acl_logs` tablosunu siler. Cihaz kimliği yalnız `envanter.devices` içinde tutulur. Protokol kaynağı veya IPAM tablosuna yazılmaz. Ham SSH çıktısı, konfigürasyon sırları ve erişim parolaları teslim kayıtlarına veya loglara eklenmez.

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

## ACL logları kaldırıldı (22 Kasım 2026)

Proje sahibinin kararıyla Kara Liste → Loglar menüsü, `netrix-acl-logs` Syslog alıcısı, 5515/UDP-TCP port yayını, `NETRIX_ACL_LOG_*` ayarları, `/api/v1/blacklist/logs` uç noktası ve `kara_liste.acl_logs` tablosu kaldırıldı; bunlar yeniden eklenmez. Gönderim artık deny kurallarına `log`/`logging` bayrağı, Syslog hedefi veya debug ayarı eklemez. Önceki sürümün cihazlara yazdığı loglu deny kuralları, Syslog hedefleri ve debug ayarları cihazda olduğu gibi bırakılır; NETRIX bunları değiştirmez, loglu deny kuralını mevcut engel olarak okur.

## IP olmadan ACL hazırlama düzeltmesi

Grup **Eşitle**, etkin IP bulunmasa da profil adı/ID’sini cihazda oluşturup bütün portlara uygular ve kalıcı konfigürasyondan doğrular. **IP → Gönder** ilgili grupların cihazlarına deny ekler. Son IP kaldırıldığında boş, son izin kuralı bulunan ACL korunur. Grup silme/cihazı gruptan çıkarma ACL kaldırmayı yönetir. Hiç gönderilmemiş taslağın silinmesi cihaz işi oluşturmaz. 82 hedefli test ve masaüstü/mobil tarayıcı kontrolü geçti; gerçek cihazlara test gönderimi yapılmadı.


ACL grubu silme, SQL’de önceki cihaz uygulama kaydı bulunmasa bile mevcut bütün üyelere SSH kaldırma işi oluşturur. Her üyeye doğrulanmamış kaldırma yükümlülüğü kaydedilir; cihazda ACL bulunmadığı veya kaldırıldığı çalışan/kalıcı konfigürasyondan doğrulanmadan grup silinmez. Eksik SSH profili veya bağlantı hatasında grup Siliniyor durumunda kalır ve cihaz gerekçesi gösterilir. Başka etkin grubun kullandığı ortak ACL korunur.

## Ayrı gönderim kuyruğu — 22 Kasım 2026

Kara Liste işleri aynı container içindeki `netrix-blacklist` sürecinde çalışır.
Bu süreç yalnız `blacklist_send` işlerini alır ve aynı anda en fazla beş cihazı
işler. Genel worker bu işleri almaz. Keşif, yedekleme ve IPAM işleri bu beş
kapasiteyi tüketmez. Cihaz başına tek iş, firmware çakışma kontrolü, iptal,
kalıcı SQL kuyruğu ve yeniden deneme davranışı korunur. Sürecin heartbeat'i
container sağlık kontrolüne dahildir.


## AOS-S trunk satırları ve yönetilen 7205 cihazları

5412/5406 ve 2930 port tablosundaki `A2-Trk1`, fiziksel `A2` portunun `Trk1` üyesi olduğunu belirtir. Fiziksel port kimliği ayrıştırılır; tabloda bildirilen trunk ile konfigürasyondaki üyelik karşılaştırılır. Eksik veya çelişkili üyelikte yazma durur.

Mobility Conductor tarafından yönetilen 7205 için `NETRIX_BLACKLIST_CONDUCTOR_HOST=10.1.0.30` yapılandırılır. Conductor aynı VRF içinde merkezi envanterde kayıtlı ve etkin olmalıdır; mevcut şifreli SSH profili ve host anahtarı politikası kullanılır. Yeni cihaz tablosu veya ayrı parola ayarı yoktur. Ayar boşsa mevcut doğrudan SSH yolu kullanılır; yönetilen cihaz doğrudan yazmayı reddederse açık Conductor gereksinimi gösterilir.

**Eşitle**, **Gönder**, **Kaldır**, IP/grup silme ve süre dolumu aynı worker yolunda Conductor üzerinden çalışır. `show switches debug`, `show configuration devices` ve `show configuration node-hierarchy` çıktılarındaki IP/MAC/düğüm eşlemesi birlikte doğrulanır. Debug tablosundaki ortak grup yolu yazma hedefi sayılmaz; yalnız doğrulanmış cihaz düğümü seçilir. 7205 bağlantısı yalnız çalışan konfigürasyon ve fiziksel/LAG port listesini okur; ACL, adres nesnesi ve port bağlantısı komutları Conductor’daki cihaz düğümüne yazılır.

Aynı Conductor üzerindeki NETRIX işleri Redis kilidiyle sırayla çalışır. Hedef düğüm veya üst/alt zincirde önceden bekleyen değişiklik, miras alınmış hedef ACL/port bağlantısı, değişen IP/MAC/düğüm, erişim profili değişimi ve plan dışı pending komutları işlemi durdurur. Commit öncesinde pending farkı tekrar karşılaştırılır. Bu kilit harici yönetici SSH oturumlarını kilitlemez; aynı düğümde eşzamanlı manuel değişiklik yapılmamalıdır. İptal veya hata sonrası pending içerik otomatik silinmez/commit edilmez; sonraki iş açık hata verir ve inceleme gerekir.

Kaydetme yalnız hedef düğümde `write memory` ile yapılır. Conductor etkin/kalıcı okumaları henüz commit edilmemiş değişiklikleri içermez. Yeni adres nesnesi, ona bağımlı ACL ve ACL’ye bağımlı port bağlantıları bu sırayla ayrı kaydedilip geri okunur; kaldırmada önce port bağlantıları, sonra ACL, sonra adres nesnesi kaydedilerek kaldırılır. Nesne bağımlılıkları böylece kalıcı kayıt üzerinden doğrulanır. İlk port reddinin yalnız commit sırasından kaynaklandığı varsayımı canlı geri okumada doğrulanmadı; gerçek bağlantı biçimi aşağıda açıklanır. Her ara aşamada pending farkı, hedef Config ID ve gerçek 7205 içeriği doğrulanır; SQL’de eşitlendi durumu yalnız bütün plan doğrulanınca yazılır.

Başarı için hedef 7205’in `UPDATE SUCCESSFUL` durumu, değişiklikte ilerleyen Config ID, boş pending, Conductor’daki kalıcı/etkin yerel düğüm içeriği ve 7205’ten salt okunur gerçek çalışan ACL/port bağlantıları doğrulanır. Her dağıtım aşaması en çok 120 saniye, bütün cihaz işi 600 saniye beklenir; komutun başarılı dönmesi tek başına başarı sayılmaz. Yerel override, Syslog veya debug ayarı yazılmaz.

7205 session ACL tanımı `ip access-list session <ad>` olarak kalır; fiziksel/LAG port bağlantısı kaynak IPv4 engelinin giriş yönü için `ip access-group in <ad>` kullanır. Canlı Conductor, kalıcı ve cihaza ulaşmış aynı ACL için `ip access-group session <ad>` komutunu `Invalid access group configuration` ile reddetti; `in` biçimini kabul etti. Kaldırma komutu ACL adını almaz: `no ip access-group in`. Aynı komuta ACL adı eklenmesi cihaz tarafından reddedilir. İki cihazda PEF lisans kullanımı ayrıca doğrulandı; bu reddin nedeni lisans yokluğu değildir. Başka yöndeki/mevcut port politikası otomatik değiştirilmez. Zaten yalnız son izin kuralı bulunan boş ACL, her eşitlemede silinip yeniden oluşturulmaz; adres nesnesi veya deny varsa eski temizleme sırası korunur.

Aruba, kullanılmasa bile `port-channel 0`–`7` şablonlarını etkin/çalışan konfigürasyonda listeler. Boş şablonlar ACL hedefi değildir. LAG hedefi yalnız fiziksel porttaki `lacp group <0-7> mode active|passive` veya aggregate içindeki açık fiziksel üye satırıyla kanıtlanır; bu üye portlar aggregate üzerinden kapsanır. Aynı fiziksel portun farklı gruplara atanması ve listede bulunmayan fiziksel üye işlemi durdurur. İlk canlı gönderimde altı fiziksel portun bağlandığı, ancak boş şablonları da hedef sayan eski doğrulamanın gereksiz hata verdiği saptandı.

7205 çalışan konfigürasyonundaki girintisiz `Description: NETRIX-BLACKLIST` alanı, ait olduğu session ACL/adres nesnesinin açıklaması olarak normalleştirilir. ACL bloğu bölünmez; deny/izin kuralları aynı blokta kalır. Yabancı açıklama NETRIX işareti sayılmaz. Bu gerçek çıktı biçimi normal worker yaşam döngüsü regresyonuna dahildir.

Önceki sürümün yarım kalan ilk boş ACL hazırlaması için dar bir devam yolu vardır: SQL’de aynı profil ve sıfır adresle kaydedilmiş belirsiz deneme bulunmalı; cihazda henüz etkin ACL olmamalı; pending yalnız aynı `NETRIX-BLACKLIST` açıklamalı, son izin kurallı ACL ile gerçek fiziksel portların otomatik `description GE…` satırlarından oluşmalıdır. Başka pending komutu varsa kaydedilmez. Bu başlangıç tanımı doğrulanarak kaydedilir, ardından normal tüm-port eşitlemesi tamamlanır. Genel iptal/pending içeriği otomatik temizlenmez veya sahiplenilmez.

Conductor regresyonları sahte protokollerle normal worker girişinden ACL hazırlama, IP gönderme/kaldırma, grup silme, paylaşılan kilit, iptal, miras/pending çakışması, değişen erişim/düğüm ve geciken/başarısız cihaz geri okumasını kapsar. İki gerçek 7205’in düğüm eşlemesi ve ön kontrolleri salt okunur doğrulanmıştır; teslim testi gerçek ACL yazması veya commit başlatmaz. Resmi komut kaynakları ve yöntem: [Conductor ACL notu](mobility-conductor-acl.md).
