# Kara Liste

22 Kasım 2026 tarihli ilk teslim, **Kara Liste → IP kayıtları** ve **ACL grupları** ekranlarını kapsar. Gruplar, cihaz ailesine göre kullanıcının girdiği ACL kimliğini ve merkezi envanter cihazlarına referansları saklar. Bir IP birden fazla gruba bağlanabilir. Aynı cihaz ve aynı ACL’ye çıkan hedefler önizlemede birleştirilir. Kayıtlar taslaktır. Cihaza SSH ile gönderim ve ACL değişikliği bu sürümde etkin değildir.

## Kullanım

1. ACL grubu oluşturun, envanter cihazlarını seçin ve her seçili aile için ACL türü ile adını veya numarasını girin.
2. IP kaydında adresi ve hedef grupları seçip taslağı kaydedin.
3. **Önizle** eylemiyle cihaz, IP, model ve hedef ACL listesini inceleyin. Uygunluğunu kaybeden cihazlar sorun açıklamasıyla gösterilir.

Grup tanımlarını yöneticiler düzenler. IP taslaklarını operatörler ve yöneticiler düzenler. Kimliği doğrulanmış kullanıcılar kayıtları okuyabilir. Form, liste, kaydetme ve önizleme eylemleri pasiftir. Ağ görevi oluşturmaz. Firewall, router, gateway işaretli, VIP, arşivlenmiş ve aktif olmayan cihazlar seçilemez. Yalnız talep edilen aileye uyan envanter modelleri sunulur.

Veri sahibi yeni ana menünün `kara_liste` şemasıdır. `acl_groups` ve `blacklist_entries` tanımları, `acl_group_devices` ve `blacklist_entry_groups` ilişkileri saklar. Cihaz kimliği `envanter.devices` kaydına FK ile bağlanır. PostgreSQL migration’ı `20261122_01` olur.

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

## SSH gönderim motorunun devamı

Bu bölüm uygulanacak davranışı tarif eder. İlk tasarım tesliminde çalışan motor olarak sunulmaz.

- Kullanıcının **Cihazlara gönder** eylemi hedefleri sabitleyip worker işini başlatır. Grup düzenleme veya sayfa açılışı gönderim tetiklemez.
- İş öncesi aktif cihaz, model/OS, SSH profili, host anahtarı ve ACL kimliği tekrar doğrulanır. Firewall/gateway elemesi worker’da da uygulanır.
- Kullanıcı ACL adı/numarası yanında yeni ACL için port/VLAN veya controller rolü bağlama hedefini belirler. Mevcut ACL’de bağlantı ve kural sırası okunur. Bir ACL’ye kayıt eklenmesi tek başına ağda engelleme doğrulaması sayılmaz.
- Kaynak veya kaynak/hedef engelleme seçimi, kural sırası ve mevcut izin politikasını koruma davranışı gönderim tasarımında açıkça tanımlanır. IPv6 ayrı ACL yeteneği ve profil doğrulaması gerektirir.
- Cihaz/ACL başına yürütme kilidi, süre sınırı, sınırlı eşzamanlılık ve iptal noktaları uygulanır. Tekrar teslimde mevcut eşdeğer deny kontrol edilir. Kısmi hata diğer cihazların sonucunu kaybettirmez.
- SSH kopması veya belirsiz yazma sonucunda önce cihazdan tekrar okunur. Cihaz çıktısı doğrulanmadan başarı gösterilmez. Kayıt ve kalıcı konfigürasyon doğrulaması ayrı sonuçlarla gösterilir.
- Mevcut envanter, kasa, görev merkezi ve denetim servisleri kullanılır. Bu modül IPAM taraması başlatmaz ve protokol kaynak tablolarına yazmaz.

## Doğrulama

- Kara Liste, PostgreSQL yerleşimi, cihaz erişimi sınırları ve firmware aile testlerinde 80 test geçti. Açık bir `NETRIX_TEST_DATABASE_URL` verilmediği için iki PostgreSQL entegrasyon testi atlandı.
- Migration’ın PostgreSQL DDL çıktısında dört tablo, şema, tam nitelikli FK, TIMESTAMPTZ, JSONB ve çalışma zamanı yetkileri kontrol edildi.
- Üretim frontend derlemesi geçti. Mevcut ana JavaScript paketi için Vite’ın 500 kB boyut uyarısı devam ediyor.
- Yerel fixture üzerinde 1440, 768 ve 375 piksel, açık/koyu tema ile 36 görünüm kontrol edildi. Form, liste, çoklu grup, ortak hedef birleştirme, düzenleme ve sayfa yenilemesi denendi. Axe erişilebilirlik ihlali ve tarayıcı JavaScript hatası bulunmadı.
- Değişen Python dosyalarının Ruff kontrolü ve Git boşluk kontrolü geçti. Depo genelindeki Ruff taramasında mevcut `scripts/lumelle_navigation_browser_check.py` ve `tests/test_aos_mac_table.py` import sıralaması hataları sürüyor.
- Bu doğrulamalar gerçek cihazlarda ACL yazma veya engelleme testi içermez.
