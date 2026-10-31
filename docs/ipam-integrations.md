# IPAM, ağ bloğu politikaları ve entegrasyonlar

IP adres yönetimi → Ağ blokları ekranında CIDR’a tıklayın. Ağ/yayın adresleri dahil tüm IPv4/IPv6 alanı sayısal sırada, 100 adreslik sayfalarla gösterilir. Boş satırlar sanaldır; veritabanına milyarlarca boş IPv6 kaydı yazılmaz. **Yalnızca aktif IP’ler** filtresi, son 24 saatteki son ICMP sonucu yanıt veren IP’leri listeler. Filtre kapatıldığında tüm adresler yeniden gösterilir. IP satırından işletim sistemi, kabinet no ve lokasyon düzenlenir; kaynak gözlemleri bu manuel değerleri değiştirmez.

Ağ bloğu ayarlarında DNS sunucusu (IP adres yönetimi → DNS sunucuları), VLAN’ın bulunduğu envanter cihazı, kullanım uyarı yüzdesi ve ağ bloğunun tamamını yetkilendiren checkbox bulunur. Ayrıca kapsam seçme zorunluluğu yoktur. Önceden bağlanmış kapsamın hariç tutmaları/hedef listesi korunur; CIDR veya VRF değişikliği yetkiyi ve zamanlamayı kapatır. Eşik ağ bloğu listesinde ve ayrıntısında uyarı gösterir. Kullanım sayısı kullanım dışı kayıtları içermez. ICMP yanıtı olmaması adresin boş olduğunu kanıtlamaz.

- **IP durumunu kontrol et:** yalnızca kayıtlı IP’leri ping ile kontrol eder. Zamanlama en az 30 saniyedir.
- **Yeni sunucuları ekle:** yetkili kapsamı ve hariç tutmaları uygulayarak ping taraması yapar; yanıtlayan yeni IP’leri ve seçilen DNS’ten PTR adlarını ekler. Envanter SNMP okumalarını ve ilgili etkin entegrasyonların eşitlemelerini de kuyruğa alır; MAC/OS/port bilgileri bu görevler tamamlandıkça eklenir. Zamanlama en az 60 saniyedir.
- IPv6 ve 4096 adresten büyük bloklarda keşif kapsamının açık hedef listesi gerekir. Sekiz eşzamanlı ICMP işlemi, 1 saniye ping beklemesi, 3 saniye süreç sınırı ve 2 saniye DNS çözümleme sınırı vardır. API tarama yapmaz; kalıcı worker işi döndürür. İptal sonraki batch ve kayıt öncesinde kontrol edilir; kaynak eşitlemeleri ayrı Görev merkezi kayıtlarıdır.
- Yönetilen cihaz kayıtları aynı VRF’deki en uzun uygun ağ bloğuna bağlanır. Mevcut envanter, ağ bloğu oluşturulduğunda/düzenlendiğinde eldeki son gözlemlerden bağlanır; cihazdan başarılı SNMP gözlemi geldikçe güncellenir. Firewall ARP/NDP bilgisi diğer switch’lerin FDB kayıtlarıyla eşleştirilir. VMware eşleşmesi yoksa tekil fiziksel uç port seçilir. LLDP/CDP komşuluğu, güncel topoloji, SSH trunk üyeliği ve STP kök portu üzerinden tanınan geçiş portları elenir. Birden fazla uç port varsa hiçbir switch kesin bağlantı gibi gösterilmez; kanıtlar korunur.

## Yönetim → Entegrasyonlar

Yönetici VMware vCenter veya Microsoft Windows DHCP tanımlar. Sunucu adı/IP, HTTPS portu, kullanıcı/parola, yetkili ağ blokları ve isteğe bağlı eşitleme aralığı girilir. Varsayılan kapalıdır; aralık 0 manuel çalışmadır. Kaydetmek kendi başına bağlantı açmaz. Etkinleştirip **Şimdi eşitle** seçin veya en az 60 saniyelik zamanlama ayarlayın. Sırlar mevcut uygulama şifreleme anahtarıyla şifrelenir; GET/API/audit yanıtlarına kullanıcı/parola veya şifreli içerik dönmez. Düzenlemede iki sır alanı boşsa saklanan erişim bilgileri korunur; sunucu değişiminde yeniden girilmelidir.

Entegrasyon okuması 240 saniyelik toplam döngü sınırı ve sınırlı soket beklemeleriyle çalışır. İptal sonrası sonuçlar kaydedilmez; başlamış senkron API/WinRM çağrısı kendi zaman aşımına kadar tamamlanabilir.

TLS doğrulaması varsayılan açıktır. Kurumsal CA sertifikaları `secrets/ca-certificates/` dizininde, Git ve imaj dışında tutulur. Compose bu dizini `/run/secrets/ca-certificates` yoluna salt okunur bağlar. Kurumsal CA kullanmayan kurulumlarda dizin boş kalabilir; aşağıdaki değişkenler tanımlanmaz.

Kurumsal CA kurulumu:

1. Root ve varsa intermediate sertifikaların CA yeteneğini, geçerliliklerini ve zincirini doğrulayın. Yalnızca PEM açık sertifikaları kullanın; özel anahtarları eklemeyin.
2. Çalışan imajdaki `certifi.where()` dosyasının içeriğiyle kurum CA sertifikalarını birleştirerek `secrets/ca-certificates/ca-bundle.pem` oluşturun. Mevcut genel CA'ları koruyun. Bundle container kullanıcısı UID 10001 tarafından okunabilmeli; dosya izni 0644 olabilir, özel anahtar içermez. İmajın certifi paketi güncellendiğinde bundle'ı yeni genel CA dosyasıyla yeniden oluşturun.
3. Sunucudaki `.env` dosyasına `SSL_CERT_FILE=/run/secrets/ca-certificates/ca-bundle.pem` ve `REQUESTS_CA_BUNDLE=/run/secrets/ca-certificates/ca-bundle.pem` ekleyin. İlki vCenter/Python TLS, ikincisi Windows WinRM/Requests içindir.
4. `docker compose config --quiet` ve `docker compose up -d --no-build netrix-app` çalıştırın. API, worker ve zamanlayıcı yeni ortamı aynı container'dan alır. HTTPS sağlık kontrolünden sonra hedeflerin sertifika zinciri ve hostname doğrulamasıyla bağlantılarını test edin.

Formdaki TLS tercihi açıkça kaydedilir. Kurumsal CA yüklemek için doğrulamayı kapatmayın. Hiçbir cihaz, VM veya DHCP konfigürasyonu değiştirilmez.

### Microsoft Windows DHCP

Windows DHCP sunucusunda WinRM HTTPS (varsayılan 5986), DHCP Server PowerShell modülü ve uzaktan komut/rezervasyon okuma yetkisi gerekir. Kimlik `DOMAIN\kullanıcı` biçimindedir; NTLM HTTPS kullanılır. NETRIX yalnızca sabit `Get-DhcpServerv4Scope`, `Get-DhcpServerv4Reservation` ve `Get-DhcpServerv4Lease` komutlarını çalıştırır; genel kullanıcı komut alanı yoktur. IPv4 sabit rezervasyonları ve aktif dinamik kiraları okur; süresi dolmuş kiralar ve DHCPv6 içe alınmaz. Yeni rezervasyonlar rezerve, yeni dinamik kiralar atanmış olarak eklenir; kullanıcı tarafından yönetilen mevcut atama durumu değiştirilmez. Aynı adres hem rezervasyon hem kira listesindeyse rezervasyon korunur. Ethernet olmayan ClientId değerleri MAC olarak uydurulmaz.

Rezervasyonlar seçilen bloklara otomatik eklenir; ilgili etkin vCenter eşitlemesi sıraya alınır. vCenter’da tekil MAC eşleşmesi varsa konuk IP’si eksik veya farklı olsa bile işletim sistemi, güç ve NIC bilgisi rezervasyonda gösterilir. Kanıt `matched_by=dhcp_mac` ve varsa `guest_address` içerir. Bir MAC birden fazla VM/NIC’e aitse otomatik eşleşme yapılmaz.

### VMware vCenter

vSphere Web Services API (varsayılan 443) ve envanter/performans okuma yetkileri kullanılır. PropertyCollector ile VM, DSwitch, port grubu ve ESXi nesneleri sayfalı okunur: konuk IP/MAC/hostname/OS, güç durumu, sanal NIC anahtarı, gerçek switch adı, port grubu adı, DSwitch UUID/dvPort ve ESXi kimliği/adı. NIC backing içindeki switch UUID ve portgroupKey, aynı okumadaki ağ nesnelerinin adlarına çözülür; konuk işletim sistemindeki eski ağ adı bu eşleşmeyi değiştirmez. Standart vSwitch adı ESXi port grubu yapılandırmasından alınır. Guest IP/OS bilgisi VMware Tools desteği ve güncelliğine bağlıdır; hardware NIC MAC ve yapılandırılmış OS, DHCP eşleştirmesine yardımcı olur. Başarısız eşitleme önceki veriyi silmez veya başarılı sayılmaz; 24 saatten eski gözlemler güncel değer olarak birleştirilmez, geçmiş olarak görünür.

Güncel DHCP veya envanter IP/MAC gözlemi tek bir VM/NIC ile eşleşiyorsa konuk IP bilgisi eksik olduğunda da bağlantı ilişkilendirilir (`matched_by=dhcp_mac` / `inventory_mac`). Çakışan MAC gözlemleri otomatik ilişkilendirilmez. Tam ve başarılı vCenter/DHCP okumasında artık görülmeyen kaynak ilişkileri `present=false` ile geçmişe alınır; başarısız veya eksik okumada mevcut bağlantılar korunur.

## Networkü izle

IP ayrıntısında güncel vCenter bağlantısı önceliklidir: örneğin `FBU-DS / VLAN-020 / Port 89`. Bu IP için FDB geçiş switch’leri izleme seçeneği olarak sunulmaz. VMware bağlantısı yoksa doğrulanan fiziksel port sunulur. Tek bağlantı otomatik seçilir; izlemeyi kullanıcı başlatır. Çakışan VM/NIC veya fiziksel uç port adayları izleme kaynağı olarak seçilemez. Envanter portu seçimi SNMP HC sayaçlarını doğrudan 5 saniyede bir okur; cihazın tamamında SNMP walk başlatmaz. Port trafiği portun toplamıdır, yalnızca o IP’nin trafiği olarak sunulmaz. İlk örnek başlangıçtır; sayaç sıfırlanması, discontinuity ve geçersiz kapasite örnekleri hız üretmez.

DSwitch için vCenter sanal NIC seçeneği API üzerinden `net.received.average` / `net.transmitted.average` ölçümlerini okur. VMware’in `QueryPerfProviderSummary.refreshRate` aralığı (genellikle 20 saniye) ve kaynak zaman damgası korunur. Ekranın 5 saniyede yenilenmesi, VMware’in 5 saniyelik yeni ölçüm ürettiği anlamına gelmez. Aynı kaynak zaman damgası yeniden saklanmaz; veri yokluğu sıfır trafik olarak çizilmez.

Canlı işler mevcut dört eşzamanlı interaktif worker kapasitesini kullanır. Her iş 12 sorgu sürer; açık görünüm tamamlanan işi yeniler. Duraklatma, pencere kapatma ve iptal yeni sorguları durdurur. Gizli tarayıcı sekmesi işi yenilemez. Yetki/kapsam/bağlantı seçimi her sorguda tekrar doğrulanır. Canlı örnekler yedi gün saklanır; görünüm son 15 dakikayı gösterir.

## Doğrulama ve kaynaklar

`tests/test_ipam_workspace.py`: kapsam/VRF/IPv6, şifreler, rol sınırları, DNS/ICMP, gözlem güncelliği, MAC korelasyonu, DHCP→VMware ve canlı trafik sayaçları. Gerçek ağa çıkılmaz. `scripts/ipam_migration_check.py` yalnızca atılabilir `netrix_test` MariaDB’de çalışır. `scripts/ipam_browser_check.py` yerel sahte veriyle 1440, 375 ve 812 px / açık-koyu tema kontrollerini yapar. Üretim vCenter/Windows DHCP erişim testi, ilgili sunucu ve erişim bilgileri tanımlanınca yapılmalıdır.

Resmi protokol kaynakları: [Microsoft DHCP rezervasyonları](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4reservation?view=windowsserver2025-ps), [DHCP kapsamları](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4scope?view=windowsserver2025-ps), [vSphere konuk NIC bilgisi](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.vm.GuestInfo.NicInfo.html), [vSphere PerformanceManager](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.PerformanceManager.html), [pyVmomi](https://github.com/vmware/pyvmomi), [pywinrm](https://github.com/diyan/pywinrm).

## Sol menü ve tanım listeleri

IP adres yönetimi sırası: Ağ blokları → IP adresleri → VLAN alanları → Kabinetler → İşletim Sistemi → Lokasyon → DNS Sunucuları → Yönlendirme alanları.

Kabinetler ekranında kabinet no, ortak lokasyon ve açıklama; İşletim Sistemi ekranında ad ve açıklama yönetilir. Lokasyon ekranı envanterde kullanılan ortak kayıtları yönetmeye devam eder. IP formundaki işletim sistemi ve kabinet alanlarında kataloglardan seçim yapılır; eski katalog dışı metinler korunur. Konum için **Kurum → Lokasyon → Alt lokasyon** ayrı seçimlerdir. Lokasyon listesi yalnızca seçilen kurumun ana lokasyonlarını, alt lokasyon listesi yalnızca seçilen lokasyonun çocuklarını içerir. Üst seçim değişince alt seçimler temizlenir. Üç ilişki kimlikleriyle kaydedilir ve düzenlemede tekrar seçili gelir; toplu düzenlemede birlikte uygulanır. İşletim sistemi/kabinet metinleri katalog değişikliklerinde korunur; bağlı lokasyonun adı tabloda güncel katalogdan okunur.


## Kurum, lokasyon ve kabinet hiyerarşisi

Lokasyon ekranındaki **Yeni Kurum Ekle** kurum adı/kodunu oluşturur. Yeni lokasyonların kurum seçmesi zorunludur. Lokasyona girip **Alt lokasyon ekle** ile yalnızca ad girerek alt kayıt oluşturulur. Üçüncü bir lokasyon seviyesi açılamaz. `01-000001` altındaki kodlar `01-000011` ile başlar; tüm lokasyon kodları arasında ilk boş kod seçilir, silinen aralık yeniden kullanılır. Kod dağıtımı kurum satırındaki kilit/sürümle seri hale getirilir. Eski lokasyonlar otomatik bir kuruma atanmamıştır; düzenlerken doğru kurum seçilir.

Kabinet formu ana lokasyon, bu lokasyonun alt lokasyonu ve 1–60 U kapasiteyi içerir. Eski kabinetler 42 U ile korunur ve düzenlenebilir. Kabinete tıklayınca U yerleşimi açılır. Cihazlar merkezi envanterden seçilir; başlangıç U ve yükseklik girilir. Aynı U alanına iki cihaz veya aynı cihazın iki kabinete yerleştirilmesi engellenir. Yerleşimi kaldırmak envanter cihazını silmez. Envanter ve kabinet kayıtlarından fiziksel U konumu çıkarılamayacağı için başlangıçta konum uydurulmaz.

Görseller üreticinin HTTPS kaynağından yüklenir; uygulamada üretici/model eşleşmesi saklanır. Doğrulanmış JL675A, JL677A ve JL558A görselleri hazırdır. Diğer HPE/Fortinet modelleri için yerleşim ekranında resmi görsel/ürün sayfası URL'leri modele bağlanabilir. Model veya görsel bilinmiyorsa yer tutucu açıkça bunu belirtir. Görsel URL'si sunucudan indirilmez; tarayıcı CSP yalnızca izin verilen üretici görsel alanlarını açar.

## IP tablosu ve toplu işlemler

Ağ bloğu başlığı VLAN/isim/CIDR gösterir. Hostname, MAC, bağlı cihaz ve port ayrı sütunlardır. Güncel VMware bağlantısı varsa fiziksel FDB veya manuel port kaydından önce gerçek sanal switch adı, port grubu ve port numarası gösterilir. Port grubu ve port ayrı sütunlardır; bağlı cihaz hücresinde yalnızca cihaz adı bulunur. VMware kaydı yoksa tekil fiziksel uç port gösterilir. Aday switch adları birleştirilmez; kesin ilişki yoksa “Bağlantı doğrulanamadı” gösterilir. Aktif/pasif durumu yeşil/kırmızı işaretle tek satırdır; güncel durum bulunamıyorsa bilinmiyor gösterilir. Networkü izle ikon düğmesinin erişilebilir adı bulunur.

Arama her sözcüğü bütün sütunlarda, sayfalama öncesinde arar. Filtreler VE/VEYA ile soldan sağa uygulanır; içerir/içermez/eşittir/eşit değildir/büyük/küçük karşılaştırmaları vardır. Sütun tercihi kullanıcıya göre tarayıcıda saklanır. Çoklu seçim sayfalar arasında korunur, arama/filtre/ağ bloğu değişince temizlenir. Toplu düzenleme seçili alanları tek işlemde uygular; herhangi bir kayıt geçersizse tamamı geri alınır. IP ve MAC topluca değiştirilemez; kaynak gözlemi olan IP'nin adresi tekil formda da kilitlidir. Silme yönetici yetkisi ister.

Arayüz listesi yalnızca seçilen bağlı cihazın arayüzlerini içerir; API de cihaz/port/VRF ilişkisini doğrular. Doluluk, aynı VRF ve CIDR içinde son 24 saatteki son ICMP sonucu `reachable` olan IP sayısının kullanılabilir adres sayısına oranıdır. Yanıt vermeyen (`no_reply`), ping sonucu olmayan veya sonucu eskimiş IP’ler doluluğa ve aktif filtresine dahil edilmez. VMware güç durumu veya manuel atama durumu tek başına aktif IP kanıtı değildir. IP kayıtları, rezervasyonlar ve geçmiş gözlemler korunur. Tablo durumu, aktif filtre ve uyarı eşiği aynı ping kuralını kullanır. Ağ/yayın adresleri paydadan ve atama sayısından çıkarılır, `/31` ve `/32` korunur. Eşik eşitliğinde de uyarı görünür; ayarı kaydederken özet yeniden hesaplanır.

Ek doğrulamalar: `tests/test_ipam_hierarchy.py`, `scripts/ipam_hierarchy_browser_check.py` ve atılabilir MariaDB için `scripts/ipam_hierarchy_migration_check.py`. Tarayıcı testleri gerçek cihaz sorgusu yapmaz; üretici görselleri ayrı HTTP erişim kontrolüne tabi tutulur.

Bağlantı önceliği, trunk ayıklama, çakışma/eski gözlem, MAC eşleştirme ve sayfalı vCenter ad çözümlemesi: `tests/test_ipam_endpoint_connections.py`. API nesneleri: [Broadcom DSwitch](https://developer.broadcom.com/xapis/virtual-infrastructure-json-api/latest/virtual-infrastructure/distributed-virtual-switch/) ve [port grubu yapılandırması](https://dp-downloads-pstg.broadcom.com/api-content/apis/API_VWSA_001/8.0.3/html/ReferenceGuides/vim.dvs.DistributedVirtualPortgroup.ConfigInfo.html). Fiziksel MAC/port kontrolü: [Aruba AOS-S show mac-address](https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/WC/content/wc/sho-mac-add-vla-por-mac-add-tun.htm).

## Kaynak önceliği ve hızlı tablo okuması

Kimlik alanlarında kaynak sırası VMware → Windows DHCP → Corner Switch → Backbone Switch → Firewall şeklindedir. Yönetilen değerler korunur. DHCP kimlik/IP/MAC kaynağıdır; DHCP sunucusu fiziksel bağlı cihaz gibi gösterilmez. DHCP'den sonraki fiziksel bağlantı, FDB ve LLDP/CDP kanıtıyla çözülür. Sunucuya giden bir LACP bond, switchler arası uplink gibi elenmez: komşunun yönetim IP'si ve aynı port/aggregate üzerindeki IP-MAC/FDB eşleşmesi birlikte değerlendirilir. Trk portu ile C17–C20 gibi üyeler ayrı kanıt olarak korunur; hiçbir IP veya MAC'e özel cihaz adı sabitlenmez.

Tekil Corner eşleşmesi Backbone'dan, Backbone eşleşmesi Firewall ARP/NDP bilgisinden önceliklidir. Aynı öncelikte birden fazla uç port kesinleştirilmez. Firewall son seçenek olduğunda sonuç `routed` türündedir; ayrıntıda bunun ARP/NDP ağ arayüzü olduğu ve doğrudan fiziksel switch portunu kanıtlamadığı açıklanır. Kaynaklar arası MAC uyuşmazlığı bayrağı korunur; öncelikli kaynağın değeri gösterilir.

Tablo listeleri ham gözlem geçmişini ve tüm FDB adaylarını taşımaz; ayrıntı endpoint'i kanıtları sağlar. Cihaz başına yalnızca en son SNMP gözlemi seçilir; değişmeyen gözlem sürümlerinin ayrıştırılmış MAC indeksi süreç içinde, 256 gözlem/400.000 MAC sınırıyla tutulur. Gözlem sürümü, 24 saat sınırı, arşiv/VRF durumu ve arayüz değişiklikleri her önbelleksiz okumada tekrar değerlendirilir. Yalnızca gereken MAC/portlar eşleştirilir; kurum genelindeki tüm portlarda her satır için tekrar döngü kurulmaz. Ağ bloğu özetleri ortak sorgularla hesaplanır.

Kimlik doğrulamadan sonra kullanılan JSON yanıt önbelleği en fazla 5 saniyeliktir. API/worker yazımları refresh yayımlamadan önce Redis revizyonunu artırır; eski yanıt anahtarları kullanılmaz. Redis kesilirse 50 ms bağlantı/soket sınırı ve yeniden denemesiz istemciyle DB okumasına dönülür; hata sonrası 5 saniye önbellek denemesi ertelenir. Tarayıcıya `Cache-Control: no-store` uygulanır. `Server-Timing` başlığı IPAM işleyicisinin süresini ve hit/miss durumunu verir; kimlik doğrulama, ağ ve tarayıcı çizim süresi bu ölçüme dahil değildir. Sayfa açılışındaki sabit 200 ms bekleme kaldırılmıştır; yalnızca arama yazımı geciktirilir ve arka plan yenilemesi mevcut satırları kaldırmaz.

Aktif DHCP kiralarının resmi kaynağı: [Microsoft Get-DhcpServerv4Lease](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4lease?view=windowsserver2025-ps).

IP konum geçişi (`20261031_17`) yalnızca tek bir kurumlu lokasyonla tam ad eşleşmesi bulunan eski manuel değerleri ilişkiye çevirir. Aynı adlı, eşleşmeyen veya kurumsuz lokasyon metinleri korunur; tahmini kurum atanmaz. API yanlış kurum/lokasyon/alt lokasyon birleşimini reddeder. IP'lerin kullandığı lokasyon hiyerarşisini değiştirmek veya lokasyonu silmek için önce IP atamaları taşınmalıdır.
