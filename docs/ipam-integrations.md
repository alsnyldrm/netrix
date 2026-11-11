# VLAN tabanlı IP adres yönetimi

## Tarama grubunu manuel başlatma — 5 Kasım 2026

Proje sahibinin talebiyle **Ayarlar → Tarama** grup kartındaki mavi **Tarama başlat**
düğmesi, operatör/yöneticinin grubu takvim beklemeden çalıştırmasını sağlar
(`POST /api/v1/ipam/scan-groups/{id}/scan`, HTTP 202). Bu eylem VLAN içindeki SQL-only
**Tara** değildir: zamanlanmış turla aynı cihaz, entegrasyon, DNS ve ICMP okumalarını
yapar ve sonucu SQL'e yazar. Köken `group_manual`, işi başlatan kullanıcı `requested_by`
olarak kaydedilir. Takvim, `next_run_at` ve çalışma sayısı değişmez; tur Tarama
geçmişinde **Manuel başlatıldı** olarak görünür. Aktif VLAN işi yeniden kullanılır,
tekrar tıklama ikinci geçmiş kaydı açmaz. İzleyici başlatamaz. Şema değişikliği yoktur.
Regresyonlar: `test_ipam_scan_schedules.py`, `scripts/ipam_scan_browser_check.py`.

## Eşzamanlı 10 cihaz okuması ve SQL yazımı — 5 Kasım 2026

Proje sahibinin talebiyle worker genelinde **aynı anda en çok 10 cihaz** okunur
(`runtime_limits.DEVICE_READ_CONCURRENCY`). Sınır tam VLAN taraması ve envanter
keşfinin ortak yuvasıdır: işler üst üste binse de toplam 10'u
geçmez. Tam VLAN taramasında SNMP ve
AOS-S switchlerde isteğe bağlı SSH komşu ayrıntısı **aynı cihazın tek yuvasını ve tek
185 saniyelik bütçesini** paylaşır; protokol başına ayrı yuva açılmaz. Yuva, yanıt
belleğe alınınca boşalır, SQL yazımı ağ okumasını bekletmez.

Ağır SQL işleri event loop dışındadır: kaynak ve sonuç yazımları tek yazıcı iş
parçacığında sırayla yürür (işler arası yeni kilitlenme/sertifikasyon çakışması
açılmaz), `Evidence` kurulumu ayrı okuma iş parçacığındadır. Böylece SNMP/ICMP
zamanlayıcıları SQL sırasında durmaz.

SNMP tablosunun 15 saniyelik süresi artık yanıtlar arası sessizlik sınırıdır. Yanıt
vermeyi sürdüren büyük FDB/ARP tablosu kesilmez; cihaz başına 160 saniyelik toplama
üst sınırı sürer. Tam tarama cihaz bütçesi 60 yerine 185 saniyedir. Regresyonlar:
`test_scan_concurrency.py`, `test_ipam_network_worker.py`.

## Eksik VLAN–FID için hedefli SNMP doğrulaması — 5 Kasım 2026

VLAN–FID tablosu hedef VLAN'ı vermiyorsa gateway ile doğrulanmış MAC'in aynı
VRF/cihaz bağlamındaki, en çok yedi saatlik ve sağlıklı SQL FDB adayları kullanılır.
VLAN numarası FID kabul edilmez; en çok 16 aday FID'nin yalnız ilgili MAC hücresi
SNMP GET ile tekrar okunur. Canlı VLAN–FID tablosunda başka/ortak VLAN'a ait olduğu
bilinen FID kullanılamaz. Birden fazla canlı FID belirsizliktir; keyfi seçim yapılmaz.
Aday yoksa bütün FDB'yi okumaya genişlenmez.

Tek adayda bridge port → ifIndex → açık arayüz adı zinciri ve hedef VLAN'ın
Q-BRIDGE statik egress PortList üyeliği SNMP ile doğrulanır. PortList bitleri bridge
port numarasına göre yorumlanır. LLDP/CDP indeksleri SNMP'den yenilenir; hedef portun
komşu kimlikleri GET ile okunur. Boş komşu tablosunun kanıt sayılması için canlı LLDP
istatistik veya etkin CDP scalar desteği gerekir; çözülemeyen yerel port reddedilir.
SQL'deki tek-MAC nüfusu, eksiksiz komşuluk kaynağı, uplink ve bağımsız aday
kontrolleri korunur. Bu alternatif SSH çağırmaz; mevcut VLAN–FID yolu önceliklidir.

Manuel tek-IP ve VLAN işi aynı yolu kullanır. Zamanlanmış VLAN işi mevcut
çözümleyici/önbellek sonuç bulamazsa yalnız eşlemesi eksik aday switchlerde bu hedefli
SNMP doğrulamasını kullanır. GET/sayfa açılışı pasiftir. Opsiyonel SSH ayrıntı hatası,
zamanlanmış okumada başarılı SNMP snapshot'ını silmez.

Eksik/desteklenmeyen VLAN–FID, ham MAC/FID/port kayıtlarının SQL'ye alınmasını
engellemez; doğrulanmamış VLAN `0` kalır. Hedefli doğrulama aynı FID/MAC/port
satırını günceller, yeni sahte FID veya genel VLAN–FID eşlemesi üretmez. IP sonucu
bu kanonik satıra referans verir; diğer IP/VLAN kayıtları topluca yenilenmez.
Regresyonlar `test_ipam_fid_candidates.py`, `test_ipam_point_protocols.py` ve
`test_ipam_source_contract.py`; gerçek ağ erişimi testlerde yasaktır.

## Tür başına tek SQL kaynak ve NIC-Teaming — 4 Kasım 2026

Bu bölüm eski JSON gözlem/snapshot saklama ve envanterden ayrı IPAM kaynak
kopyalama hükümlerinin yerine geçer. Gateway, DHCP, VMware VM/host/NIC/ağ,
switch MAC–port, LLDP ve CDP verilerinin her türü tek ilişkili SQL yapısında
saklanır. Envanter keşfi ve yetkili IP/VLAN/zamanlama işleri aynı kaynak
repository'lerini günceller; IPAM ve envanter bu kayıtlardan okur. Yönetilen
cihaz alanları, kullanıcı etiketleri ve hariç tutmalar kaynak kanıtından ayrıdır.
Tablo listesi ve doğrulamalı aktarım `docs/data-model.md` revision 50 bölümündedir.

IP **NIC-Teaming** seçeneği varsayılan kapalıdır. Etkin IP taramasında yalnız
seçili DNS ile hostname bulunur; sonra aynı VRF'nin güncel, etkin ve hariç
tutulmamış envanter komşuları SQL'den tam hostname ile eşleştirilir. Gateway,
VMware, DHCP, backbone/switch istemcisi oluşturulmaz ve sorgulanmaz. Aynı veya
farklı switchlerdeki bütün eşleşen portlar ve NIC/uzak port bilgileri birlikte
gösterilir; yalnız isim benzerliğinden eşleşme yapılmaz. 24 saatten eski komşular
son bilinen kanıt olarak Sorunlu uyarısıyla gösterilir. DNS yoksa isim tahmin
edilmez. Mod seçimi ve sayfa açılışı ağ sorgusu başlatmaz; mevcut SQL DNS/komşu
verisiyle form tercihi uygulanır. Sonraki açık Tara veya zamanlama DNS'i günceller.
NIC-Teaming kapalı IP'lerde gateway → VM/host ayrımı → fiziksel dal aynen sürer.

Normal kaynak okuyucuları tamamlanan IP'nin kaynaklarını önce kanonik SQL'ye,
sonra sonuç referanslarını aynı IP'ye yazar; diğer IP'lerin bitmesi beklenmez.
Dar kapsamlı manuel IP/VLAN okuması yalnız dönen IP/MAC/port/komşu kayıtlarını
günceller, diğer VLAN kaynaklarını emekliye ayırmaz ve bütün ağ okumaz. Kaynak
okuma ortak SQL kanıtını günceller; yönetilen cihaz kimliğini veya manuel
komşuluk tercihlerini değiştirmez. Her GET yalnız SQL okur; JSON yanıt önbelleği
ve JSON kaynak dosyası tutulmaz. Bağımsız ICMP ve zamanlama tetikleyicileri korunur.

Doğrulamalar: `test_source_tables.py`, `test_ipam_nic_teaming.py`,
`source_tables_mariadb_check.py`, `source_tables_legacy_fixture.py`,
`nic_teaming_browser_check.py`. Gerçek protokoller testlerde yasaktır.

## Tek VLAN düzenleme formu — 4 Kasım 2026

VLAN bilgileri ve DNS, kullanım uyarı eşiği, ping aralığı/etkinliği **Kaydı düzenle · VLAN alanları** penceresinden birlikte kaydedilir. Ortak alanlar yalnızca bir kez bulunur. Ayrı **VLAN ayarları** penceresi ve dişli düğmesi kaldırılmıştır; düzenleme düğmesi güncel VLAN kaydını SQL'den okuyup aynı forma getirir. Böylece liste yenilenmeden hızlıca yeniden açılan form eski değerleri kullanmaz. Kaydetme tek `PUT /api/v1/vlans/{id}` isteğidir; eski ayar API'si mevcut istemciler için korunur, bu arayüz tarafından çağrılmaz.

Ping aralığı 10–86.400 saniye, eşik %1–100 olarak sınırlandırılır; yeni VLAN formu API ile aynı 30 saniye/etkin ping varsayılanını kullanır. Eski otomatik kaynak keşif aralığı ve etkinlik kontrolleri gösterilmez; tam tarama Ayarlar → Tarama grupları veya açık Tara eylemiyle başlar. Form açma, yenileme ve kayıt kaynak sorgusu/tarama başlatmaz. Mevcut VLAN ayarları silinmez; şema değişikliği yoktur.

Birleştirilmiş formun güncel tarayıcı regresyonu `scripts/vlan_edit_browser_check.py` dosyasıdır: tekil alanlar, sayısal sınırlar, VLAN/DNS/ping kalıcılığı ve hızlı yeniden açma, 1440/375/812 px açık/koyu tema, alan hizaları ve WCAG kontrolleri gerçek yerel API ile doğrulanır; protokol işi başlatılmaz.

## VLAN içinde manuel IP kaydı — 4 Kasım 2026

VLAN listesinde **Yeni kayıt**, VLAN formunu; bir VLAN açılmışken **Yeni IP kaydı**, o VLAN'a bağlı IP formunu açar. VLAN/VRF bağlamı sabittir; kurum ve lokasyon seçilen VLAN'dan gelir. Hostname, MAC, işletim sistemi, kurum/lokasyon/oda, kabinet, gateway işareti, atama durumu, bağlı cihaz ve yalnız o cihazın yönetilen arayüzleri mevcut IP formunda düzenlenir. Oda ve kabinet seçimleri kat/bölüm/oda yoluyla aranır. Bu form kaynak okuması veya iş kuyruğu başlatmaz.

`GET /api/v1/ipam/vlans/{id}/available-addresses` yalnız SQL'den en çok 200 adreslik sayfa döndürür; arayüz 100'lük sayfaları arama ve **Daha fazla IP** ile açar. Son güncel pinginde yanıt veren adresler, açık rezervasyonlar, gateway işaretli kayıtlar ve IPv4 ağ/yayın adresleri listelenmez. Pasif keşif kayıtları ve henüz kaydedilmemiş adresler seçilebilir. Tam IPv4/IPv6 adresiyle doğrudan arama desteklenir; IPv6 bloğu bütünüyle genişletilmez. Aynı VRF'deki diğer VLAN'ın kayıtları değiştirilmez.

`POST /api/v1/ipam/vlans/{id}/addresses` operatör yetkisi, CIDR/VRF/VLAN uyumu ve mevcut ilişki doğrulamalarını uygular. Kaydetmeden önce seçilen IP'nin durumu SQL'den tekrar okunur; dolmuş adres 409 ile reddedilir. Pasif keşif satırı varsa aynı kimlik güncellenir, gözlemler ve kaynak sonuçları korunur; ikinci IP satırı açılmaz. Yeni atamalar varsayılan olarak **Rezerve** kaydedilir. Kayıt sonrası kullanıcı eklediği adresi görebilsin diye mevcut görünüm adresle aranır ve aktif filtresi kapatılır; VLAN'a sonraki girişte aktif filtre varsayılanı korunur. Okuma, form açma ve kayıt yeni tarama başlatmaz.

Regresyonlar: `tests/test_ipam_allocation.py`, `scripts/ipam_allocation_fixture.py`, `scripts/ipam_allocation_browser_check.py`. Tarayıcı doğrulaması gerçek yerel API ile masaüstü/mobil, açık/koyu tema, klavye seçimi, açılır listenin ekrana sığması, alan hizaları ve WCAG kontrollerini kapsar. Şema değişikliği yoktur.

## Entegrasyon bağlantı testi — 4 Kasım 2026

Entegrasyon ekleme/düzenleme penceresindeki **Bağlantıyı test et**, formdaki ayarlarla salt okunur bağlantı ve temel erişim kontrolü başlatır. Yeni taslak için `POST /api/v1/integrations/connection-tests`, kayıtlı entegrasyon için `POST /api/v1/integrations/{id}/connection-tests` HTTP 202 ile `test_integration` işini döndürür. Yalnız yönetici başlatabilir. Kullanıcı/parola boşsa mevcut şifreli bilgi kullanılır; hedef sunucu, port veya tür değiştiğinde yeni kullanıcı/parola birlikte gerekir. Test ayarları kaydetmez, `last_success_at`, IPAM gözlemleri, envanter ve kaynak snapshot’larını değiştirmez. Sayfa/pencere açılışı ve Kaydet düğmesi test başlatmaz.

Test mevcut etkileşimli worker kapasitesini paylaşır (en çok 4 işlem); uygun worker/kapasite yoksa 503/429 ile reddedilir. Form taslağı ve sırlar uygulama anahtarıyla şifrelenmiş olarak Redis’te en çok 120 saniye tutulur, bitiş/iptalde kullanılabilir içerik temizlenir. MariaDB iş sonucu, audit ve API yanıtı sırları içermez. Worker en çok 60 saniyelik testte vCenter HTTPS oturumu ve görünür VM envanter erişimini veya WinRM HTTPS, DHCP modülü ve bir DHCP kapsam okumasını kontrol eder. Temel erişim testi tam rezervasyon/kiralama veya VM kaynak toplaması değildir. Sonuç pencerede gösterilir; çalışan test iptal edilebilir. Alan değişikliği önceki sonucu kaldırır; test çalışırken form alanları ve Kaydet devre dışıdır.

Regresyonlar: `tests/test_integration_connection_tests.py`, mevcut etkileşimli protokol/karşılaştırma testleri ve `scripts/integration_test_browser_check.py`. Tarayıcı fixture’ı gerçek API/worker akışını sahte protokollerle çalıştırır; doğrulamalar gerçek DHCP/vCenter sunucularına bağlanmaz. Şema değişikliği yoktur.

## Gateway öncelikli ortak algoritma — 4 Kasım 2026

Bu bölüm önceki DNS/VMware MAC önceliğinin ve tek-IP toplu kaynak okumasının yerine geçer. Manuel hostname/MAC/işletim sistemi düzenlemeleri ayrı kalır ve görüntülemede önceliklidir.

| Sıra | Koşul | İşlem / kaynak |
| --- | --- | --- |
| 1 | Her IP | Doğrudan bağlı gateway arayüzünde IP → tekil MAC; kimlik otoritesi gateway'dir |
| 2 | Her IP | VMware IP/NIC araması; MAC gateway ile karşılaştırılır |
| 3a | Tekil, uyumlu VMware sanal makine (VM) kaydı | Hostname, sanal switch/port, ağ ve işletim sistemi VMware'den; DNS, DHCP, backbone ve switch sorgulanmaz |
| 3b | VMware kaydı yok veya kayıt fiziksel ESXi hostu | Gateway MAC'inin backbone → alt switch yolu; uç port doğrulanır |
| 4b | Fiziksel dal | DHCP'nin IP/MAC ve ters MAC/IP kaydı karşılaştırılır; DNS PTR okunur |
| 5 | Her işlenmiş IP | Tüm alanlar tek transaction ile güncel sonuca yazılır ve ilgili VLAN'a bildirilir |

Fiziksel dalda hostname önce DNS, DNS yoksa uyumlu aktif DHCP kaydıdır. DHCP IP/MAC veya hostname kaynakları çelişirse otomatik ad `YANLIŞ-DHCP-VERİSİ` olur; MAC değiştirilmez. Otomatik işletim sistemi fiziksel dalda boştur. VM bulunduğu halde MAC/kimlik çelişiyorsa fiziksel dala düşülmez, sorun kaydedilir. Kaynak erişim hatası VMware kaydı yokmuş gibi yorumlanmaz. Yanıt vermeyen kaynak veya eksik yanıt, önceki doğrulanmış alanları temizlemez; korunan bilgiler ve hata ayrıntıda açıkça belirtilir. Gateway MAC'i değişmişse önceki kimliğin adı/bağlantısı yeni kimliğe taşınmaz. Aynı uç kimliği/LAG kanıtıyla doğrulanan çoklu port/switch bağları birlikte gösterilir; port etiketinde üye port ve trunk bulunur (`H7 Trk1 - H8 Trk1`). Transit/uplink ve bağımsız çelişkili adaylardan rastgele uç seçilmez.

### VMware VM / fiziksel ESXi ayrımı — 4 Kasım 2026

`record_type=host` kayıtları sanal makine dalını kısa devre etmez. VMware hostun kimliğini belirledikten sonra gateway MAC'iyle backbone → alt switch → fiziksel port, ardından DHCP ve DNS adımları devam eder. Hostun kendi vSwitch/vmk portu veya VMware uplink ipucu bağlı fiziksel port olarak sunulmaz. Host/NIC bilgileri yardımcı kaynak ayrıntısında korunabilir; switch/port seçiminin kaynağı fiziksel dalın güncel kanıtıdır. Host adı fiziksel dalın DNS/uyumlu DHCP kuralını izler; otomatik işletim sistemi boş kalır. Host `Sanal` kabinet gösterimini almaz.

Sanal makine kaydı ise VMware hostname/işletim sistemi ve kendi sanal switch/portunu kullanır; diğer kaynaklar atlanır. Gateway MAC çakışması veya VM/host sahipliği belirsizliği görünür sorun olarak kalır. Ortak çözümleyicideki ayrım tek-IP, manuel VLAN ve zamanlanmış VLAN işlerine uygulanır; her IP SQL commit'inden sonra görünür olur. Dağıtım eski sonuçları yeniden taramaz veya başarılı diye değiştirmez; kullanıcı **Tara** eylemi ya da sonraki zamanlama yeni kuralı uygular. Regresyon: `test_ipam_esxi_branch.py`, `test_vlan_scan_pipeline.py` (host ve VM türleri ayrı doğrulanır).

### SQL'de güncel sonuç

`ip_resolution_results.address_id` tekildir: her IP için yalnız bir güncel satır vardır. Alanlar, gateway kanıtı, en çok 32 bağlantı, 24 sorun ve 32 işlem adımı güncellenir; her denemede geçmiş satırı eklenmez. Başlangıç/bitiş/son başarı zamanları UTC'dir. Daha eski başlayan iş, yeni tamamlanmış sonucu ezemez. IP/VRF/VLAN bağı değişmişse eski sonuç kullanılmaz. IP silinince sonuç CASCADE silinir. `network_source_states.device_id` tekildir; zamanlanmış kaynağın son başarılı protokol snapshot'ı yerinde güncellenir. Bu tabloların satır sayısı tarama sayısıyla değil mevcut IP/kaynak sayısıyla sınırlıdır; gerçek envanter büyüdükçe doğal olarak artabilir. Mevcut ayrı olay ve konfigürasyon geçmişleri bu sözleşmeden etkilenmez. Migration, eski bağımsız `integration` kaynak işlerinin bekleyen/çalışan kayıtlarını iptal eder; bu işler yeni düzende ortak VLAN/IP akışının içinde okunur. Zamanlama grupları ve diğer işler değişmez.

Liste/ayrıntı, işlenen IP için doğrudan bu sonucu okur; her GET'te kanıtları baştan birleştirmez. Ping ayrı gözlemdir, sonuç kimliğini ve kaynak alanlarını silmez. **Sonuç**, IP'nin hemen solundadır: yeşil **Başarılı**, kırmızı **Sorunlu**; henüz işlenmemiş kayıt `—` gösterir. Ayrıntı sorun açıklaması, korunan veri uyarısı ve adım tablosunu gösterir. `ipam_results_backfill.py` mevcut kaynak gözlemlerinden yalnız eksik sonuçları çevrimdışı oluşturabilir; ağ sorgusu yapmaz ve eşzamanlı oluşan sonucu ezmez. Bu kayıtlar arayüzde mevcut gözlemlerden işlendiği notuyla ayrılır. Süresi eskimiş son bilinen gateway/port verisi de geçişte korunur; Sorunlu ve eski kaynak açıklamasıyla gösterilir, yeni gözlem gibi sunulmaz.

### IP ayrıntısında tek adres taraması

Operatör/yönetici **Tara** düğmesiyle `POST /api/v1/ipam/addresses/{id}/scan` çağırır (202). Aynı değişmez IP/VRF/VLAN bağı için tek aktif iş, aktör ve iptal desteği korunur; `GET` yalnız son işi okur. API kaynak okumaz. Worker tek IP'nin gateway ARP/NDP hücresini GET ile okur. VMware `SearchIndex.FindAllByIp` yalnız hedef IP ve onun NIC/backing nesnelerini getirir; guest IP eksikse önceden bilinen MOID yalnız ipucu, güncel gateway MAC doğrulaması zorunludur. Fiziksel dalda Q-BRIDGE VLAN/FID metadata'sından yalnız ilgili MAC hücresi ve yol üzerindeki port/LLDP/CDP ayrıntıları okunur; bütün ARP/FDB/NIC envanteri okunmaz. DHCP `-IPAddress` ve `-ClientId` filtreleri sunucuda çalışır; kapsam listesi yalnız metadata'dır. Tek-IP işi CIDR genişletmez ve başka IP kaydetmez. Dönen kaynak verileri ortak kanonik SQL tablolarına yazılır; manuel envanter/komşuluk tercihleri değiştirilmez. Noktasal SNMP okuması 8 saniye, SSH port ayrıntısı 10 saniye; entegrasyon adımı 25 saniye ile sınırlıdır. Üretici yeteneği/veri eksikse bütün ağ taramasına sessizce genişlemek yerine Sorunlu sonuç verilir.

### Açık tetikleyici ve manuel VLAN kapsamı — 4 Kasım 2026

Yeni VLAN/IP oluşturma, düzenleme, sayfa açma/yenileme, arama ve filtre yalnız SQL okur/yazar; tarama kuyruğu oluşturmaz. Kaynak okuması ancak yetkili kullanıcının IP/VLAN **Tara** isteği veya tarama grubunun takvimiyle worker’da başlar. Önceki otomatik `vlan_create` kökeni artık geçersizdir; eski bu kökenli işler worker tarafından kaynak erişiminden önce iptal edilir. Bağımsız periyodik ICMP ve mevcut günde dört switch MAC takvimi korunur.

Manuel VLAN işi, yalnız seçilen CIDR’ın uç IP’leri için hedefli gateway IP→MAC, VMware IP/NIC ve gerektiğinde backbone/switch MAC, DHCP IP/MAC ve DNS PTR okuyucularını kullanır. Tüm ARP/FDB/VMware/DHCP kayıtlarını toplayan ortak kaynak okuyucusu çağrılmaz. Gateway cevabı aynı IP işlenirken tekrar sorgulanmaz; ping yanıtı olmasa da gateway’de bulunan uç eklenir. Dört kaynak/IP çözümü ve 32 ICMP sınırı korunur. Diğer VLAN’ların sonuçları ve kaynakları emekliye ayrılmaz; yalnız hedefli sorgunun döndürdüğü ortak kaynak satırları güncellenir. Tek-IP ve manuel VLAN işleri ortak gateway öncelikli algoritmayı kullanır.

Her IP tamamlanınca tüm alanları önce `ip_resolution_results` satırına commit edilir, sonra ilgili VLAN’a bildirim gönderilir; liste ve ayrıntı yalnız bu SQL sonucunu yeniden okur. Diğer IP’lerin veya VLAN işinin tamamlanması beklenmez. Ağ hatası eski doğrulanmış sonucu silmez. İptal, CIDR/VRF/DNS/profil değişiminde hedef yeniden doğrulanır. Regresyon: `test_ipam_explicit_scope.py` (gerçek ağ erişimi kapalı; yavaş/hızlı IP sırası, commit sonrası görünürlük ve başka VLAN’a yazmama).

### Hedefli Windows DHCP hata ayrımı — 4 Kasım 2026

Rezervasyon sorgusundaki `DHCP 20018` (istemci rezervasyonlu değil) tam hedefli okumayı durdurmaz; IP kiralaması ve aynı MAC'in kapsamlardaki ters araması devam eder. DHCP sağlayıcısının `ObjectNotFound` olarak işaretlediği `20013`/`1168` kayıt yok yanıtıdır. `20013` veritabanı/okuma hatası olarak gelirse boş sonuç sayılmaz. Yetki, modül, servis, zaman aşımı ve bilinmeyen komut hataları görünür sorun olarak kalır; eski doğrulanmış alanlar korunur. Metin içinde sayı aranarak hata yutulmaz: yalnız DHCP/Win32 sağlayıcı kimliği ve hata kategorisi değerlendirilir.

`20016` (`ERROR_DHCP_INVALID_DHCP_CLIENT`), [Microsoft'un hedefli istemci okuma sözleşmesinde](https://learn.microsoft.com/en-us/windows/win32/api/dhcpsapi/nf-dhcpsapi-dhcpv4getclientinfo) aramaya karşılık gelen IPv4 kira kaydı olmadığında da döner. Doğrulanmış IP/MAC filtreleriyle yapılan `Get-DhcpServerv4Reservation` veya `Get-DhcpServerv4Lease` sorgusunda sağlayıcı kimliği bu komutla eşleşiyor ve kategori `InvalidType`/`ObjectNotFound` ise kayıt yok kabul edilir. IP sorgusundan sonra diğer kapsamlardaki aynı MAC araması sürer; başka IP'de rezervasyon bulunursa çakışma denetimine aktarılır. Kapsam listeleme, farklı komut, `ReadError` veya sınıflandırılmamış `20016` hata olarak kalır. Kayıtsız sabit IP tek başına DHCP arızası değildir; fiziksel bağlantı doğrulanamaması ayrı sorundur.

WinRM komutu başarısızsa en çok 16 KiB hata akışı bellekte sınıflandırılır; SQL/API'ye yalnız sabit Türkçe açıklama, güvenli hata türü ve varsa sayısal Windows kodu yazılır. Ham PowerShell/WinRM yanıtı, kullanıcı ve sırlar saklanmaz. Var olan SQL sonuçlarının hata kaydı yeniden yorumlanmaz; sonraki kullanıcı taraması veya zamanlama günceller. Bu düzeltme dağıtımda kaynak sorgusu başlatmaz.

Ağsız regresyon: `test_ipam_dhcp_point_errors.py`; `NETRIX_TEST_PWSH` veya PATH'teki PowerShell ile gerçek üretilen script, sahte DHCP modülü üzerinde çalıştırılır. Rezervasyonsuz aktif kira, tüm kayıtlarda yok yanıtı (`20018`/`20013` ve `20016`), sonraki kapsamda ters MAC rezervasyonu, kayıt yok yanıtıyla başarılı IP çözümü, gerçek yetki/veritabanı/okuma/kapsam hatası ve güvenli hata aktarımı doğrulanır. PowerShell uygulamanın çalışma bağımlılığı değildir. Kaynaklar: [rezervasyon sorgusu](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4reservation), [DHCP hata kodları](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/dhcp/dhcp-server-management-api-error-codes), [istemci kaydı okuması](https://learn.microsoft.com/en-us/windows/win32/api/dhcpsapi/nf-dhcpsapi-dhcpgetclientinfov4).

### Zamanlanmış VLAN işi

Aynı `pipeline.resolve` dallanması kullanılır. Gateway snapshot'ı başta bir kez okunur; VMware snapshot'ı bir kez, yalnız fiziksel dal varsa switch ve DHCP snapshot'ları bir kez okunur. IP/MAC indeksleri bellekte bir kez hazırlanır. ICMP hazır sonuçları ve tamamlanan IP'nin tüm alanları, diğer IP'leri veya tüm işin bitmesini beklemeden görünür. Dört eşzamanlı IP çözümü ve dört kaynak okuması sınırı vardır. İptal veya kapsam/profil değişiminde yanlış hedefe yazılmaz. Eksik kaynaklar son başarılı snapshot'ı temizlemez ve yeni kesin eşleştirme üretmez. Sayfa açma/yenileme hiçbir kaynak işini tetiklemez; 30 saniyelik bağımsız ping devam eder.

Regresyonlar: `test_ipam_gateway_pipeline.py`, `test_ipam_point_protocols.py`, `test_ipam_address_scan.py`, `test_vlan_scan_pipeline.py`, `test_ipam_incremental.py`; MariaDB: `ipam_results_mariadb_check.py`. Kaynaklar: [VMware SearchIndex](https://developer.broadcom.com/xapis/virtual-infrastructure-json-api/latest/virtual-infrastructure/search-index/), [DHCP rezervasyon filtreleri](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4reservation), [Q-BRIDGE FDB](https://www.rfc-editor.org/rfc/rfc4363.html), [AOS-S port/trunk sorgusu](https://arubanetworking.hpe.com/techdocs/AOS-S/16.10/MCG/KB/content/kb/sho-tru.htm).

## Açık kullanıcı eylemi, zamanlama ve salt okunur sayfalar — 3 Kasım 2026

Tam VLAN taraması **IP adres yönetimi → Ayarlar → Tarama** grubunun günlük/haftalık/aylık zamanlaması, yetkili kullanıcının VLAN başlığındaki **Tara** düğmesi ile başlar. Sayfa/ayrıntı açmak, aramak, filtrelemek, yenilemek, IP kaydetmek ve mevcut VLAN’ı düzenlemek iş kuyruğuna kaynak okuması eklemez. Yeni VLAN kaydı tarama işi oluşturmaz. Operatör/yönetici için `POST /ipam/vlans/{id}/discover` tam taramayı, `POST /ipam/vlans/{id}/ping` yalnız kayıtlı IP’lerin ICMP kontrolünü kuyruğa ekler (HTTP 202); izleyici bu eylemleri başlatamaz. Bağımsız entegrasyon `sync` çağrısı HTTP 409 döndürmeye devam eder. Eski VLAN `discovery_enabled` ve bağımsız entegrasyon `interval_seconds` zamanlamaları devreden çıkarılmıştır; API bunların yeniden etkinleştirilmesini reddeder. Etkin kaynak tam taramanın worker adımında okunur; HTTP isteği ağ okumasını beklemez.

Periyodik ping varsayılan 30 saniyedir (VLAN ayarından 10–86.400 saniye); kullanıcı sayfasından bağımsızdır ve yalnız kayıtlı IP'lere ICMP gönderir. DNS/VMware/DHCP/SNMP/SSH/API okuması veya yeni IP keşfi yapmaz; önceki kaynak bilgileri korunur. Zamanlayıcı ping son başlangıç tarihini beş saniyelik kontrollerle izler. Aynı VLAN için aktif ping işi tekildir; uzun süren tur üstüne ikinci tur bindirilmez. İki ayrı ping worker slotu, dört genel slot ve iki tam tarama sınırı içinde çalışır; aynı VLAN'ın tam taraması ping'i bloke etmez. Hedefler en çok 32 eşzamanlı iş içindedir; hazır sonuçlar commit edildikten sonra durum yayımlanır. Süreyi aşan tur yoğunluğu sonraki başlangıcı geciktirebilir; eski sonuç yeni ping yanıtı gibi yazılmaz.

Ping bildirimi `ipam_ping`, kaynak güncellemesi `ipam_update`/VLAN kimliği taşır. Açık IPAM listesi ve ayrıntısı yalnız kendi DB yanıtını yeniler; oda/cihaz referanslarını yeniden toplamaz. Görünür sayfada 10 saniyelik DB yenilemesi kopuk WebSocket için yedektir; geri dönüldüğünde DB yanıtı hemen okunur. Bu GET istekleri gerçek kaynak veya ping isteği değildir.

Tarayıcı veya üst araç çubuğundan yenileme, mevcut son tarama işini kimliği/oluşturulma zamanı/ilerlemesiyle tekrar gösterir; yeni iş oluşturmaz. İlerleme alanı aynı işin `ipam_origin` kaydını **Zamanlanmış tarama**, **Manuel tarama/ping** veya **Yeni VLAN’ın ilk taraması** (yalnız eski geçmiş) olarak ve kuyruğa alınma saatiyle gösterir. Eski kökensiz kayıtlar tahmin edilmez. Ek zamanlama/başlatma isteği veya grup sorgusu yapılmaz. Regresyonlar: `test_refresh_restores_same_scan_without_requeue`, `scripts/ipam_refresh_browser_check.py`.

Ping işleri arka planda yürütülür; manuel ve periyodik `ipam_ping` kayıtları Görev merkezi listesine, arama sonuçlarına, sayfalama toplamına ve çalışan görev sayacına dahil edilmez. Mevcut ping geçmişi de görünmez. Worker durumları ve canlı IPAM bildirimleri korunur; tam tarama ve diğer görevler listelenmeye devam eder.

### Tarama sürerken tamamlanan sonuçlar

IP/ICMP/DNS sonuçları, aynı 32’lik grupteki yavaş IP’leri veya sonraki kaynak aşamalarını beklemeden kaydedilir. Hazır sonuçlar en fazla 200 ms’lik bir toplama penceresinde birleştirilir; bu pencere DB/HTTP yanıt süresi garantisi değildir. IP ekleme/güncelleme ve ilerleme aynı transaction’da commit edilir, ardından Redis okuma revizyonu ve yalnız ilgili VLAN’ın `ipam_update` bildirimi yayımlanır. DNS tamamlama adımı da hazır yanıtları bekletmez. Bir switch/gateway okuması commit edildiğinde diğer cihazların bitmesi beklenmeden bildirilir. Son eşleştirme sayımı tabloyu açan bir onay adımı değildir; liste/ayrıntı her aşamada mevcut geçerli kanıtlardan okunur.

Açık liste, IP ayrıntısı ve tarama ilerlemesi bu bildirimle DB’den yenilenir; tüm uygulamanın oda/cihaz referansları tekrar yüklenmez. Bağlantı yokken mevcut 10 saniyelik DB yenilemesi sürer. Bu okumalar ek tarama başlatmaz. İptal/hata durumunda bekleyen en çok 32 probe temizlenir; tamamlanıp commit edilmiş sonuçlar korunur. Kaydetmeden önce güncel VLAN kapsamı, iptal ve DNS seçimi kontrol edilir.

DHCP/VMware’in kendi snapshot’ı atomik kalır: çoklu VM/NIC/MAC çakışması ve kaybolan kayıtlar eksik bir snapshot’tan kesinleştirilmez. Başarılı kaynak snapshot’ı tamamlandığında alanları diğer tarama aşamalarını beklemeden görünür olur. Regresyonlar: `test_ipam_incremental.py`, `test_ipam_network_worker.py`, `test_ipam_scan_capacity.py`, `ipam_live_browser_check.py`.

Kuyruk işleri iç `ipam_origin` alanıyla `schedule`, `scheduled_source`, `ping_timer` veya `manual` kökenini taşır. Manuel eylemde kimliği doğrulanmış kullanıcı `requested_by` ile kaydedilir; HTTP gövdesi köken seçemez. Worker kökensiz, eski `vlan_create` veya kullanıcısız manuel işleri ağ erişiminden önce iptal eder. Aynı VLAN/tür için aktif iş tekildir; kullanıcı eylemi grup takvimini ve çalışma sayısını değiştirmez. Bağımsız entegrasyon aralıkları kapalıdır; kaynaklar VLAN/IP işinin içindedir. Önceki `20261103_41` migration’ının ping ve eski işleri emekliye ayırma davranışı korunur. Bu değişiklik şema dönüşümü veya tarama başlatmaz. Testler: `test_vlan_initial_scan.py`, `test_vlan_scan_pipeline.py`, `test_ipam_schedule_only.py`, `test_ipam_explicit_scope.py`.

## Bağımsız switch MAC önbelleği — 3 Kasım 2026 (taraması 5 Kasım'da kaldırıldı)

**5 Kasım 2026 kararı:** Proje sahibinin kararıyla `switch_mac_scan` işi, dört günlük
zamanlaması, **Şimdi tara** eylemi, `/ipam/switch-mac-cache` API'si ve Ayarlar paneli
kaldırılmıştır. Aynı veriyi tarama grubu okuyup yazar. Mevcut `mac_port_records`
satırları silinmez ve grup taramasıyla güncellenir. Yedek eşleştirmenin en çok yedi
saatlik kaynak kuralı, günlük grup için 25 saattir. Eski kuyruk kaydı worker tarafından
desteklenmeyen tür olarak iptal edilir, geçmiş iş kayıtları görünmeye devam eder.
Aşağıdaki kanıt ve belirsizlik kuralları geçerlidir; zamanlama ve API hükümleri geçersizdir.

Proje sahibinin ek talebiyle `switch_mac_scan` işi, tam VLAN taramasından bağımsız olarak tüm etkin, yetkili envanter kapsamına ve SNMP profiline sahip switchlerin Q-BRIDGE FDB, VLAN/FID, arayüz ve komşuluk kanıtlarını okur. Türkiye saatiyle 00:00, 06:00, 12:00, 18:00'de bir kez kuyruğa alınır. Kesinti sonrası geçmiş slotlar yığılmaz; mevcut slot bir kez değerlendirilir. Ayarlar → Tarama → Switch MAC tablosu içindeki **Şimdi tara** eylemi operatör yetkisiyle aynı tekil kuyruğu kullanır. Etkin iş varsa ikinci iş oluşmaz. Kaynak başına 185 saniye sınır, en çok on eşzamanlı cihaz okuması ve taşıma hatalarında üç kontrollü deneme vardır. İptalde bekleyen görevler temizlenir. Ping, DNS, VMware, DHCP, gateway ARP/NDP ve trafik sayaçları bu işte okunmaz; envanter veya Komşuluklar değiştirilmez. Sayfa GET istekleri yalnız DB okur.

`switch_mac_snapshots` her switchin son eksiksiz kanıtını ve kaynak bağlamını; `switch_mac_entries` VRF/VLAN/MAC/port/ifIndex konumlarını tutar. Başarılı okuma yalnız değişen bağları ekler/siler; aynı bağların kimlikleri korunur. Eksiksiz boş FDB eski bağları kaldırır. Eksik, zaman aşımına uğramış veya 65.536 satırlık sınırda kesilmiş tablolar başarılı sayılmaz: önceki satırlar teşhis için korunur, kaynak sağlıksız işaretlenir ve eşleştirmede kullanılmaz. Sonuçlar her switch commit'inden sonra IPAM WebSocket bildirimiyle görünür olur. İş ayrıntısı kaynak hatalarını sınıfıyla saklar; sırlar ve ham hata metni dışarı verilmez.

Her switch okuması sonrasında yeni sonuç tablosunun yalnız boş veya MAC önbelleğinden türemiş bağlantıları worker'da yeniden değerlendirilir. Ana VMware/komşuluk/manuel bağlar değişmez. Güncel gateway kimliği varsa yeni port doğrudan sonuca işlenir; önbellek bağlantısı kaybolur veya kaynak başarısız olursa son bilinen port korunup Sorunlu işaretlenir. Ek DNS/VMware/gateway sorgusu yapılmaz; tamamlanan yeni sonuç, önceki noktasal işin eski hata başlığını geçersiz kılar.

Mevcut VMware/komşuluk/FDB ve geçerli manuel bağlantı önceliği korunur. Yalnız mevcut bağlantısı/adayı/çakışması olmayan ve **güncel gateway ARP/NDP kanıtında tek MAC kimliği** bulunan IP'ler yeni tabloda aranır. Görüntülenen manuel MAC otomatik kimlik kanıtı değildir. Arama `(vrf_id, vlan_vid, mac_address)` birleşik indeksiyle, toplu yapılır. Kaynak en çok yedi saatlik, sağlıklı ve güncel envanter/profil bağlamıyla aynı olmalıdır. Switch arşivlenir, VRF/adres/profil değişir veya son okuma başarısız olursa önbellek bağlantı üretmez. Uplink, çok MAC'li transit port, ortak FID, link durumu, tipli LLDP kimliği, çoklu NIC ve bağımsız aday belirsizliği mevcut çözümleyiciden aynen uygulanır. Geçerli çoklu port/switch bağları birlikte gösterilir; bağımsız çelişkili adaylardan biri keyfi seçilmez. Kaynak etiketi **Switch MAC tablosu** olur; hostname, otomatik MAC ve işletim sistemi kaynak sözleşmesi değişmez.

Regresyonlar: `test_switch_mac_cache.py`, `test_switch_mac_jobs.py`; gerçek MariaDB migration/indeks doğrulaması `scripts/switch_mac_mariadb_check.py`; yerel ağsız UI/port değişimi ve erişilebilirlik `scripts/switch_mac_browser_check.py`; yalnız açık canlı test yetkisiyle `scripts/switch_mac_live_check.py`.

## Önceki kaynak çözümleyicisi — 1–3 Kasım 2026

Aşağıdaki otomatik öncelikler önceki gözlemleri yorumlayan eski çözümleyiciyi açıklar; güncel sonuçlar için yukarıdaki gateway algoritması geçerlidir. Manuel alanlar, VRF/VLAN/FID ayrımı ve kanıt güvenliği kuralları korunur.

IP adres yönetimi ve Envanter ayrı menüler ve ayrı yazma akışlarıdır. Bu sözleşme proje sahibinin açık yeni talebi olmadan değiştirilemez. IPAM yalnızca VLAN içindeki IP kayıtlarını yönetir; bir IP gözlemi cihaz envanterine veya Komşuluklar'a kayıt eklemez. Envanter → Ağ keşfi, IPAM taramasını tetiklemez ve keşif gözlemleri IPAM alanlarını beslemez.

| IP alanı | Otomatik kaynak |
| --- | --- |
| Hostname | Önce VLAN'ın seçili DNS kaynağı (seçim yoksa sistem PTR); DNS adı yoksa güncel, tekil IP/NIC ile doğrulanmış VMware VM adı; o da yoksa kanıtlı MAC ile eşleşen DHCP adı |
| MAC | DNS hostname'i veya açık guest IP ile doğrulanan tekil VMware VM/NIC; bu eşleşme yoksa aynı VRF ve VLAN CIDR'ına doğrudan bağlı gateway arayüzünün ARP/NDP tablosu |
| Bağlı cihaz / Port | Bağlantı → Komşuluklar'ın güncel LLDP/CDP kanıtı; gateway MAC'i ile VLAN'a ait switch FDB eşleştirmesi; VMware VM'lerinde entegrasyonun doğruladığı sanal switch/NIC portu |
| İşletim sistemi | Yönetim → Entegrasyonlar → VMware |
| Kabin No | Aynı VRF/IP ile cihazın kendi kabinet yerleşimi; oda katı/bölümü/kabinet numarası/başlangıç U (`L-0/A/4/13U`) |

DHCP kiralamaları/rezervasyonları IP kaydı ve VMware NIC eşleşmesi için yardımcı kanıttır. Doğrulanmamış DHCP/VMware adı DNS yerine; DHCP MAC'i otomatik MAC alanında; cihaz adına bakılarak tahmin edilmiş bir işletim sistemi VMware yerine gösterilmez. DNS hostname'i veya çelişkisiz doğrudan guest IP VMware'de tekil VM/NIC olarak doğrulanırsa MAC önceliği VMware'dedir; bu istisnalar dışındaki kayıtlar gateway kuralını kullanır. Kaynağı olmayan otomatik değer boştur.

### DNS adı olmayan doğrulanmış VM — 3 Kasım 2026

Kullanıcının yeni talebiyle DNS gözlemi boş, olumsuz, bulunamıyor veya süresi dolmuşsa doğrulanmış VM/NIC gözlemindeki ad otomatik Hostname alanında gösterilir (`field_sources.hostname=vcenter`). Bunun için MAC seçiminde kullanılan güncel ve çelişkisiz doğrudan guest IP kanıtı gerekir; aynı seçilmiş NIC'in adları normalize edildiğinde tekil olmalıdır. Sadece kaynak gözlemleri tablosunda görünen, eski, emekliye ayrılmış veya başka IP'den `matched_by` ile taşınmış bir ad bu önceliği kazanmaz. DNS adı yeniden bulunduğunda DNS, manuel ad girildiğinde manuel değer önceliklidir. VMware adı DNS eşleştirmesine veya yönetilen `ip_addresses.hostname` alanına kopyalanmaz; IP/NIC çözümlemesi fallback adı uygulanmadan tamamlanır. Liste, ayrıntı, genel arama ve gelişmiş filtre aynı türetilmiş Hostname/MAC/OS değerlerini kullanır. Mevcut kayıtlar yeniden tarama gerektirmeden düzelir; sonraki zamanlanmış snapshot'ta kaybolan/çelişen VM kanıtı fallback adı geçersiz kılar. Fiziksel ESXi hostunun DNS sözleşmesi değişmez.

### DHCP adı ve Q-BRIDGE portu — 3 Kasım 2026

DNS ve doğrulanmış VMware adı yokken, güncel DHCP rezervasyonu veya `Active`/`ActiveReservation` kiralamasının adı gösterilir. DHCP'nin geçerli MAC'i mevcut otomatik gateway/VMware kimliğiyle eşleşmeli; birden fazla DHCP kaynağındaki MAC/ad çakışmasında ad seçilmez. Eski, `present=false`, süresi dolmuş/pasif kiralama ve kanıtsız DHCP MAC'i hostname kaynağı değildir. Kaynak `windows_dhcp` olarak işaretlenir; MAC gateway/VMware'den, işletim sistemi VMware'den gelmeye devam eder. Manuel/DNS/VMware ad önceliği korunur. Gelecek zamanlanmış DHCP snapshot'ları kaybolan kayıtları emekliye ayırır; adlar manuel alanlara kopyalanmaz.

Q-BRIDGE `other(1)` durumu tek başına geçersiz kayıt değildir: [RFC 4363, dot1qTpFdbPort/dot1qTpFdbStatus](https://www.rfc-editor.org/rfc/rfc4363.html#page-50) açık, sıfır olmayan port değerinin learned(3) dışındaki durumlarda da bildirilmesine izin verir. `other(1)`, learned(3) ve mgmt(5) kayıtları ancak geçerli bridge port (1–65535), açık/adı çözülmüş arayüz, tekil VLAN→FDB eşlemesi ve güncel eksiksiz snapshot ile değerlendirilir. Invalid(2), self(4), eksik/bilinmeyen durumlar kullanılmaz. `other(1)` MAC'leri portun MAC nüfusuna da katılır; çok MAC'li/transit port tek uç gibi seçilmez. Komşuluk/uplink elemesi ve bağımsız aday çakışması korunur. Değişiklik mevcut kayıtlı switch tablolarını da doğru yorumlar; yeni kaynak sorgusu başlatmaz. Sonraki okuma grup zamanlaması veya açık Tara eylemiyle worker'da yapılır. Regresyonlar: `test_ipam_dhcp_switch.py`, `test_ipam_source_contract.py`, `test_ipam_network_worker.py`.

### Manuel bilgilerin gösterimi — 3 Kasım 2026

Proje sahibinin talebiyle kaydedilmiş manuel hostname, işletim sistemi ve MAC liste, ayrıntı, arama ve filtrelerde önceliklidir. `field_sources` bu alanları `manual` olarak belirtir; ayrıntıda kaynak **Manuel** görünür. Manuel alan boşsa yukarıdaki otomatik kaynak kullanılır. MAC adresi, iki nokta/tire/noktalı veya ayraçsız EUI-48 biçiminden küçük harfli `aa:bb:cc:dd:ee:ff` biçimine çevrilir; sıfır ve multicast adresler geçerli MAC kaydı sayılmaz. Boş alan manuel kaydı temizler. Ham DNS/VMware gözlemleri ve `managed` değerleri korunur. Manuel hostname DNS kanıtı yerine geçmez; VMware NIC/MAC/port kimliği gerçek DNS veya doğrudan guest IP kanıtından çözülür. Hostname ve işletim sistemi önceliği mevcut manuel kayıtlara da uygulanır; yeniden kaydetmek gerekmez.

Manuel MAC bağımsız `ip_addresses.mac_address` alanında tutulur (`20261103_38`); otomatik MAC ayrıca `automatic_mac_address` ile döner. Görüntüleme önceliği VMware/ARP, NIC, FDB ve komşuluk kimlik çözümlemesinden sonra uygulanır; manuel MAC otomatik bağlantı kanıtı yerine geçmez. İki değer farklıysa ayrıntıda otomatik MAC de gösterilir. Kaynak güncellemeleri manuel kaydı değiştirmez. Eski istemcinin MAC alanını göndermeden yaptığı güncelleme mevcut manuel MAC'i korur; açıkça boş göndermek temizler. Manuel MAC değişiklikleri IP atama geçmişine yazılır. Çoklu düzenleme MAC'i değiştirmez. Migration, dolu manuel kayıt varken veri kaybettirecek downgrade'i durdurur.

Düzenleyici yalnız `managed` değerlerini düzenler; dokunulmadan kaydetmek otomatik adı, işletim sistemini veya MAC adresini manuel değere dönüştürmez. Kabinet seçimi lokasyon/kat/bölüm/oda/kabinet yoluyla, oda seçimi kat/bölüm/oda yoluyla aranabilir. Aynı numaralı kabinetler seçenek kimlikleriyle ayrılır; kabinet seçimi kendi kurum/lokasyon/oda ilişkisini birlikte günceller. Eski belirsiz kabinet notu keyfi bir odaya atanmaz. Regresyonlar: `test_ipam_manual_display.py`, `scripts/ipam_manual_browser_check.py`.

Kaydedilmiş kurum/lokasyon/oda ilişkileri `manual_location` ile ayrıca döner. Fiziksel yerleşim yoksa ayrıntı tablosu bu açık seçimin kat/bölüm/oda/kabinet bilgisini **Manuel konum bilgisi** olarak gösterir; U boş kalır. Yalnız kabinet notundan oda veya U tahmin edilmez. Liste kabinet hücresinde tam konum yolunu gösterir; genel arama bu yolu da kapsar. Fiziksel yerleşim ve doğrulanmış VMware `Sanal` gösterimi önceliklidir.

Kaydedilmiş bağlı cihaz/arayüz `manual_connection` içinde ayrı okunur. Güncel otomatik bağlantı yoksa ve kanıtlar çelişmiyorsa liste/ayrıntıda **Manuel** etiketiyle gösterilir; bu seçim otomatik bağlantı, MAC, FDB veya komşuluk kanıtına dönüşmez. Güncel otomatik bağlantı varsa onun gösterimi korunur. Seçili aktif arayüz, yönetilen arayüz listesinin dışında kalmışsa düzenleyicide mevcut seçim olarak korunur. Arşivlenmiş cihaz/silinmiş arayüz bağlantısı yeniden geçerli gösterilmez.

Eski sütun tercihleri bir kez yükseltilerek hostname/işletim sistemi/kabinet/lokasyon alanlarını görünür kılar. Sonraki sütun seçimleri korunur; IP kaydını kaydetmek dolu manuel alanların sütunlarını hemen görünür yapar. Form açıklamaları kontrolün altında ayrı grid satırındadır; işletim sistemi, oda/kabinet ve gateway kutusu aynı standart yüksekliktedir.

VMware sanal makinesi olduğu güncel eşleşmeyle doğrulanan IP adreslerinde Kabinet no `Sanal` gösterilir. Bu türetilmiş değer liste, ayrıntı ve düzenleme ekranında aynıdır; manuel kabinet kaydı korunur. Süresi dolmuş VMware gözlemi bu gösterimi oluşturmaz. Hostname ile doğrulanmamış ve gateway MAC ile çelişen VMware gözlemi de kullanılmaz.

## Bağlantı eşleştirmesi

- IPAM okuması, envanterdeki aktif switch/router/firewall cihazlarının kayıtlı SNMP profillerini kullanır. Yeni erişim profili veya ağ keşfi kapsamı istemez. Okuma worker'dadır; envanter alanlarını, arayüzleri veya komşulukları değiştirmez. Ayrı `ipam_network` gözlemleri kullanılır; eski `discovery` gözlemleri bağlantıya temel olmaz.
- Gateway arayüzü, IP-MIB arayüz adresi/prefix kanıtıyla VLAN CIDR'ını kapsamalıdır; IPAM, bağlı gateway ağının bir alt bloğunu yönetebilir. FortiOS'un VDOM içeren adres indeksleri, ham dört oktetlik adres/maskeleri ve uzunluk okteti olmayan prefix RowPointer biçimi açık alan/ifIndex kanıtıyla çözülür. Normal bir hostun ARP tablosu kaynak değildir. Hostname ile doğrulanmış VMware NIC yokken aynı IP için birden fazla gateway MAC'i varsa MAC ve kesin bağlantı boş bırakılır; kanıtlar ayrıntıda gösterilir. VMware önceliği kullanıldığında ham gateway kanıtları ve gateway çakışması ayrıca korunur.
- Q-BRIDGE `dot1qTpFdbPort` içindeki FDB kimliği VLAN numarası kabul edilmez. `dot1qVlanFdbId` ile VLAN → FDB kimliği, ardından bridge port → ifIndex → arayüz adı zinciri izlenir. Paylaşılan FDB, eksik eşleme, tamamlanmamış tablo, kapalı veya kimliği çözülemeyen port bağlantı olarak seçilmez.
- Komşuluklarda yalnızca güncel, silinmemiş ve envanterdeki kaynak cihaza ait kayıt kullanılır. Uzak IP veya tanımlı LLDP MAC alt türü eşleşmelidir. Ad/hostname benzerliği ve kullanıcı tarafından değiştirilmiş görünen etiket kimlik kanıtı değildir.
- Uplink portları ve birden çok MAC taşıyan transit portlar uç cihazın fiziksel portu diye gösterilmez. Son switch seçimi cihaz adı veya tür sıralamasıyla yapılmaz.
- Birden çok bağımsız port adayı varsa seçim yapılmaz. Ortak, geçerli LLDP chassis UUID'si veya aynı cihazdaki aynı LAG kimliğiyle kanıtlanan çoklu NIC/port bağlantıları birlikte gösterilebilir.
- Güncellik süresi VLAN'ın keşif aralığının iki katıdır; 5 dakika–24 saat arasında sınırlandırılır. Daha yeni boş/başarısız okuma eski pozitif eşleşmeyi geçersiz kılar. IPAM'dan yeni komşuluk üretilemez; kullanıcı tarafından silinen komşuluk yeniden oluşturulmaz.
- Hostname temelli VMware MAC önceliğinde seçili DNS kaynağının güncel hostname'i ile VMware hostname'i tam eşleşmelidir; yalnızca harf büyüklüğü ve sondaki nokta normalize edilir. Kısa ad/FQDN benzerliği kullanılmaz. Tek VM içindeki NIC, önce guest IP ile; bu yoksa tek NIC ile veya çoklu NIC içinde gateway MAC kanıtıyla seçilir. Aynı hostname birden fazla VM'deyse, IP birden fazla NIC'teyse veya NIC'in MAC'i çelişkiliyse VMware önceliği uygulanmaz. Guest IP olmadan da hostname ile tekil kart doğrulanabilir. MAC, OS ve sanal port aynı seçilmiş NIC gözleminden gelir; fiziksel FDB çözümlemesi de seçilen MAC ile yeniden yapılır.
- **3 Kasım 2026 MAC düzeltmesi:** DNS adı VMware adıyla uyuşmasa da güncel VMware gözleminin açık `guest_address` alanı IP'ye eşitse tekil integration/VM/NIC ve tutarlı geçerli MAC doğrulanır. Gateway kimliği varsa aynı MAC olmalı; gateway çakışması, birden fazla VM/NIC/integration veya aynı NIC'teki çelişkili MAC bu yolu kapatır. `matched_by` ile başka IP'den taşınmış DHCP/gateway/DNS ilişkilendirmesi doğrudan guest IP sayılmaz; eski/`present=false` gözlem kullanılmaz. Diğer IP'lere ait NIC'ler seçili NIC'in MAC/portuna karıştırılmaz. DNS adı varsa korunur; yoksa aşağıdaki doğrulanmış VMware adı kuralı uygulanır. MAC, OS ve sanal port aynı seçili VMware gözleminden gelir. Mevcut kayıtlar yeniden taramadan liste/ayrıntı/arama/filtreye yansır; sonraki başarılı zamanlanmış VMware snapshot'larında kaybolan eşleşme emekliye ayrılır. Regresyon: `test_ipam_vmware_mac.py`.
- Hostname doğrulaması olmayan VMware IP/NIC kaydı gateway MAC'iyle çelişirse o VM'nin işletim sistemi/bağlantısı o IP'ye atanmaz. VMware guest IP bildirmese de tekil NIC, gateway MAC'iyle eşleştirilebilir; gateway kanıtı yoksa DHCP yardımcı eşleşmesi kullanılabilir. Aynı IP için birden fazla VM/NIC bağlantısı bulunursa keyfi seçim yapılmaz. Fiziksel host uplink'i VM'nin kendi portu olarak sunulmaz.

IP ayrıntıları kaynak, cihaz, port/MAC, gözlem zamanı ve belirsizlik nedenini gösterir. HTTP sorgusu ağ işlemi yapmaz; ilgili cihazlar ve son gözlemler toplu okunur. Yetkilendirilmiş yanıtların kısa süreli önbelleği değişiklik bildirimleriyle geçersiz kılınır.

### Güncel komşuluk ve fiziksel VMware hostları — 2 Kasım 2026

Proje sahibinin güncel talebiyle IPAM'ın kendi son `ipam_network` okumasındaki LLDP/CDP satırları da doğrudan bağlantı kanıtıdır. Kaynak switch aynı VRF'de aktif envanter cihazı olmalı; yerel port güncel arayüz tablosunda açık ve adı çözülmüş olmalıdır. Eski Komşuluklar kaydının güncellenmesini beklemez. Daha yeni boş veya başarısız okuma eski pozitif IPAM verisini geçersiz kılar. Komşuluklar tablosuna kayıt eklenmez, eski kayıtların tarihleri veya dışlama işaretleri değiştirilmez. Normal ham eşleşmeler mevcut kullanıcı dışlamalarını korur.

VMware entegrasyonu VM kayıtlarından ayrı `record_type=host` gözlemleri toplar: ESXi host kimliği/UUID'si, VMkernel IP/MAC'i, fiziksel NIC adları/MAC'leri/link durumları ve `QueryNetworkHint` LLDP/CDP bilgileri. Host IP'si VMkernel adresiyle ve varsa gateway MAC'iyle doğrulanır. Birden fazla host/integration aynı IP'yi sahiplenirse seçim yapılmaz. Hostlar `Sanal` olarak işaretlenmez; hostname DNS'den, IP'nin MAC'i mevcut alan sözleşmesinden gelir. Fiziksel NIC MAC'leri ayrı gösterilir.

NIC sahipliği doğrulanan hostun farklı kartları, aynı veya farklı switchlerdeki portlarıyla birlikte gösterilir. Hostun kendi VMkernel → standard/distributed switch → uplink ilişkisi ayrıca saklanır; diğer host ağları ayrıntıda belirtilir. NIC MAC'i veya tanımlı chassis kimliği + NIC adı olmayan görünen hostname benzerliği kanıt değildir. Bağımsız, güncel VMware switch ipuçları envanter switchinin yönetim IP'si ve güncel port adı/ifIndex ile doğrulanır; sayısal LLDP port ID'si doğrudan port etiketi yapılmaz. Yeni VMware veya VMware + güncel IPAM protokol kanıtı, geçmişte dışlanmış Komşuluklar satırından bağımsız olarak IPAM'da kullanılabilir; bu işlem silinen komşuluğu geri getirmez. FDB'de çok MAC bulunması tek başına hypervisor bağlantısı sayılmaz.

Aynı fiziksel NIC için iki farklı switch/port kanıtı veya farklı host sahipliği çakışma olarak gösterilir. VMware dışındaki çoklu NIC'ler, IP/MAC ile doğrulanan ortak tipli LLDP chassis UUID/MAC kimliğiyle gruplanabilir. Salt okunur IP listesi/ayrıntı sorguları yeni ağ isteği ya da envanter/topoloji yazımı yapmaz. Kaynaklar worker'da sınırlı eşzamanlılıkla okunur; fiziksel host bilgileri sonraki başarılı tam entegrasyon okumasında kaybolursa emekliye ayrılır.

Regresyonlar: `test_ipam_host_connections.py`, `test_vmware_host_adapter.py`; gerçek backend ile masaüstü/mobil ve açık/koyu tema doğrulaması: `scripts/ipam_host_browser_check.py`. API alanları mevcut JSON gözlemlerindedir; yeni tablo veya migration gerekmez. VMware API sözleşmesi: [PhysicalNicHintInfo](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.PhysicalNic.NetworkHint.html), [HostVirtualNicSpec](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.host.VirtualNic.Specification.html).

VMware dışındaki sunucularda da IP'nin ARP MAC'i fiziksel kart MAC'inden farklı olabilir. AOS-S kabiliyetli envanter switchlerinde mevcut SSH profiliyle güncel, salt okunur LLDP/CDP ayrıntısı IPAM worker'ında okunur ve yalnız IPAM gözlemine eklenir. SSH'dan gelen iki protokolün aynı chassis MAC'inde anlaşması, CDP'nin istenen yönetim IP'sini açıkça bildirmesi ve LLDP'nin tipli, geçerli fiziksel port MAC'i vermesi bağımsız cihaz/NIC sahipliği kanıtıdır. Görünen isim tek başına kullanılmaz. Bu güncel bağımsız kanıt geçmiş Komşuluklar satırını geri açmaz; IP'nin MAC alanını değiştirmez. Farklı kartlar `physical_nics` ayrıntısında ayrı MAC'leriyle, bağlı switch/portlarıyla listelenir. Standart, tek protokollü MAC çakışmaları halen belirsizdir.

SSH okuması mevcut 185 saniyelik cihaz bütçesi ve on eşzamanlı cihaz sınırının içindedir. SSH hatası sır içerebilen ham yanıtı saklamaz; yalnız hata sınıfını işaretler, geçerli SNMP verisini korur ve yeniden başlatmada başarısız ayrıntıyı tekrar okur. SSH/SNMP profil sürümü, port, adaptör ve güven ayarı değişirse sürmekteki sonuç kullanılmaz. Gateway ve ayrıntı okuyabilen kaynaklar erken toplanır; kaynak sırası bağlantı adayı seçme kuralı değildir. Ek regresyonlar: `test_ipam_ssh_peer.py`.

Protokol temelleri: [IP-MIB (RFC 4293)](https://www.rfc-editor.org/rfc/rfc4293.html), [Q-BRIDGE-MIB (RFC 4363)](https://www.rfc-editor.org/rfc/rfc4363.html). Davranış testleri: `test_ipam_source_contract.py`, `test_ipam_vmware_mac.py`, `test_ipam_network_worker.py`, `test_connection_inventory_boundary.py`.

## VLAN ve zamanlama

IP adres yönetimi → VLAN alanları, CIDR, VRF, DNS, kurum/lokasyon ve zamanlama ayarlarının sahibidir. Yeni VLAN oluşturulması tarama işi oluşturmaz. Mevcut VLAN’ı düzenlemek veya IP kaydı oluşturmak/değiştirmek yeni tarama işi oluşturmaz. IPv4 en çok 65.536 adres, 32 eşzamanlı probe ile taranır; IPv6 uzayı gezilmez, bilinen adresler kontrol edilir.

VLAN ayrıntısındaki **Tara**, zamanlamanın kullandığı `ipam_discover` akışını kullanıcı isteğiyle başlatır. **Ping** yalnız ICMP kontrolü yapar. Etkin iş varsa aynı iş döner; buton işlem boyunca devre dışıdır. VLAN yeniden açıldığında son tarama ve aşaması `GET /api/v1/ipam/vlans/{id}/scan` ile görünür.

Tarama ping/DNS kontrolünden sonra gateway/switch kaynaklarını en çok on eşzamanlı cihaz okumasıyla toplar. Her cihazda taşıma yeniden denemesi ve 180 saniyelik toplam protokol sınırı vardır. Ardından DHCP eşitlemesini, sonra VMware eşitlemesini bekler; DHCP'nin oluşturduğu VMware işi yeniden kullanılır. Her kaynak aşamasında en çok 15 dakika bekler; başarısız, iptal edilmiş, bulunamayan veya zaman aşımına uğrayan bağımlılık kısmi sonuçtur. Ana görev kaynaklar kuyruğa konunca tamamlandı sayılmaz. Kaynak okumalarından sonra yeni/ICMP yanıtı vermeyen kayıtların DNS kontrolü tamamlanır, cihaz/port kanıtları çözülür ve alan başına eşleşme sayısı kaydedilir.

Envanter keşfi ve IPAM taraması birlikte en fazla iki worker yuvası kullanır; kalan yuvalar bağımlı entegrasyonlar ve kısa görevler için açıktır. Böylece kaynak bekleyen taramalar worker'ı kilitlemez. İptal beklemeyi ve sürmekte olan IPAM okumalarını durdurur; başka taramalarla paylaşılabilen entegrasyon işi otomatik iptal edilmez. Aynı iş yeniden başlarsa IPAM ağ gözlemleri yinelenmez; güncel, başarılı ve bağlantı/profil sürümü aynı okumalar korunarak kalan cihazlardan devam edilir. Başarısız/eski okumalar veya değişen erişim bilgileri yeniden okunur. Yeni bir tarama işi önceki işin okumalarını atlamaz. Ping ve yeni IP keşif zamanlamaları ayrı kalır. Ping sonucu yalnızca güncel ICMP gözlemidir; VM güç durumu değildir.

## Gruplu tam tarama zamanlaması — 3 Kasım 2026

IP adres yönetimi → Ayarlar → Tarama ekranında ad/açıklama ile grup oluşturulur ve CIDR tanımlı VLAN'lar seçilir. Bir VLAN tek tarama grubuna bağlıdır. Eski VLAN `discovery_enabled` zamanlaması hiçbir VLAN için uygulanmaz; otomatik tam taramanın sahibi gruptur. Bağımsız ICMP takvimi ve kullanıcının Tara/Ping eylemleri sürer. Grup silinirse eski VLAN tam tarama ayarları yeniden etkinleşmez; VLAN/IP kayıtları ve başlamış işler silinmez.

Günlük/haftalık/aylık tekrar, her kaç dönem çalışacağı (1–365), saat dilimli başlangıç ve isteğe bağlı toplam çalışma sınırı (1–100.000; boşsa sürekli) saklanır. Arayüz tarih girişini ve gösterimini Türkiye saatinde yapar. Haftalık tarama başlangıcın hafta gününü; aylık tarama başlangıcın ay gününü kullanır. O günün bulunmadığı aylarda son gün seçilir; sonraki aylarda özgün gün korunur. Zamanlama alanı değişirse sayaç sıfırlanır ve yeni sürüm açılır; üyelik/açıklama veya etkinlik değişikliği sayacı sıfırlamaz. Kullanıcı açıkça geçmiş başlangıç seçerse sonraki zamanlayıcı turunda bir kez çalışır.

Zamanlayıcı her 15 saniyelik turda en fazla 100 zamanı gelmiş grubu okur. Grup satırı kilidi, sürüm/tarih UNIQUE kaydı, VLAN işlerinin mevcut `active_key` tekilliği ve ortak transaction aynı turun iki kez dağıtılmasını engeller. İş dağıtımı yarıda hata verirse oluşturulan işler ve sayaç birlikte geri alınır. Uzun duruş sonrası bir kez telafi edilir, geçmiş tüm tarihler için tarama patlaması oluşturulmaz; sonraki tarih geleceğe ilerletilir. Çalışma sayısı başlatılan/yeniden kullanılan iş dağıtım turlarını sayar, başarı garantisi değildir.

Her VLAN için mevcut `ipam_discover` işi üretilir/yeniden kullanılır; gerçek ağ işlemi HTTP isteğinde veya zamanlayıcıda yapılmaz, mevcut worker ve eşzamanlılık sınırları korunur. `enqueue` hedef doğrulaması mevcut tarama kapsamını kontrol eder. Başlatılamayan VLAN nedeni geçmişe yazılır; bütün VLAN'ları silinen grup durdurulur. Geçmiş API'si son 20 turu, planlanan/gerçek zamanı ve ilişkili işlerin güncel durumunu gösterir. Yeni kurulumda grup veya görev oluşturulmaz. İzleyici okuyabilir; operatör/yönetici kaydedebilir, yalnız yönetici silebilir.

API: `GET/POST /api/v1/ipam/scan-groups`, `PUT/DELETE /{id}`, `GET /{id}/runs`. Alembic `20261103_35`: `ipam_scan_groups`, `ipam_scan_members`, `ipam_scan_runs`. Hedefli doğrulama: `test_ipam_scan_schedules.py`, `ipam_scan_mariadb_check.py`, `ipam_scan_browser_check.py`. MariaDB model/şema karşılaştırması yeni üç tabloya uygulanır; mevcut günlük tablolarının DESC indekslerinin MariaDB tarafından ASC olarak yansıtılması bu kontrolün dışındadır.

## Entegrasyonlar

Yönetim → Entegrasyonlar yalnızca VMware vCenter ve Microsoft Windows DHCP içerir. Entegrasyonlar bütün IPAM VLAN'larına hizmet eder; ayrı yetkili ağ blokları listesi yoktur. Switch/router/gateway erişimi mevcut envanter cihazının şifreli profiliyle yapılır; yinelenen switch entegrasyonu oluşturulmaz.

VMware IP/MAC, işletim sistemi, güç durumu, VM/NIC ve sanal switch/port grubu kanıtını; DHCP rezervasyon ve aktif kiralamaları sağlar. Aynı adres farklı VRF'lerde belirsizse otomatik VLAN ataması yapılmaz. Eşitleme, zamanlanmış veya kullanıcı tarafından başlatılmış tam taramanın kaynak adımıdır; bittiğinde bağımsız ping/DNS işi veya başka bir eşitleme başlatmaz. Sırlar API ve loglara dönmez.

## Silme ve menü sınırı

VLAN silme önizlemesi IP sayısını gösterir. Silme VLAN'ın ping/keşif işlerini iptal eder; VLAN ve IP gözlemlerini kaldırır. Envanter ve entegrasyon kayıtları korunur. IPAM'a ait sunucular Bağlantı cihaz listesine taşınmaz. Ortak kurum/lokasyon ve kabinet tanımları kullanılmaya devam eder.

VLAN IP listesindeki ve IP ayrıntısındaki Kabin No, fiziksel yerleşim varsa oda/kabinet ilişkilerinden tek toplu sorguyla üretilir. Seçilmiş üst switchin kabineti kullanılmaz. Fiziksel yerleşim, eski manuel kabinet notunun görüntülenmesine göre önceliklidir; manuel not değiştirilmez ve yerleşim yoksa kullanılabilir. Fiziksel yerleşim `rack_position` ile belirtilir; IP düzenleyicide salt okunur gösterilir ve kaydetme sırasında manuel alana kopyalanmaz. Güncel VMware VM eşleşmesinde önceki “Sanal” davranışı korunur. Kabinet numarası tanımlandığı biçimiyle gösterilir; eski ve eksik oda alanları `—` olarak belirtilir. Oda, U ve kabinet düzenlemeleri mevcut yayın/önbellek geçersizleştirme akışını kullanır.

IP ayrıntısındaki **Kabinet yerleşimi** ayrı bir tabloda Lokasyon → Kat → Bölüm → Oda ismi → Kabin → U no sırasıyla gösterilir. Bu alanlar aynı toplu sorgudan gelen `rack_location` nesnesini kullanır; lokasyon kabinetin bağlı olduğu lokasyondur. Yapılandırılmamış yerleşim ve manuel nottan oda/kat türetilmez. VMware IP'sinde fiziksel tablo yerine “Sanal” gösterilir. Mobilde tablo kendi içinde yatay kayar.

## VLAN adres matrisi — 4 Kasım 2026

Açık VLAN’ın **Yeni IP kaydı** düğmesi yanındaki **VLAN incele**, yalnız o VLAN’ın IP adreslerini bir pencerede gösterir. Genel VLAN listesinde bu düğme bulunmaz. Pencerede VLAN değiştirici veya tüm VLAN listesini okuyan sorgu yoktur; açık VLAN ve CIDR salt okunur gösterilir. Yeşil/○ boş adres mevcut VLAN kapsamlı IP ekleme formunu adres seçilmiş olarak açar; kırmızı/● dolu adres mevcut IP ayrıntısını açar. Ayrıntı kapatıldığında aynı matrise dönülür. İzleyici matrisi ve dolu adreslerin ayrıntısını okuyabilir, IP ekleyemez.

Boş/dolu hesabı IP ekleme listesinin SQL kuralını paylaşır: en son güncel ICMP yanıtı olan, rezerve veya gateway işaretli adresler doludur; diğer adresler boştur. Önceki pasif keşif kaydının bulunması adresi tek başına dolu yapmaz. Kayıt sırasında mevcut kilit ve yeniden doğrulama davranışı korunur. VLAN/VRF kapsamları birbirine karışmaz. Pencere açılışı, adres araması ve sayfalama kaynak taraması başlatmaz; mevcut WebSocket bildirimleri ve görünür ekranın 10 saniyelik SQL yenilemesi durumları günceller.

`GET /api/v1/ipam/vlans/{id}/inspection` yalnız veritabanını okur. Yanıt en fazla 256 adres, tam adres/varsa kayıt kimliği, boş/dolu durumu, sayfa sayıları ve metin türünde önceki/sonraki ofsetleri içerir. Tam IP araması ilgili sayfaya gider. IPv4 ağ/yayın adresleri /31 ve /32 dışında listelenmez; IPv6 aralıkları bütünüyle üretilmez. Büyük IPv6 kapasite ve ofsetleri JavaScript sayı hassasiyetinden etkilenmez. Şema veya yeni görev türü eklenmez. Doğrulama: `test_ipam_allocation.py`, gerçek yerel API kullanan ve protokol işleri engellenmiş `scripts/vlan_inspector_fixture.py` ile `scripts/vlan_inspector_browser_check.py`.

## Manuel tarama SQL sözleşmesi — 5 Kasım 2026

- Kullanıcının IP ayrıntısında **Tara** ve VLAN içinde **Tara** eylemleri yalnız
  kanonik SQL kaynaklarını yeniden eşleştirir. SNMP, SSH, VMware, DHCP, DNS veya
  ICMP istemcisi çalıştırmaz. NIC-Teaming de SQL DNS/LLDP/CDP kayıtlarını kullanır.
- VLAN işlemi yalnız seçili VLAN/VRF/CIDR içindeki kayıtları işler; kaynak SQL'de
  bulunan yeni adresleri içeri alabilir. Kaynağın zamanı korunur; yeniden hesaplama
  eski gözlemi yeni gözlem yapmaz. Her IP sonucu ayrı transaction ile yayımlanır.
- Kaynak toplama zamanlanmış işlerdedir; yeni VLAN'ın ilk otomatik taraması sürer.
  Ayrı **Ping** eylemi ve periyodik ICMP işi değişmez. Sayfa açılışı pasiftir.
- SQL kaynaklarına yeniden kopyalama yapılmaz: sonuç alanları mevcut kanonik
  kayıtlara foreign key ile bağlanır. Kaynak hatasında son doğrulanmış sonuç
  korunur; çelişki/belirsizlik veya eski kaynak sonucu sorunsuz diye sunulmaz.

### SNMP okuma bütünlüğü

Envanter ve IPAM MAC okumaları MAC-port, MAC durumu ve bridge-ifIndex kolonlarını
birlikte ister. VLAN-FID ayrı metadatadır; eksikliği ham MAC-port kayıtlarının
saklanmasını engellemez ve FID hiçbir zaman VLAN kimliği varsayılmaz.

Her tablo için sınırlı GETBULK, ayrı süre bütçesi ve 65.536 satır koruması kullanılır.
Tam, zaman aşımı, SNMP hata yanıtı, desteklenmeyen ve kesilmiş okumalar ayrılır.
`source_unsupported_tables` mevcut metadata tablosu artık tüm tablo okumalarının
son durumunu, güvenli hata kodunu, satır sayısını, deneme ve başarı zamanını tutar;
anahtar cihaz+tablodur, geçmiş payload veya JSON çoğaltılmaz.

Sorgulanmayan/başarısız kolon önceki doğrulanmış alanı temizlemez. Kısmi okumada
birlikte doğrulanmış pozitif MAC/port satırları eklenebilir; yokluk çıkarımı yapılamaz.
Yalnız tam ve başarılı tablo okuması kaybolan kayıtları pasifleştirir. Eski tamamlanan
iş yeni kaydı ezmez. Arayüz numarası değişince MAC kaydının ifIndex'i de güncellenir.
Genel bağlantı eksikliği gerçek uplink kanıtı gibi raporlanmaz.

### SQL görev ayrıntısı ve ping hatası ayrımı — 5 Kasım 2026

- Görev ayrıntısı SQL sonucunda canlı okuma sayaçları (`read`/`failed`) aramaz;
  eski ve yeni sonuç biçimleri HTTP 200 ile okunur. SQL işleminin kaynaklara
  bağlanmadığı ve eksik veriyi yeniden doğrulayamadığı açıkça belirtilir.
- Değeri boş DNS kaydı, kullanılmadığı halde sonuç yaşını eskitemez. Etkin olmayan
  gateway kimliği yeni MAC/port eşleştirmesine dayanak yapılmaz. Önceki doğrulanmış
  değerlerin korunması, güncel eşleştirmenin başarılı olduğu anlamına gelmez.
- Tek ICMP sürecinin zaman aşımı/çalıştırma hatası tüm VLAN görevini durdurmaz.
  Hatalı IP için yeni ping gözlemi yazılmaz; önceki yanıt ve gözlem zamanı korunur.
  Diğer IP'ler işlenir. `ping_failed` ayrı sayılır; yanıt vermeyen IP sayısına
  eklenmez ve görev kısmi sonuç olur. Görev iptali bu hata yolunda yutulmaz.
- Testler: `test_job_details.py`, `test_ipam_sql_manual.py`,
  `test_ipam_incremental.py` (sahte protokol istemcileri; gerçek ağa erişmez).

## Envanterden salt okunur switch kanıtı — 7 Kasım 2026

Bu karar, önceki zamanlanmış IPAM switch toplaması ve canlı eksik-FID doğrulaması
izinlerinin yerine geçer. Switch kaynaklarının tek yazarı Envanter'dir.

- IPAM zamanlanmış VLAN/grup işi, manuel VLAN/IP işi ve yardımcı kaynak yolları
  switch/backbone/corner cihazına SNMP, SSH veya API oturumu açmaz. Gateway olarak
  işaretlenmiş switch de doğrudan sorgulanmaz. Gerçek gateway/router/firewall,
  VMware, DHCP, DNS ve ICMP toplaması kendi sözleşmesiyle devam eder.
- Switch/port çözümü `envanter.network_source_states`, `source_ports`,
  `source_vlan_fdb`, `source_bridge_ports`, `mac_port_records` ve mevcut
  `baglanti.neighbor_links`/`lldp_neighbors`/`cdp_neighbors` kayıtlarına dayanır.
  Mevcut servis üzerinden okunur; ikinci bir IPAM kaynak tablosu oluşturulmaz.
- Görev içinde switch kanıtı SQL'den okunur; `network.switch_mode=inventory_sql`
  olarak bildirilir ve switch ağ okuma sayısı sıfır kalır. Veri yokluğu veya
  VLAN–FID/port kanıtının eksikliği canlı sorguya dönüşmez; belirsiz port seçilmez.
- Sonuç yazıcısı mevcut MAC-port/komşuluk satırına FK ile bağlanır. IPAM adına
  envantere MAC-port satırı veya yeni kaynak durumu oluşturmaz. Kaynağın zamanı ve
  tamlık bilgisi değişmez. Başarısız eşleştirmede önceki doğrulanmış sonuç korunur.
- Regresyonlar `tests/test_ipam_inventory_only.py`: zamanlanmış gerçek worker
  yolu, SQL verisi bulunan/bulunmayan uç, gateway işaretli switch, doğrudan port
  alternatifi ve kaynak satırlarının/zamanlarının değişmediği kontrol edilir.

### Tek IP için SQL işlem süresi — 7 Kasım 2026

- Tek IP işi, kimlik ve DNS/VMware dalı belirlenmeden bütün envanter FDB'sini
  yüklemez. SQL cihaz kataloğu ayrıdır; fiziksel kanıt gerektiğinde ilgili MAC'in
  tek-MAC port adayları ve IP/MAC ile eşleşen tüm LLDP/CDP cihazları seçilir.
- Çok-MAC portlar tek başına uç kanıtı olamaz. Seçilen cihazların tam port nüfusu,
  komşulukları, VLAN–FID, kaynak bağlamı, güncellik ve uplink kontrolleri korunur;
  iki port/iki switch adayları birlikte değerlendirilir. Yeni ağ sorgusu yapılmaz.
- Noktasal SQL işlemleri ayrı, tek kapasiteli worker ve SQL yürütme sırası kullanır;
  uzun keşif/VLAN işleri ile toplu kaynak/ping yazımları bu kapasiteyi tüketmez.
- IP sonucunun yazımı genel VRF mutex'i yerine ilgili IP satırını ve sonuç satırını
  kilitler. Güncel IP/VRF/VLAN bağı yeniden doğrulanır; eski iş yeni sonucu ezemez.
- Manuel **Tara** DNS dahil mevcut SQL verisini okur. Gerçek DNS sorgusu zamanlanmış
  kaynak toplamasına aittir; bu süreyle SQL kayıt okuması birbirine karıştırılmaz.
- Regresyonlar: `test_ipam_point_latency.py`, `test_ipam_inventory_only.py`,
  `test_ipam_sql_manual.py`. Süreler üretim SQL'inde salt okunur profil ile ölçülür;
  ölçüm için switch/entegrasyon/DNS sorgusu başlatılmaz.

### Manuel VLAN SQL eşleştirme: hız ve devam noktası — 10 Kasım 2026

Manuel VLAN işi kayıtlı ve yetkili hedef IP'leri sayısal adres sırasıyla dörderli gruplara ayırır: `.1–.4`, ardından `.5–.8` gibi. Aynı grupta en fazla dört IP eşzamanlı işlenir; dört IP tamamlanmadan sonraki grup başlamaz. IPv6 adresleri de sayısal sıralanır; büyük CIDR'larda kapsam içindeki sonraki adreslerle devam edilir. Her IP için kaynaklar SQL'den okunur, gerekli hedefli DNS sorgusu yapılır. Hazır olan her IP sonucu ve ilerleme aynı kısa transaction'da hemen commit edilir ve ilgili VLAN'a bildirim yayımlanır; bunun için grubun veya VLAN taramasının bitmesi beklenmez. Liste ve açık ayrıntı bu commit edilmiş sonuçları okur. Henüz işlenmemiş IP önceki sonucunu gösterir. İptal/hata halinde mevcut grubun bekleyen işleri temizlenir, sonraki gruba geçilmez; commit edilmiş sonuçlar korunur. Önceki serbest dört eşzamanlı IP davranışı bu dörderli grup kararıyla değiştirilmiştir.

Gateway kaynak adreslerini içeri alırken tam switch envanteri hazırlanmaz. Fiziksel kanıt gerektiğinde ortak görünüm bir kez hazırlanır. MAC-port yedek kanıtı için bağlam sütunları ve SNMP/SSH profil sürümleri toplu okunur; sütun başına SELECT ve IP başına aynı topoloji projeksiyonu üretilmez. Aynı iş içinde en fazla sekiz aday-kümesi görünümü bellekte paylaşılır; kaynak kimliği/gözlem/güncelleme zamanı ve erişim bağlamı değişirse yeniden hazırlanır. SQL'ye kaynak kopyası veya yeni payload yazılmaz. Gateway kimliği, 25 saat sınırı, VLAN/FID, uplink elemesi, belirsizlik ve NIC kanıt kuralları değişmez.

Aynı görev yeniden başladığında sabit `sql_started_at` ve giriş imzası kullanılır. Güncel sonuç tablosunda bu başlangıçtan sonra tamamlanmış, IP/VRF/VLAN bağı aynı olan kayıtlar atlanır; ilerleme bu sonuçlardan yeniden hesaplanır. CIDR/VLAN kimliği, DNS, hedef IP/teaming seçimi veya profil/entegrasyon ayarı değişirse başlangıç yenilenir. Yeni kullanıcı isteği yeni görev olduğundan tekrar eşleştirme yapar. Daha yeni tek-IP sonucu eski VLAN kararıyla ezilmez. Yeni tablo/migration gerekmez; sonuçların tek SQL sahibi değişmez.

Ağsız regresyonlar: `test_ipam_sql_throughput.py` (eski kodda üç ana hata yeniden üretildi), `test_ipam_sql_manual.py`, `test_switch_mac_cache.py`, `test_ipam_point_latency.py`, `test_ipam_inventory_only.py`. Performans karşılaştırması yalnız SQL okuyan ayrı süreçte, aynı IP/MAC ve aynı kanıtlarla yapılır; ölçüm kaynak sorgusu veya gerçek ağ taraması başlatmaz.

## DNS yenileme ve komşusuz uçta MAC–port — 10 Kasım 2026

Bu karar, manuel IP/VLAN işlerinin DNS'i yalnız SQL'den okuması kuralının yerine
geçer. Yetkili manuel IP/VLAN taraması worker'da yalnız seçili hedefler için VLAN'ın
DNS sunucusuna PTR sorgusu yapar. Zamanlanmış tarama da aynı DNS kaynağını kullanır.
Başarılı yanıt kanonik `ip_adres_yonetimi.dns_records` kaydına yazılır; hostname
aynı kalsa da kaydın güncelleme zamanı yenilenir, değişirse yeni hostname saklanır.
DNS için değer değişikliği yaşı üzerinden ikinci bir 24 saat kontrolü yapılmaz.
Kaynak anahtarı VLAN'ın DNS sunucusu kimliğidir; sistem DNS'i için `system` kullanılır.
VMware kimliği doğrulanmış VM dalının kaynak önceliği, manuel alanlar, pasif sayfa
okumaları ve NIC-Teaming'in DNS → SQL komşuluk dalı korunur.

LLDP/CDP ile hedef uç eşleşmiyorsa gateway MAC'i, envanter SQL'indeki VLAN/FID ve
MAC–port kanıtıyla terminal switch/yerel portuna çözülebilir. Başka FDB satırlarının
bağımlılıkları eksik olduğu için tablonun kısmi olması, kendi bağımlılıkları geçerli
pozitif satırı tek başına geçersiz kılmaz. Her adayın kendi gözlem zamanı denetlenir;
sonraki genel cihaz okuması eski MAC satırını güncel yapmaz. VRF, VLAN–FID tekilliği,
port durumu, çoklu MAC, uplink, komşuluk ve birden fazla aday kontrolleri korunur.
Komşusuz MAC–port kanıtından uzak cihaz portu, işletim sistemi veya komşu hostname'i
üretilmez; IP hostname'i DNS/öncelikli kimlik kaynağından gelir. IPAM switch'e bağlanmaz
ve envanter kaynak satırlarını güncellemez.

Regresyonlar: `tests/test_ipam_dns_mac_fallback.py`, `tests/test_ipam_sql_manual.py`
ve `tests/test_ipam_inventory_only.py`. Gerçek DNS/cihaz sorguları yerine sahte
istemciler ve yerel SQL fixture'ları kullanılır.

### Gateway boş döndüğünde envanter eşleştirmesi ve keşif kaydı temizliği

Zamanlanmış iş gateway ARP/NDP görünümünü ICMP denemelerinden sonra alır. Gateway
tekil MAC vermediğinde manuel ve zamanlanmış IP çözümü, envanterin SQL'deki
doğrudan IP komşuluğuna ve aynı IP'ye ait DHCP MAC adayına bakar. DHCP MAC'i tek
başına otomatik kimlik olmaz: aynı VLAN'daki güncel, tekil fiziksel uç portuyla
doğrulanmalı ve çelişkili gateway kanıtı olmamalıdır. Bu yolun MAC kaynağı DHCP,
port kaynağı envanter FDB'sidir. Uplink ve belirsiz portlar kabul edilmez. IPAM
switch'e bağlanmaz. PTR yokluğu ve DNS erişim hatası farklı sonuçlardır.

Yalnız zamanlanmış iş, ping yanıtı olmayan ve tüm gerekli kaynak okumaları başarıyla
tamamlanmış eski otomatik IP kaydını silebilir. Gateway, DHCP, VMware, DNS ve
envanter kanıtı bulunmamalı; bilinen MAC'in transit dahil hiçbir aktif envanter
eşleşmesi olmamalıdır. Eksik veya eskimiş envanter, okuma hatası, belirsizlik, yeni
eşleştirme, rezervasyon veya elle yönetilen IP kaydı silmeyi engeller. Silme SQL
transaction'ında doğrulanır, denetim kaydı ve VLAN bildirimi üretilir. Manuel tarama
taze gateway ve ping kanıtı üretmediği için otomatik silme yapmaz.

### AOS-CX envanterinde eksik VLAN–FID — 11 Kasım 2026

Envanter keşfinde mevcut `aruba_6100` cihazı Q-BRIDGE MAC satırları döndürdüğü
halde VLAN–FID tablosu boşsa, cihazın atanmış SSH profiliyle salt okunur
`show mac-address-table` alınır. Komut yalnız envanter worker'ında, yetkili
keşif kapsamındaki aktif cihazda çalışır; IPAM bu istemciyi çağırmaz.

Çıktı başlığı, bildirilen kayıt sayısı ve tüm satırlar doğrulanır. CLI'deki
MAC/fiziksel port, SNMP'deki aynı MAC/port satırıyla birebir eşleşmeli ve
tek VLAN bildirmelidir. İki kaynaktan üretilen doğrulanmış VLAN aynı
`envanter.mac_port_records` satırına yazılır; FID'nin VLAN olduğu varsayılmaz,
global VLAN–FID eşlemesi uydurulmaz ve ikinci kaynak kopyası tutulmaz.
`discovery_reads` içindeki `cx_mac_vlan` toplamanın tamlık/zaman bilgisidir.
IPAM bu satırı okurken SSH profil sürümünü, satırın kanıt zamanını,
uplink/çoklu MAC/komşuluk ve belirsizlik kontrollerini korur. Mevcut SNMP
VLAN–FID eşlemesi varsa bu alternatif onun yerine geçmez.

SSH hatası başarılı SNMP toplamasını düşürmez; hata metadata'sı yazılır.
Önceki doğrulanmış satır varsa kanıt tarihi korunur; yeni SNMP okuması eski
VLAN kanıtını güncel yapmaz. Bozuk veya eksik CLI çıktısından VLAN çıkarılmaz.
Regresyonlar `test_cx_mac_vlans.py` ve `test_ipam_inventory_only.py`.
CLI biçimi: [HPE AOS-CX Layer-2 Bridging Guide](https://www.arubanetworks.com/techdocs/AOS-CX/10.13/PDF/l2_bridging_4100i-6000-6100-6200.pdf).
