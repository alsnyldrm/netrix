# VLAN tabanlı IP adres yönetimi

IP adres yönetimi → VLAN alanları ilk menüdür. VLAN kaydı IP bloğu/CIDR, VRF, DNS sunucusu, kurum, lokasyon, açıklama, IP kullanım uyarı eşiği ve tarama zamanlamalarını taşır. Ayrı Ağ blokları ve IP adresleri ekranları kaldırılmıştır. VLAN’a tıklanınca önceki IP tablosu aynı sütun, filtre, arama, düzenleme ve sayfalama davranışıyla açılır.

Yeni VLAN veya IP bloğu değişikliği aynı transaction içinde `ipam_discover` işi oluşturur. API ağ sorgusu yürütmez. VLAN eklemek o ağın IPAM taramasını tetikler; ek keşif kapsamı, SNMP profili veya ikinci onay gerekmez. Tarama yetkisi varsayılan açıktır; kapatılırsa ping/keşif durdurulur. IPv4 için ağ/yayın adresleri hariç en çok 65.536 adres, 32 eşzamanlı probe sınırıyla taranır. IPv6 uzayı tümüyle gezilmez; entegrasyonlar veya kullanıcı tarafından bilinen adresler kontrol edilir.

DNS ismi seçili DNS sunucusundan, seçim yoksa sistem çözümleyicisinden PTR ile alınır. DNS gözlemi bulunan adresin görünen isminde önceliklidir. Ping sonucu yalnızca son 24 saatte alınan ICMP yanıtından üretilir; VMware güç durumu ping yerine geçmez. Kullanım yüzdesi bu aktif IP sayısından hesaplanır. Yeni sunucuları düzenli ekle ve IP durumunu düzenli kontrol et seçenekleri birbirinden bağımsızdır.

## Envanter keşfinden bağımsızlık

Envanter → Ağ keşfi yalnızca cihaz envanterine hizmet eder. IPAM VLAN’larının keşif kapsamına FK’si yoktur; kapsam silme/devre dışı bırakma IPAM’ı etkilemez. IPAM, envanter keşif gözlemlerini veya bağlantı haritasını okumaz ve tarama sonucundan cihaz envanteri oluşturmaz. Ortak kurum/lokasyon ve kabinet tanımları korunur.

## Entegrasyonlar

Entegrasyonlar yalnızca IPAM içindir. Yetkili ağ blokları seçimi kaldırılmıştır; her etkin kaynak mevcut ve sonradan eklenen bütün VLAN’lara uygulanır. Farklı VRF’lerde aynı adresin hangi VLAN’a ait olduğu belirsizse kaynak o adresi otomatik atamaz.

- VMware: IP/MAC, OS, güç durumu, VM/NIC ve sanal switch/port grubu bilgileri.
- Windows DHCP: IPv4 rezervasyonları ve aktif kiralamalar, MAC/hostname kanıtları.
- Corner Switch: bağımsız kayıtlı SNMP bağlantısından ARP/NDP/FDB ve port bilgileri.
- Backbone Switch: aynı şekilde backbone katmanındaki bağımsız bağlantı kanıtları.

Kaynak sırası VMware → DHCP → Corner Switch → Backbone Switch’tir. VMware bağlantısı varsa fiziksel FDB geçişleri VM erişim portu gibi gösterilmez. Uplink ve birden fazla çelişen port belirsiz olarak korunur. Switch erişim profili entegrasyon üzerinde bir kez seçilir; VLAN’a ek profil girilmez. Kaynak sırları mevcut şifreli erişim kasasında kalır, API’ye dönmez.

## Veri geçişi ve silme

`20261101_21` migration mevcut IP bloklarının ayarlarını bağlı VLAN’a, IP’lerin FK’sini doğrudan VLAN’a taşır; eski blok tablosunu ve entegrasyon blok listesini kaldırır. Mevcut switch bağlantıları bir defaya mahsus bağımsız IPAM entegrasyonlarına taşınır. Sonraki cihaz/kapsam değişiklikleri bu kaynakları değiştirmez.

VLAN silme önizlemesi bağlı IP sayısını gösterir. Onayla birlikte ilgili ping/keşif işleri iptal edilir, VLAN ve IP gözlemleri silinir. Envanter keşfi ve entegrasyon kayıtları değişmez.
