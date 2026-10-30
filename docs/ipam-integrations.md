# IPAM, ağ bloğu politikaları ve entegrasyonlar

IP adres yönetimi → Ağ blokları ekranında CIDR’a tıklayın. Ağ/yayın adresleri dahil tüm IPv4/IPv6 alanı sayısal sırada, 100 adreslik sayfalarla gösterilir. Boş satırlar sanaldır; veritabanına milyarlarca boş IPv6 kaydı yazılmaz. Yalnızca kayıtlı IP filtresi de vardır. IP satırından işletim sistemi, kabinet no ve lokasyon düzenlenir; kaynak gözlemleri bu manuel değerleri değiştirmez.

Ağ bloğu ayarlarında DNS sunucusu (IP adres yönetimi → DNS sunucuları), VLAN’ın bulunduğu envanter cihazı, yetkili keşif kapsamı ve kullanım uyarı yüzdesi seçilir. Eşik ağ bloğu listesinde ve ayrıntısında uyarı gösterir. Kullanım sayısı kullanım dışı kayıtları içermez. ICMP yanıtı olmaması adresin boş olduğunu kanıtlamaz.

- **IP durumunu kontrol et:** yalnızca kayıtlı IP’leri ping ile kontrol eder. Zamanlama en az 30 saniyedir.
- **Yeni sunucuları ekle:** yetkili kapsamı ve hariç tutmaları uygulayarak ping taraması yapar; yanıtlayan yeni IP’leri ve seçilen DNS’ten PTR adlarını ekler. Envanter SNMP okumalarını ve ilgili etkin entegrasyonların eşitlemelerini de kuyruğa alır; MAC/OS/port bilgileri bu görevler tamamlandıkça eklenir. Zamanlama en az 60 saniyedir.
- IPv6 ve 4096 adresten büyük bloklarda keşif kapsamının açık hedef listesi gerekir. Sekiz eşzamanlı ICMP işlemi, 1 saniye ping beklemesi, 3 saniye süreç sınırı ve 2 saniye DNS çözümleme sınırı vardır. API tarama yapmaz; kalıcı worker işi döndürür. İptal sonraki batch ve kayıt öncesinde kontrol edilir; kaynak eşitlemeleri ayrı Görev merkezi kayıtlarıdır.
- Yönetilen cihaz kayıtları aynı VRF’deki en uzun uygun ağ bloğuna bağlanır. Mevcut envanter, ağ bloğu oluşturulduğunda/düzenlendiğinde eldeki son gözlemlerden bağlanır; cihazdan başarılı SNMP gözlemi geldikçe güncellenir. Firewall ARP/NDP bilgisi diğer switch’lerin FDB kayıtlarıyla eşleştirilir. Uplink ve çoklu adaylar belirsiz olarak kalır.

## Yönetim → Entegrasyonlar

Yönetici VMware vCenter veya Microsoft Windows DHCP tanımlar. Sunucu adı/IP, HTTPS portu, kullanıcı/parola, yetkili ağ blokları ve isteğe bağlı eşitleme aralığı girilir. Varsayılan kapalıdır; aralık 0 manuel çalışmadır. Kaydetmek kendi başına bağlantı açmaz. Etkinleştirip **Şimdi eşitle** seçin veya en az 60 saniyelik zamanlama ayarlayın. Sırlar mevcut uygulama şifreleme anahtarıyla şifrelenir; GET/API/audit yanıtlarına kullanıcı/parola veya şifreli içerik dönmez. Düzenlemede iki sır alanı boşsa saklanan erişim bilgileri korunur; sunucu değişiminde yeniden girilmelidir.

Entegrasyon okuması 240 saniyelik toplam döngü sınırı ve sınırlı soket beklemeleriyle çalışır. İptal sonrası sonuçlar kaydedilmez; başlamış senkron API/WinRM çağrısı kendi zaman aşımına kadar tamamlanabilir.

TLS doğrulaması varsayılan açıktır. Kurumsal CA’yı container trust store’a ekleyin (vCenter için `SSL_CERT_FILE`, WinRM/Requests için `REQUESTS_CA_BUNDLE` uygun secret/CA mount’una yönlendirilebilir). Formdaki TLS tercihi açıkça kaydedilir. Hiçbir cihaz, VM veya DHCP konfigürasyonu değiştirilmez.

### Microsoft Windows DHCP

Windows DHCP sunucusunda WinRM HTTPS (varsayılan 5986), DHCP Server PowerShell modülü ve uzaktan komut/rezervasyon okuma yetkisi gerekir. Kimlik `DOMAIN\kullanıcı` biçimindedir; NTLM HTTPS kullanılır. NETRIX yalnızca sabit `Get-DhcpServerv4Scope` ve `Get-DhcpServerv4Reservation` komutlarını çalıştırır; genel kullanıcı komut alanı yoktur. İlk sürüm IPv4 sabit rezervasyonları okur; dinamik kiraları veya DHCPv6 rezervasyonlarını içe almaz. Ethernet olmayan ClientId değerleri MAC olarak uydurulmaz.

Rezervasyonlar seçilen bloklara otomatik eklenir; ilgili etkin vCenter eşitlemesi sıraya alınır. vCenter’da tekil MAC eşleşmesi varsa konuk IP’si eksik veya farklı olsa bile işletim sistemi, güç ve NIC bilgisi rezervasyonda gösterilir. Kanıt `matched_by=dhcp_mac` ve varsa `guest_address` içerir. Bir MAC birden fazla VM/NIC’e aitse otomatik eşleşme yapılmaz.

### VMware vCenter

vSphere Web Services API (varsayılan 443) ve envanter/performans okuma yetkileri kullanılır. PropertyCollector ile sayfalı VM bilgisi alınır: konuk IP/MAC/hostname/OS, güç durumu, sanal NIC anahtarı, port grubu, DSwitch UUID/dvPort ve ESXi yönetilen nesne kimliği. Guest IP/OS bilgisi VMware Tools desteği ve güncelliğine bağlıdır; hardware NIC MAC ve yapılandırılmış OS, DHCP eşleştirmesine yardımcı olur. Başarısız eşitleme önceki veriyi silmez veya başarılı sayılmaz; 24 saatten eski gözlemler güncel değer olarak birleştirilmez, geçmiş olarak görünür.

## Networkü izle

IP ayrıntısından bir bağlantı kaynağı seçin. Envanter portu seçimi SNMP HC sayaçlarını doğrudan 5 saniyede bir okur; cihazın tamamında SNMP walk başlatmaz. Port trafiği portun toplamıdır, yalnızca o IP’nin trafiği olarak sunulmaz. İlk örnek başlangıçtır; sayaç sıfırlanması, discontinuity ve geçersiz kapasite örnekleri hız üretmez.

DSwitch için vCenter sanal NIC seçeneği API üzerinden `net.received.average` / `net.transmitted.average` ölçümlerini okur. VMware’in `QueryPerfProviderSummary.refreshRate` aralığı (genellikle 20 saniye) ve kaynak zaman damgası korunur. Ekranın 5 saniyede yenilenmesi, VMware’in 5 saniyelik yeni ölçüm ürettiği anlamına gelmez. Aynı kaynak zaman damgası yeniden saklanmaz; veri yokluğu sıfır trafik olarak çizilmez.

Canlı işler mevcut dört eşzamanlı interaktif worker kapasitesini kullanır. Her iş 12 sorgu sürer; açık görünüm tamamlanan işi yeniler. Duraklatma, pencere kapatma ve iptal yeni sorguları durdurur. Gizli tarayıcı sekmesi işi yenilemez. Yetki/kapsam/bağlantı seçimi her sorguda tekrar doğrulanır. Canlı örnekler yedi gün saklanır; görünüm son 15 dakikayı gösterir.

## Doğrulama ve kaynaklar

`tests/test_ipam_workspace.py`: kapsam/VRF/IPv6, şifreler, rol sınırları, DNS/ICMP, gözlem güncelliği, MAC korelasyonu, DHCP→VMware ve canlı trafik sayaçları. Gerçek ağa çıkılmaz. `scripts/ipam_migration_check.py` yalnızca atılabilir `netrix_test` MariaDB’de çalışır. `scripts/ipam_browser_check.py` yerel sahte veriyle 1440, 375 ve 812 px / açık-koyu tema kontrollerini yapar. Üretim vCenter/Windows DHCP erişim testi, ilgili sunucu ve erişim bilgileri tanımlanınca yapılmalıdır.

Resmi protokol kaynakları: [Microsoft DHCP rezervasyonları](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4reservation?view=windowsserver2025-ps), [DHCP kapsamları](https://learn.microsoft.com/en-us/powershell/module/dhcpserver/get-dhcpserverv4scope?view=windowsserver2025-ps), [vSphere konuk NIC bilgisi](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.vm.GuestInfo.NicInfo.html), [vSphere PerformanceManager](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.PerformanceManager.html), [pyVmomi](https://github.com/vmware/pyvmomi), [pywinrm](https://github.com/diyan/pywinrm).

## Sol menü ve tanım listeleri

IP adres yönetimi sırası: Ağ blokları → IP adresleri → VLAN alanları → Kabinetler → İşletim Sistemi → Lokasyon → DNS Sunucuları → Yönlendirme alanları.

Kabinetler ekranında kabinet no, ortak lokasyon ve açıklama; İşletim Sistemi ekranında ad ve açıklama yönetilir. Lokasyon ekranı envanterde kullanılan ortak kayıtları yönetmeye devam eder. IP formundaki işletim sistemi, kabinet ve lokasyon alanlarında bu listelerden öneriler seçilebilir veya mevcut serbest metin yöntemiyle değer girilebilir. Katalog değişiklikleri daha önce IP'ye kaydedilmiş metni otomatik değiştirmez.
