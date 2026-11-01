# VLAN tabanlı IP adres yönetimi

IP adres yönetimi → VLAN alanları ilk menüdür. VLAN kaydı IP bloğu/CIDR, VRF, DNS sunucusu, kurum, lokasyon, açıklama, IP kullanım uyarı eşiği ve tarama zamanlamalarını taşır. VLAN’a tıklanınca IP tablosu açılır.

Yeni VLAN veya IP bloğu değişikliği aynı transaction içinde `ipam_discover` işi oluşturur. API ağ sorgusu yürütmez. VLAN eklemek o ağın IPAM taramasını tetikler; ek yetki kutusu, keşif kapsamı, SNMP profili veya ikinci onay gerekmez. IPv4 için ağ/yayın adresleri hariç en çok 65.536 adres, 32 eşzamanlı probe sınırıyla taranır. IPv6 uzayı tümüyle gezilmez; entegrasyonlar veya kullanıcı tarafından bilinen adresler kontrol edilir.

DNS ismi seçili DNS sunucusundan, seçim yoksa sistem çözümleyicisinden PTR ile alınır. DNS gözlemi bulunan adresin görünen isminde önceliklidir. Ping sonucu yalnızca son 24 saatte alınan ICMP yanıtından üretilir; VMware güç durumu ping yerine geçmez. Kullanım yüzdesi bu aktif IP sayısından hesaplanır. Yeni sunucuları düzenli ekle ve IP durumunu düzenli kontrol et seçenekleri birbirinden bağımsızdır.

## Entegrasyonlar

Entegrasyonlar yalnızca **VMware vCenter** ve **Microsoft Windows DHCP** içerir. Switch, backbone veya firewall entegrasyonu eklenemez. VLAN taraması etkin DHCP ve VMware eşitlemelerini kuyruğa alır; her kaynak mevcut ve sonradan eklenen bütün VLAN’lara uygulanır. Ağ seçimi ve ayrıca tarama yetkisi gerekmez. Aynı adres farklı VRF’lerde belirsizse otomatik VLAN ataması yapılmaz.

- VMware: IP/MAC, OS, güç durumu, VM/NIC ve sanal switch/port grubu bilgileri.
- Windows DHCP: IPv4 rezervasyonları ve aktif kiralamalar, MAC/hostname kanıtları.

DHCP eşitlemesi VMware verisinin MAC üzerinden tamamlanmasını tetikler. Başarılı eşitleme VLAN’ların kayıtlı IP’leri için ping işlerini kuyruğa alır. VMware sanal switch/port bilgileri VMware verisinin parçasıdır; bağımsız switch entegrasyonu değildir.

Entegrasyon düzenlenirken kayıtlı şifreli kullanıcı/parola korunur. Yenilemek için “Kullanıcı/parolayı değiştir” seçilir; sunucu/port/tür değişirse iki bilgi birlikte yeniden girilir. Sırlar API’ye dönmez.

## Envanter keşfinden bağımsızlık

Envanter → Ağ keşfi yalnızca cihaz envanterine hizmet eder. IPAM VLAN’larının keşif kapsamına FK’si yoktur; kapsam silme/devre dışı bırakma IPAM’ı etkilemez. IPAM envanter switchlerini sorgulamaz, keşif gözlemlerini veya bağlantı haritasını okumaz ve tarama sonucundan cihaz envanteri oluşturmaz. Ortak kurum/lokasyon ve kabinet tanımları korunur. Uygulamanın kullanıcı/rol erişim denetimleri devam eder.

## Veri geçişi ve silme

`20261101_24` migration switch/backbone/firewall entegrasyon kayıtlarını ve IP gözlemlerini kaldırır; bekleyen/çalışan eşitleme işlerini iptal eder. DHCP/VMware kayıtları ve şifreli sırları, IP atamaları, envanter cihazları ve erişim kasası korunur. Ayrı VLAN tarama yetkisi alanı kaldırılır; mevcut ping/keşif zamanlama tercihleri korunur.

VLAN silme önizlemesi bağlı IP sayısını gösterir. Onayla birlikte ilgili ping/keşif işleri iptal edilir, VLAN ve IP gözlemleri silinir. Envanter keşfi ve entegrasyon kayıtları değişmez.
